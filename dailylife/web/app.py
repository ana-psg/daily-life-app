"""Servidor Flask do Daily Life: telas, segurança e o registro da API (web/api.py).

Rodar só no navegador (sem janela): python -m dailylife.web.app  ->  http://127.0.0.1:5055
O jeito normal de abrir o app é o programa instalado (ou: python main.py).
"""

import logging
import os
import secrets
import threading
from datetime import timedelta

from flask import Flask, jsonify

from dailylife import config, db
from dailylife.core import NotFound, ValidationError
from dailylife.web.api import bp as api_bp
from dailylife.web.api import desktop_hooks
from dailylife.web.pages import register_pages
from dailylife.web.security import register_security

log = logging.getLogger("dailylife.app")


def _secret_key() -> str:
    path = os.path.join(config.DATA_DIR, "secret.key")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def create_app(testing: bool = False) -> Flask:
    app = Flask(__name__, template_folder=config.TEMPLATES_DIR, static_folder=config.STATIC_DIR)
    app.config.update(
        SECRET_KEY=_secret_key(),
        TESTING=testing,
        SESSION_COOKIE_NAME=f"{config.APP_SLUG}_session",  # cookies valem para o endereço em qualquer porta
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )
    app.json.ensure_ascii = False
    app.register_blueprint(api_bp)
    db.init_db()
    register_security(app)
    register_pages(app)

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

    @app.errorhandler(OverflowError)
    def on_overflow(_e: Exception):
        return jsonify(erro="Data ou número fora do intervalo aceito."), 400

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from dailylife.desktop.scheduler import scheduler

    application = create_app()
    scheduler.start()
    desktop_hooks["sincronizar"] = scheduler.request_sync
    print(f"{config.APP_NAME} em http://127.0.0.1:{config.PORT}")
    application.run(host="127.0.0.1", port=config.PORT, threaded=True)
