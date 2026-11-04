"""As janelas do app: painel e widget (pywebview), ou o Edge como plano B."""

import logging
import os
import threading
from collections.abc import Callable
from typing import Any

from dailylife import config
from dailylife.core import settings
from dailylife.desktop.scheduler import scheduler
from dailylife.desktop.tray import stop_tray

try:
    import webview

    WEBVIEW_ERROR = ""
except Exception as e:  # bloqueado pelo Controle de Aplicativos Inteligente, ou não instalado
    webview = None
    WEBVIEW_ERROR = str(e)

log = logging.getLogger("dailylife.desktop")

BASE_URL = f"http://127.0.0.1:{config.PORT}"
BG = {"claro": "#F4F2FA", "escuro": "#111017", "sistema": "#F4F2FA"}


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
