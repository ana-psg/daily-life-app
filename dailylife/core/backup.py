"""Backup diário do banco e exportar/importar em JSON (Fase 8)."""

import glob
import os
import re
import sqlite3
from datetime import datetime

from dailylife import config
from dailylife.core import settings
from dailylife.db import get_conn, rows

KEEP = 14
TABLES = ["calendars", "events", "todos", "reminders", "settings"]
PREFIX = f"{config.APP_SLUG}-"


def make_backup(
    conn: sqlite3.Connection | None = None, force: bool = False, motivo: str = "manual"
) -> str | None:
    """Copia o banco para data/backups.

    Automático: dailylife-AAAA-MM-DD.db, uma vez por dia.
    Forçado (botão ou antes de importar): dailylife-AAAA-MM-DD-HHMMSS-<motivo>.db, sem sobrescrever.
    """
    conn = conn or get_conn()
    now = config.now()
    today = now.date().isoformat()
    if not force and settings.get("ultimo_backup", conn) == today:
        return None
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    name = f"{PREFIX}{today}.db" if not force else f"{PREFIX}{today}-{datetime.now():%H%M%S}-{motivo}.db"
    dest = os.path.join(config.BACKUP_DIR, name)
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
    finally:
        target.close()
    if not force:
        settings.set("ultimo_backup", today, conn)
    for old in _backup_files()[:-KEEP]:
        try:
            os.remove(old)
        except OSError:
            pass
    return dest


def _backup_files() -> list[str]:
    """Backups do mais antigo para o mais novo."""
    return sorted(glob.glob(os.path.join(config.BACKUP_DIR, f"{PREFIX}*.db")), key=os.path.getmtime)


def list_backups() -> list[dict]:
    return [
        {"arquivo": os.path.basename(f), "tamanho_kb": round(os.path.getsize(f) / 1024, 1)}
        for f in reversed(_backup_files())
    ]


def export_data(conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or get_conn()
    data = {"app": config.APP_NAME, "versao": 2, "exportado_em": config.iso(config.now())}
    for t in TABLES:
        data[t] = rows(conn.execute(f"SELECT * FROM {t}"))
    data["settings"] = [s for s in data["settings"] if s["chave"] != "pin_hash"]
    return data


def _upgrade_old_export(data: dict) -> None:
    """Exportações da versão 1 guardavam a lista da tarefa numa tabela à parte (todo_lists)."""
    keys = {item.get("id"): item.get("chave") for item in data.pop("todo_lists", None) or []}
    for t in data.get("todos") or []:
        if "lista" not in t:
            t["lista"] = keys.get(t.pop("list_id", None)) or "hoje"


def _validate_import(data: dict) -> None:
    """Confere o arquivo inteiro antes de apagar qualquer coisa."""
    from dailylife.core import recurrence, todos

    if not isinstance(data, dict) or data.get("app") != config.APP_NAME:
        raise ValueError(f"Este arquivo não é uma exportação do {config.APP_NAME}.")
    missing = [t for t in TABLES if not isinstance(data.get(t), list)]
    if missing:
        raise ValueError("Arquivo incompleto: faltam " + ", ".join(missing) + ".")
    hexcolor = re.compile(r"^#[0-9A-Fa-f]{6}$")
    for c in data["calendars"]:
        if not hexcolor.match(str(c.get("cor", ""))):
            raise ValueError("Arquivo com cor de calendário inválida.")
    for t in data["todos"]:
        if t.get("prioridade") not in todos.PRIORIDADES:
            raise ValueError("Arquivo com prioridade de tarefa inválida.")
        if t.get("lista") not in todos.LISTAS:
            raise ValueError("Arquivo com lista de tarefa inválida.")
    for r in data["reminders"]:
        if r.get("cor") not in ("amarelo", "rosa", "azul", "verde", "lilas"):
            raise ValueError("Arquivo com cor de lembrete inválida.")
        recurrence.parse_reminder_rule(r.get("repeticao") or "")
    for e in data["events"]:
        if (e.get("repeticao") or "") not in recurrence.EVENT_RULES:
            raise ValueError("Arquivo com repetição de compromisso inválida.")
    if not data["calendars"]:
        raise ValueError("Arquivo sem calendários.")


def import_data(data: dict, conn: sqlite3.Connection | None = None) -> dict[str, int]:
    """Substitui todos os dados pelos do arquivo. Faz um backup antes."""
    conn = conn or get_conn()
    if isinstance(data, dict):
        _upgrade_old_export(data)
    _validate_import(data)
    make_backup(conn, force=True, motivo="antes-de-importar")
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        conn.execute("DELETE FROM event_alerts")
        conn.execute("DELETE FROM sync_state")
        for t in reversed(TABLES):
            if t == "settings":
                conn.execute("DELETE FROM settings WHERE chave!='pin_hash'")
            else:
                conn.execute(f"DELETE FROM {t}")
        for t in TABLES:
            cols_db = {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")}
            for item in data.get(t, []):
                if t == "settings" and item.get("chave") == "pin_hash":
                    continue
                item = {k: v for k, v in item.items() if k in cols_db}
                if not item:
                    continue
                cols = ",".join(item)
                marks = ",".join("?" * len(item))
                conn.execute(f"INSERT OR REPLACE INTO {t} ({cols}) VALUES ({marks})", list(item.values()))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    from dailylife.db import init_db

    init_db(conn)  # recoloca os calendários padrão, se o arquivo não tiver nenhum local
    return {t: len(data.get(t, [])) for t in TABLES}
