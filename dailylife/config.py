"""Caminhos e constantes do Daily Life.

Funciona rodando pelo Python ou empacotado como .exe (PyInstaller).
Dados e credenciais ficam na pasta do app; telas e estilos, dentro do pacote.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

APP_NAME = "Daily Life"
APP_SLUG = "dailylife"  # nome sem espaço para arquivos, registro e chaves
PORT = int(os.environ.get("DAILYLIFE_PORT", "5055"))
TZ = ZoneInfo("America/Sao_Paulo")

if getattr(sys, "frozen", False):  # .exe: recursos dentro do pacote, dados ao lado do executável
    PACKAGE_DIR = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "dailylife")
    BASE_DIR = os.path.dirname(sys.executable)
else:
    PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = os.path.dirname(PACKAGE_DIR)

DATA_DIR = os.environ.get("DAILYLIFE_DATA", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, f"{APP_SLUG}.db")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
TOKEN_PATH = os.path.join(DATA_DIR, "token.json")
LOG_PATH = os.path.join(DATA_DIR, f"{APP_SLUG}.log")
CREDENTIALS_PATH = os.environ.get("DAILYLIFE_CREDENTIALS", os.path.join(BASE_DIR, "credentials.json"))
TEMPLATES_DIR = os.path.join(PACKAGE_DIR, "templates")
STATIC_DIR = os.path.join(PACKAGE_DIR, "static")
ICON_PNG = os.path.join(STATIC_DIR, "img", "icon-256.png")

os.makedirs(DATA_DIR, exist_ok=True)


def now() -> datetime:
    """Hora de São Paulo sem fuso e sem segundos (é assim que gravamos no banco)."""
    return datetime.now(TZ).replace(tzinfo=None, second=0, microsecond=0)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def parse_iso(value: str) -> datetime:
    if not value:
        raise ValueError("data vazia")
    value = value.strip().replace(" ", "T")
    if len(value) == 10:
        value += "T00:00"
    return datetime.strptime(value[:16], "%Y-%m-%dT%H:%M")
