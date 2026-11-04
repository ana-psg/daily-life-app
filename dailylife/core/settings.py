"""Configurações guardadas na tabela settings (valor em JSON)."""

import hashlib
import hmac
import json
import os
import sqlite3
from datetime import datetime
from typing import Any

from dailylife.core import ValidationError, as_bool, as_int, clean_text
from dailylife.db import get_conn

DEFAULTS = {
    "tema": "claro",  # claro | escuro | sistema
    "nome": "",
    "abrir_com_windows": False,
    "sempre_por_cima": False,
    "modo_inicial": "painel",  # painel | widget
    "notificacoes": True,
    "som": True,
    "nao_perturbe": False,
    "np_inicio": "22:00",
    "np_fim": "07:00",
    "sync_min": 5,
    "acesso_rede": False,
    "pin_hash": "",
    "janela_painel": {},
    "janela_widget": {},
    "ultimo_backup": "",
    "ultima_abertura": "",
}

# Chaves que a interface pode mudar diretamente
EDITABLE = {
    "tema",
    "nome",
    "abrir_com_windows",
    "sempre_por_cima",
    "modo_inicial",
    "notificacoes",
    "som",
    "nao_perturbe",
    "np_inicio",
    "np_fim",
    "sync_min",
    "acesso_rede",
}
PRIVATE = {"pin_hash"}


def get(key: str, conn: sqlite3.Connection | None = None) -> Any:
    conn = conn or get_conn()
    r = conn.execute("SELECT valor FROM settings WHERE chave=?", (key,)).fetchone()
    if r is None:
        return DEFAULTS.get(key)
    return json.loads(r["valor"])


def set(key: str, value: Any, conn: sqlite3.Connection | None = None) -> None:
    conn = conn or get_conn()
    conn.execute(
        "INSERT INTO settings (chave, valor) VALUES (?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
        (key, json.dumps(value, ensure_ascii=False)),
    )
    conn.commit()


def get_all(conn: sqlite3.Connection | None = None, public: bool = True) -> dict:
    conn = conn or get_conn()
    out = dict(DEFAULTS)
    for r in conn.execute("SELECT chave, valor FROM settings"):
        out[r["chave"]] = json.loads(r["valor"])
    if public:
        out["tem_senha"] = bool(out.get("pin_hash"))
        for k in PRIVATE:
            out.pop(k, None)
    return out


def _hhmm(value: Any, label: str) -> str:
    value = str(value or "").strip()
    try:
        h, m = (int(x) for x in value.split(":"))
    except ValueError:
        raise ValidationError(f"{label}: use o formato HH:MM.") from None
    # if em vez de assert: assert some quando o Python roda otimizado (-O)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValidationError(f"{label}: use o formato HH:MM.")
    return f"{h:02d}:{m:02d}"


def update(data: dict, conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or get_conn()
    clean = {}  # confere tudo antes de gravar: um valor errado não deixa a mudança pela metade
    for key, value in data.items():
        if key not in EDITABLE:
            raise ValidationError(f"Configuração desconhecida: {key}")
        if key == "tema" and value not in ("claro", "escuro", "sistema"):
            raise ValidationError("Tema inválido.")
        if key == "modo_inicial" and value not in ("painel", "widget"):
            raise ValidationError("Modo inicial inválido.")
        if key in ("np_inicio", "np_fim"):
            value = _hhmm(value, "Horário do não perturbe")
        if key == "sync_min":
            value = as_int(value, "Sincronização")
            if value not in (5, 15, 60):
                raise ValidationError("Sincronização: escolha 5, 15 ou 60 minutos.")
        if key == "nome":
            value = str(value).strip()[:40]
        if key in (
            "abrir_com_windows",
            "sempre_por_cima",
            "notificacoes",
            "som",
            "nao_perturbe",
            "acesso_rede",
        ):
            value = as_bool(value)
        clean[key] = value
    for key, value in clean.items():
        set(key, value, conn)
    return get_all(conn)


# ---------- senha de acesso pelo celular ----------
# Guardada como hash em "pin_hash" (nome da época do PIN de números; PINs antigos continuam valendo).


def _hash_password(password: str, salt: bytes) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + ":" + dk.hex()


def set_password(password: str, conn: sqlite3.Connection | None = None) -> None:
    password = clean_text(password, "Senha")
    if not 6 <= len(password) <= 64:
        raise ValidationError("A senha deve ter de 6 a 64 caracteres.")
    set("pin_hash", _hash_password(password, os.urandom(16)), conn)


def check_password(password: str, conn: sqlite3.Connection | None = None) -> bool:
    stored = get("pin_hash", conn) or ""
    if not stored or ":" not in stored:
        return False
    salt_hex, _ = stored.split(":", 1)
    return hmac.compare_digest(_hash_password((password or "").strip(), bytes.fromhex(salt_hex)), stored)


def in_quiet_hours(now_dt: datetime, conn: sqlite3.Connection | None = None) -> bool:
    """True se agora está no horário de não perturbe."""
    if not get("nao_perturbe", conn):
        return False
    ini = get("np_inicio", conn)
    fim = get("np_fim", conn)
    cur = now_dt.strftime("%H:%M")
    if ini <= fim:
        return ini <= cur < fim
    return cur >= ini or cur < fim
