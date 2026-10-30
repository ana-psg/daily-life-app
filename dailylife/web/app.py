"""Servidor Flask do Daily Life: telas, segurança e o registro da API (web/api.py).

Rodar só no navegador (sem janela): python -m dailylife.web.app  ->  http://127.0.0.1:5055
O jeito normal de abrir o app é o DailyLife.bat (main.py).
"""

import json
import logging
import os
import secrets
import threading
import time
from datetime import timedelta
from urllib.parse import urlsplit

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from dailylife import config, db
from dailylife.core import NotFound, ValidationError, settings
from dailylife.web.api import bp as api_bp
from dailylife.web.api import desktop_hooks
from dailylife.web.net import host_allowed, is_local_request, public_host, server_now

log = logging.getLogger("dailylife.app")

PAGES = {
    "/": "painel",
    "/widget": "widget",
    "/calendario": "calendario",
    "/todo": "todo",
    "/lembretes": "lembretes",
    "/config": "config",
}
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


def _secret_key() -> str:
    path = os.path.join(config.DATA_DIR, "secret.key")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def _safe_next(path: str | None) -> str:
    """Para onde voltar depois da senha: só caminhos deste app."""
    path = path or "/"
    return "/" if not path.startswith("/") or path.startswith("//") or "\\" in path else path


def create_app(testing: bool = False) -> Flask:
    app = Flask(__name__, template_folder=config.TEMPLATES_DIR, static_folder=config.STATIC_DIR)
    app.config.update(
        SECRET_KEY=_secret_key(),
        TESTING=testing,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )
    app.json.ensure_ascii = False
    app.register_blueprint(api_bp)
    db.init_db()

    # ---------------- segurança ----------------
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

    @app.teardown_request
    def close_conn(_exc: BaseException | None) -> None:
        # Cada requisição roda numa thread nova do servidor: fecha a conexão dela no fim
        if threading.current_thread() is not threading.main_thread():
            db.close_conn()

    # ---------------- erros ----------------
    @app.errorhandler(ValidationError)
    def on_validation(e: Exception):
        return jsonify(erro=str(e)), 400

    @app.errorhandler(NotFound)
    def on_notfound(e: Exception):
        return jsonify(erro=str(e)), 404

    @app.errorhandler(ValueError)
    def on_value(e: Exception):
        return jsonify(erro=str(e) or "Dado inválido."), 400

    # ---------------- telas ----------------
    def make_page(name: str):
        def view():
            return render_template(
                f"{name}.html",
                page=name,
                tema=settings.get("tema"),
                local=is_local_request(),
                agora=server_now(),
            )

        return view

    for path, name in PAGES.items():
        app.add_url_rule(path, name, make_page(name))

    @app.route("/entrar", methods=["GET", "POST"])
    def entrar():
        erro, status = "", 200
        ip = request.remote_addr or "?"
        if request.method == "POST":
            wait = login_blocked_for(ip)
            if wait:
                erro = f"Muitas tentativas. Tente de novo em {max(1, round(wait / 60))} min."
                status = 429
            elif settings.check_password(request.form.get("senha", "")):
                register_login(ip, True)
                session.clear()
                session.permanent = True
                session.update(pin_ok=True, pv=pin_version())
                return redirect(_safe_next(request.args.get("proximo")))
            else:
                register_login(ip, False)
                wait = login_blocked_for(ip)
                erro = (
                    f"Senha incorreta. Bloqueado por {round(wait / 60)} min." if wait else "Senha incorreta."
                )
                status = 429 if wait else 401
        return render_template("entrar.html", erro=erro, tema=settings.get("tema")), status

    @app.route("/sair")
    def sair():
        session.clear()
        return redirect(url_for("entrar"))

    @app.route("/manifest.webmanifest")
    def manifest():
        data = {
            "name": config.APP_NAME,
            "short_name": config.APP_NAME,
            "start_url": "/",
            "display": "standalone",
            "background_color": "#F4F2FA",
            "theme_color": "#7152F0",
            "lang": "pt-BR",
            "icons": [
                {"src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png"},
            ],
        }
        return Response(json.dumps(data, ensure_ascii=False), mimetype="application/manifest+json")

    @app.route("/sw.js")
    def service_worker():
        return send_from_directory(
            os.path.join(config.STATIC_DIR, "js"), "sw.js", mimetype="application/javascript"
        )

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from dailylife.desktop.scheduler import scheduler

    application = create_app()
    scheduler.start()
    desktop_hooks["sincronizar"] = scheduler.request_sync
    print(f"{config.APP_NAME} em http://127.0.0.1:{config.PORT}")
    application.run(host="127.0.0.1", port=config.PORT, threaded=True)
