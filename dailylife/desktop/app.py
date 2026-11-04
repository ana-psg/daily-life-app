"""Daily Life no Windows: abre o servidor, o agendador, a bandeja e as janelas.

Pelo código: python main.py
"""

import argparse
import json
import logging
import os
import sys
import threading
import urllib.request
from logging.handlers import RotatingFileHandler
from typing import Any

from flask import Flask

from dailylife import config

# pythonw (sem terminal) não tem stdout/stderr; evita erros de quem tentar escrever neles
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[RotatingFileHandler(config.LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")]
    + ([logging.StreamHandler()] if sys.stdout and sys.stdout.isatty() else []),
)
log = logging.getLogger("dailylife.desktop")

from werkzeug.serving import make_server

from dailylife import db
from dailylife.core import settings
from dailylife.desktop import notifier, startup
from dailylife.desktop.scheduler import scheduler
from dailylife.desktop.tray import start_tray
from dailylife.desktop.windows import BASE_URL, WEBVIEW_ERROR, BrowserDesktop, Desktop, webview
from dailylife.web import app as appmod


def already_running() -> bool:
    """Se já tem um Daily Life aberto, traz a janela para frente e devolve True."""
    try:
        with urllib.request.urlopen(f"{BASE_URL}/api/ping", timeout=1.5) as r:
            if json.loads(r.read()).get("app") != config.APP_NAME:
                return False
        req = urllib.request.Request(
            f"{BASE_URL}/api/janela/mostrar",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=2).read()
        return True
    except Exception:
        return False


class ServerThread(threading.Thread):
    def __init__(self, flask_app: Flask) -> None:
        super().__init__(daemon=True, name="servidor")
        if os.name == "nt":
            # No Windows, reaproveitar o endereço deixaria uma segunda cópia abrir na mesma porta
            from werkzeug.serving import ThreadedWSGIServer

            ThreadedWSGIServer.allow_reuse_address = False
        # Só neste PC: o celular chega pelo `tailscale serve`, que repassa para 127.0.0.1
        self.server = make_server("127.0.0.1", config.PORT, flask_app, threaded=True)

    def run(self) -> None:
        self.server.serve_forever()

    def shutdown(self) -> None:
        self.server.shutdown()


def log_blocked_modules() -> None:
    """Registra no log o que não carregou, para o diagnóstico."""
    if WEBVIEW_ERROR:
        log.warning("janela própria indisponível (pywebview): %s", WEBVIEW_ERROR)
    if not notifier.TOAST_OK:
        log.warning("avisos do Windows indisponíveis (win11toast): %s", notifier.TOAST_ERROR)
    for text in (WEBVIEW_ERROR, notifier.TOAST_ERROR):
        if "4551" in text or "Application Control" in text or "Controle de Aplicativo" in text:
            log.warning(
                "O Controle de Aplicativos Inteligente do Windows bloqueou uma biblioteca. "
                "Rode python tools/diagnostico.py para ver qual, ou veja o Manual."
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicializacao", action="store_true", help="aberto pelo Windows ao ligar o PC")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if already_running():
        log.info("Daily Life já estava aberto; janela trazida para frente")
        return

    db.init_db()
    startup.refresh()
    settings.set("ultima_abertura", config.iso(config.now()))

    flask_app = appmod.create_app()
    try:
        server = ServerThread(flask_app)
    except OSError as e:
        log.error("porta %s ocupada: %s", config.PORT, e)
        raise SystemExit(f"A porta {config.PORT} está em uso por outro programa.") from None
    server.start()

    log_blocked_modules()
    state = {"desk": Desktop() if webview else BrowserDesktop()}

    def use(desk: Any) -> None:
        state["desk"] = desk
        appmod.desktop_hooks.update(
            {
                "painel": desk.show_panel,
                "widget": desk.show_widget,
                "mostrar": desk.show_current,
                "abrir_url": desk.open_url,
                "esconder": desk.hide_all,
                "sair": desk.quit,
                "on_top": desk.set_on_top,
                "sincronizar": scheduler.request_sync,
            }
        )
        notifier.handlers["abrir"] = desk.show_current

    use(state["desk"])
    scheduler.start()
    start_tray(lambda: state["desk"])

    if webview:
        try:
            state["desk"].create_windows()
            storage = os.path.join(config.DATA_DIR, "webview")
            try:
                webview.settings["ALLOW_DOWNLOADS"] = True  # botão "Exportar (JSON)"
            except Exception:
                pass
            webview.start(debug=args.debug, private_mode=False, storage_path=storage)
            state["desk"].quit()
            return
        except Exception:
            log.exception("a janela própria não abriu; usando o Edge em modo aplicativo")
            use(BrowserDesktop())

    desk = state["desk"]
    desk.show_current()
    desk.done.wait()


if __name__ == "__main__":
    main()
