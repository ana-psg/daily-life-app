"""Quem pode pedir o quê: sites de fora, aparelhos sem senha e o limite de tentativas."""

import threading
import time
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, redirect, request, session, url_for

from dailylife import config
from dailylife.core import settings
from dailylife.web.net import host_allowed, is_local_request, public_host

PUBLIC_PATHS = ("/entrar", "/static/", "/manifest.webmanifest", "/sw.js", "/api/ping")
LOCAL_ONLY_API = (
    "/api/janela",
    "/api/config/senha",
    "/api/celular/",
    "/api/google/conectar",
    "/api/importar",
)

# Limite de tentativas de senha por endereço: depois de 5 erros, bloqueia 5 min (dobra a cada erro, até 1 h)
MAX_TRIES = 5
_login_fails: dict[str, dict] = {}
_login_lock = threading.Lock()


def login_blocked_for(ip: str, now: float | None = None) -> int:
    """Segundos que ainda faltam de bloqueio para esse endereço (0 = liberado)."""
    now = now if now is not None else time.monotonic()
    with _login_lock:
        info = _login_fails.get(ip)
        return max(0, round(info["ate"] - now)) if info else 0


def register_login(ip: str, ok: bool, now: float | None = None) -> None:
    now = now if now is not None else time.monotonic()
    with _login_lock:
        if ok:
            _login_fails.pop(ip, None)
            return
        info = _login_fails.setdefault(ip, {"erros": 0, "ate": 0.0})
        info["erros"] += 1
        extra = info["erros"] - MAX_TRIES
        if extra >= 0:
            info["ate"] = now + min(3600, 300 * (2**extra))


def pin_version() -> str:
    """Muda sempre que a senha muda (o hash leva um sal novo)."""
    return (settings.get("pin_hash") or "")[:16]


def register_security(app: Flask) -> None:
    @app.before_request
    def same_origin_only():
        """Bloqueia sites de fora: nome de domínio no Host (DNS rebinding) e envios de outra origem (CSRF)."""
        if not (host_allowed(request.host) and host_allowed(public_host())):
            return Response("Endereço não permitido.", 403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if request.headers.get("Sec-Fetch-Site") == "cross-site" or (
                origin and origin != "null" and urlsplit(origin).netloc != public_host()
            ):
                return jsonify(erro="Pedido de outro site bloqueado."), 403
        return None

    @app.before_request
    def guard():
        """Pedidos de outros aparelhos (pelo Tailscale): só com o acesso ligado e a senha digitada."""
        if is_local_request():
            return None
        path = request.path
        if not settings.get("acesso_rede"):
            return Response(f"Acesso pelo celular desligado nas Configurações do {config.APP_NAME}.", 403)
        if path.startswith(LOCAL_ONLY_API):
            return jsonify(erro="Disponível só no computador."), 403
        if path.startswith(PUBLIC_PATHS):
            return None
        if not settings.get("pin_hash"):
            return Response(
                f"Crie uma senha nas Configurações do {config.APP_NAME} para usar no celular.", 403
            )
        if session.get("pin_ok") and session.get("pv") == pin_version():
            return None  # trocar a senha desconecta os outros aparelhos
        if path.startswith("/api/"):
            return jsonify(erro="Digite a senha."), 401
        return redirect(url_for("entrar", proximo=path))
