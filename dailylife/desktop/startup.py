"""Abrir o Daily Life junto com o Windows.

Usa a chave do usuário HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run,
que não precisa de administrador. Fora do Windows não faz nada.
"""

import os
import sys

from dailylife import config

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DailyLife"

try:
    import winreg  # type: ignore
except ImportError:  # pragma: no cover - fora do Windows
    winreg = None


def command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --inicializacao'
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pythonw):
        exe = pythonw  # sem janela de terminal
    script = os.path.join(config.BASE_DIR, "main.py")
    return f'"{exe}" "{script}" --inicializacao'


def is_supported() -> bool:
    return winreg is not None


def _has_value(name: str) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, name)
            return True
    except OSError:
        return False


def is_enabled() -> bool:
    return winreg is not None and _has_value(VALUE_NAME)


def refresh() -> None:
    """Ao abrir: atualiza o caminho se a pasta mudou."""
    if is_enabled():
        set_enabled(True)


def set_enabled(enabled: bool) -> bool:
    if winreg is None:
        return False
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
    return True
