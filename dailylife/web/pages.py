"""Telas, entrada com senha, manifest do app no celular e service worker."""

import json
import os

from flask import Flask, Response, redirect, render_template, request, send_from_directory, session, url_for

from dailylife import config
from dailylife.core import settings
from dailylife.web.net import is_local_request, server_now
from dailylife.web.security import login_blocked_for, pin_version, register_login

PAGES = {
    "/": "painel",
    "/widget": "widget",
    "/calendario": "calendario",
    "/todo": "todo",
    "/lembretes": "lembretes",
    "/config": "config",
}


def _safe_next(path: str | None) -> str:
    """Para onde voltar depois da senha: só caminhos deste app."""
    path = path or "/"
    return "/" if not path.startswith("/") or path.startswith("//") or "\\" in path else path


def register_pages(app: Flask) -> None:
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
