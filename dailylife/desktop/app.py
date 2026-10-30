"""Daily Life no Windows: janelas (painel e widget), bandeja, agendador e servidor.

Abrir: DailyLife.bat  (ou: python main.py)
"""

import argparse
import json
import logging
import os
import sys
import threading
import urllib.request
from collections.abc import Callable
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

try:
    import webview

    WEBVIEW_ERROR = ""
except Exception as e:  # bloqueado pelo Controle de Aplicativos Inteligente, ou não instalado
    webview = None
    WEBVIEW_ERROR = str(e)
from werkzeug.serving import make_server

from dailylife import db
from dailylife.core import settings
from dailylife.desktop import (
    notifier,
    startup,
)
from dailylife.desktop.scheduler import scheduler
from dailylife.web import app as appmod

BASE_URL = f"http://127.0.0.1:{config.PORT}"
BG = {"claro": "#F4F2FA", "escuro": "#111017", "sistema": "#F4F2FA"}


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


class Debounce:
    def __init__(self, delay: float, fn: Callable) -> None:
        self.delay, self.fn, self.timer = delay, fn, None

    def __call__(self, *args: Any) -> None:
        if self.timer:
            self.timer.cancel()
        self.timer = threading.Timer(self.delay, self.fn, args)
        self.timer.daemon = True
        self.timer.start()


class Desktop:
    def __init__(self) -> None:
        self.painel = None
        self.widget = None
        self.quitting = False
        self.modo = settings.get("modo_inicial") or "painel"
        self.geo = {
            "painel": dict(settings.get("janela_painel") or {}),
            "widget": dict(settings.get("janela_widget") or {}),
        }

    @staticmethod
    def _sane(geo: dict) -> dict:
        """Descarta posição de janela minimizada (-32000) ou fora de qualquer tela razoável."""
        geo = dict(geo)
        x, y = geo.get("x"), geo.get("y")
        if x is None or y is None or not (-4000 < x < 12000 and -2000 < y < 8000):
            geo.pop("x", None)
            geo.pop("y", None)
        if not (300 <= geo.get("w", 800) <= 8000 and 300 <= geo.get("h", 800) <= 8000):
            geo.pop("w", None)
            geo.pop("h", None)
        return geo

    # ---------- janelas ----------
    def create_windows(self) -> None:
        tema = settings.get("tema") or "claro"
        gp, gw = self._sane(self.geo["painel"]), self._sane(self.geo["widget"])
        self.geo = {"painel": gp, "widget": gw}
        self.painel = webview.create_window(
            config.APP_NAME,
            f"{BASE_URL}/",
            width=gp.get("w", 1280),
            height=gp.get("h", 860),
            x=gp.get("x"),
            y=gp.get("y"),
            min_size=(400, 560),
            background_color=BG.get(tema),
            hidden=self.modo != "painel",
            text_select=True,
        )
        self.widget = webview.create_window(
            f"{config.APP_NAME} · widget",
            f"{BASE_URL}/widget",
            width=gw.get("w", 380),
            height=gw.get("h", 680),
            x=gw.get("x"),
            y=gw.get("y"),
            min_size=(320, 480),
            frameless=True,
            easy_drag=False,
            on_top=bool(settings.get("sempre_por_cima")),
            background_color=BG.get(tema),
            hidden=self.modo != "widget",
        )
        for name, win in (("painel", self.painel), ("widget", self.widget)):
            win.events.closing += self._closing(win)
            save = Debounce(0.8, lambda n=name: self._save_geo(n))
            win.events.moved += self._track(name, "pos", save)
            win.events.resized += self._track(name, "size", save)

    def _closing(self, win: Any) -> Callable[[], bool]:
        def handler() -> bool:
            if self.quitting or windows_shutting_down():
                self.quitting = True
                return True
            threading.Thread(target=win.hide, daemon=True).start()
            return False  # cancela o fechamento: o app continua na bandeja

        return handler

    def _track(self, name: str, kind: str, save: Callable) -> Callable[..., None]:
        def handler(*args: Any) -> None:
            if len(args) < 2:
                return
            a, b = args[-2], args[-1]  # algumas versões passam a janela antes
            if kind == "pos" and (a <= -30000 or b <= -30000):
                return  # janela minimizada: não guarda essa posição
            if kind == "pos":
                self.geo[name].update(x=a, y=b)
            else:
                self.geo[name].update(w=a, h=b)
            save()

        return handler

    def _save_geo(self, name: str) -> None:
        try:
            settings.set(f"janela_{name}", self.geo[name])
        except Exception:
            log.exception("não salvou posição da janela")

    def show_panel(self) -> None:
        self.modo = "painel"
        self.widget.hide()
        self.painel.show()
        self.painel.restore()

    def show_widget(self) -> None:
        self.modo = "widget"
        self.painel.hide()
        self.widget.show()

    def open_url(self, path: str) -> None:
        """Abre uma tela no painel (usado pelos links do widget)."""
        self.painel.load_url(f"{BASE_URL}{path}")
        self.show_panel()

    def show_current(self) -> None:
        (self.show_widget if self.modo == "widget" else self.show_panel)()

    def hide_all(self) -> None:
        self.painel.hide()
        self.widget.hide()

    def set_on_top(self, value: bool) -> None:
        try:
            self.widget.on_top = bool(value)
        except Exception:
            log.exception("on_top")

    def quit(self) -> None:
        log.info("saindo")
        self.quitting = True
        scheduler.stop()
        stop_tray()
        for win in (self.widget, self.painel):
            try:
                win.destroy()
            except Exception:
                pass
        threading.Timer(1.5, lambda: os._exit(0)).start()


