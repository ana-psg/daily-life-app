"""Ícone do Daily Life na bandeja, perto do relógio."""

import logging
import os
import threading
from collections.abc import Callable
from typing import Any

from dailylife import config
from dailylife.desktop import notifier
from dailylife.desktop.scheduler import scheduler

log = logging.getLogger("dailylife.desktop")

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
