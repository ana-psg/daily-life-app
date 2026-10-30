"""Avisos no celular por notificação web (Web Push), sem serviço pago.

O navegador do celular (Chrome no Android) cria uma "inscrição" com um endereço do
serviço de push dele. O PC cifra o aviso (RFC 8291, aes128gcm) e o envia para esse
endereço, assinado com a chave VAPID do app (RFC 8292). Só precisa da biblioteca
cryptography; se ela não carregar, o resto do app funciona sem os avisos no celular.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import struct
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from dailylife import config
from dailylife.db import get_conn, rows

log = logging.getLogger("dailylife.push")

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    AVAILABLE = True
except Exception:  # não instalada, ou bloqueada pelo Controle de Aplicativos Inteligente
    AVAILABLE = False

RECORD_SIZE = 4096
TTL = 4 * 3600  # aviso que não chegar em 4 h (celular desligado) é descartado
_key_lock = threading.Lock()


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def _raw_public(key: "ec.EllipticCurvePrivateKey") -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


# ---------------- chave do app (VAPID) ----------------
def _app_key() -> "ec.EllipticCurvePrivateKey":
    path = os.path.join(config.DATA_DIR, "push_key.pem")
    with _key_lock:
        if not os.path.exists(path):
            key = ec.generate_private_key(ec.SECP256R1())
            pem = key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
            with open(path, "wb") as f:
                f.write(pem)
        with open(path, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)


def public_key() -> str:
    """Chave pública que o navegador usa para criar a inscrição (applicationServerKey)."""
    return b64(_raw_public(_app_key())) if AVAILABLE else ""


def vapid_header(endpoint: str, now: float | None = None) -> str:
    """Cabeçalho Authorization: um JWT ES256 curto dizendo que o aviso vem deste app."""
    key = _app_key()
    url = urlsplit(endpoint)
    claims = {
        "aud": f"{url.scheme}://{url.netloc}",
        "exp": int((now or time.time()) + 12 * 3600),
        "sub": "mailto:daily-life@localhost",
    }
    head = b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = b64(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{head}.{body}".encode()
    r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"vapid t={head}.{body}.{b64(signature)}, k={b64(_raw_public(key))}"


# ---------------- cifragem (RFC 8291) ----------------
def encrypt(
    payload: bytes,
    ua_public: bytes,
    auth_secret: bytes,
    server_key: "ec.EllipticCurvePrivateKey | None" = None,
    salt: bytes | None = None,
) -> bytes:
    """Cifra o aviso para um navegador. server_key e salt só são passados nos testes."""
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    as_public = _raw_public(server_key)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = server_key.exchange(ec.ECDH(), ua_key)
    prk_key = _hmac(auth_secret, shared)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # \x02 = último (e único) registro
    header = salt + struct.pack(">IB", RECORD_SIZE, len(as_public)) + as_public
    return header + ciphertext


# ---------------- inscrições ----------------
def subscribe(sub: dict, aparelho: str = "", conn: sqlite3.Connection | None = None) -> None:
    from dailylife.core import ValidationError

    conn = conn or get_conn()
    keys = sub.get("keys") or {}
    endpoint = str(sub.get("endpoint") or "")
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise ValidationError("Inscrição de avisos inválida.")
    try:
        if len(unb64(keys["p256dh"])) != 65 or len(unb64(keys["auth"])) != 16:
            raise ValueError
    except ValueError:
        raise ValidationError("Inscrição de avisos inválida.") from None
    conn.execute(
        "INSERT OR REPLACE INTO push_subs (endpoint, p256dh, auth, aparelho, criado_em) VALUES (?,?,?,?,?)",
        (endpoint, keys["p256dh"], keys["auth"], aparelho[:80], config.iso(config.now())),
    )
    conn.commit()


def unsubscribe(endpoint: str, conn: sqlite3.Connection | None = None) -> None:
    conn = conn or get_conn()
    conn.execute("DELETE FROM push_subs WHERE endpoint=?", (endpoint,))
    conn.commit()


def devices(conn: sqlite3.Connection | None = None) -> list[dict]:
    conn = conn or get_conn()
    return rows(conn.execute("SELECT endpoint, aparelho, criado_em FROM push_subs ORDER BY criado_em"))


# ---------------- envio ----------------
def send_one(sub: dict, message: dict) -> int:
    """Envia um aviso; devolve o código HTTP (201 = entregue ao serviço de push)."""
    data = encrypt(json.dumps(message, ensure_ascii=False).encode(), unb64(sub["p256dh"]), unb64(sub["auth"]))
    req = urllib.request.Request(
        sub["endpoint"],
        data=data,
        method="POST",
        headers={
            "Authorization": vapid_header(sub["endpoint"]),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(TTL),
            "Urgency": "high",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def send_all(message: dict) -> int:
    """Envia para todos os aparelhos inscritos e devolve quantos receberam. Inscrições vencidas saem."""
    if not AVAILABLE:
        return 0
    conn = get_conn()
    sent = 0
    for sub in rows(conn.execute("SELECT * FROM push_subs")):
        try:
            code = send_one(sub, message)
        except OSError as e:  # sem internet: o aviso no celular se perde, o do PC continua
            log.warning("push sem conexão: %s", e)
            continue
        if code in (404, 410):
            unsubscribe(sub["endpoint"], conn)
        elif 200 <= code < 300:
            sent += 1
        else:
            log.warning("push recusado (%s) para %s", code, urlsplit(sub["endpoint"]).netloc)
    return sent


def send_async(message: dict) -> None:
    """Envia sem segurar quem chamou (o agendador continua no ritmo dele)."""
    if not AVAILABLE:
        return

    def run() -> None:
        from dailylife import db

        try:
            send_all(message)
        except Exception:
            log.exception("falha ao enviar avisos para o celular")
        finally:
            db.close_conn()

    threading.Thread(target=run, daemon=True, name="push").start()