def windows_shutting_down() -> bool:
    """True quando o Windows está desligando ou encerrando a sessão (não segura o desligamento)."""
    if os.name != "nt":
        return False
    try:
        import ctypes

        SM_SHUTTINGDOWN = 0x2000
        return bool(ctypes.windll.user32.GetSystemMetrics(SM_SHUTTINGDOWN))
    except Exception:
        return False


def find_edge() -> str | None:
    for base in (
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramFiles"),
        os.environ.get("LOCALAPPDATA"),
    ):
        if base:
            path = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.exists(path):
                return path
    return None


class BrowserDesktop:
    """Plano B quando a janela própria (pywebview) não abre: usa o Edge em modo aplicativo.

    Funciona tudo, menos o widget sem bordas e o "sempre por cima".
    """

    def __init__(self) -> None:
        self.modo = settings.get("modo_inicial") or "painel"
        self.quitting = False
        self.done = threading.Event()
        self.edge = find_edge()

    def _open(self, path: str, size: str) -> None:
        url = f"{BASE_URL}{path}"
        if self.edge:
            import subprocess

            subprocess.Popen([self.edge, f"--app={url}", f"--window-size={size}"])
        else:
            import webbrowser

            webbrowser.open(url)

    def show_panel(self) -> None:
        self.modo = "painel"
        self._open("/", "1280,860")

    def show_widget(self) -> None:
        self.modo = "widget"
        self._open("/widget", "380,680")

    def open_url(self, path: str) -> None:
        self._open(path, "1280,860")

    def show_current(self) -> None:
        (self.show_widget if self.modo == "widget" else self.show_panel)()

    def hide_all(self) -> None:
        pass  # a janela do Edge é fechada pelo próprio X

    def set_on_top(self, value: bool) -> None:
        pass

    def quit(self) -> None:
        log.info("saindo (modo navegador)")
        self.quitting = True
        scheduler.stop()
        stop_tray()
        self.done.set()
        threading.Timer(1.5, lambda: os._exit(0)).start()


# ---------- bandeja (independente da janela) ----------
_tray = {"icon": None}


def start_tray(get_desk: Callable) -> Any:
    """Ícone perto do relógio. Sem ele, os avisos ainda funcionam; só não há o menu."""
    try:
        import pystray
        from PIL import Image
    except Exception as e:
        log.warning("sem ícone na bandeja (pystray/Pillow não carregaram): %s", e)
        return None
    image = (
        Image.open(config.ICON_PNG)
        if os.path.exists(config.ICON_PNG)
        else Image.new("RGB", (64, 64), "#7152F0")
    )
    menu = pystray.Menu(
        pystray.MenuItem("Abrir painel", lambda: get_desk().show_panel(), default=True),
        pystray.MenuItem("Abrir widget", lambda: get_desk().show_widget()),
        pystray.MenuItem("Sincronizar com o Google", lambda: scheduler.request_sync()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair do Daily Life", lambda: get_desk().quit()),
    )
    icon = pystray.Icon("Daily Life", image, "Daily Life", menu)
    threading.Thread(target=icon.run, daemon=True, name="bandeja").start()
    _tray["icon"] = icon
    notifier.handlers["balao"] = lambda titulo, corpo: icon.notify(corpo or " ", titulo)
    return icon


def stop_tray() -> None:
    try:
        if _tray["icon"]:
            _tray["icon"].stop()
    except Exception:
        pass


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
                "Rode diagnostico.bat para ver qual."
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
