"""Calendários (categorias de compromissos): locais e do Google."""

import re
import sqlite3

from dailylife import config
from dailylife.core import NotFound, ValidationError, as_bool, require_text
from dailylife.db import get_conn, row, rows

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def list_all(conn: sqlite3.Connection | None = None, only_visible: bool = False) -> list[dict]:
    conn = conn or get_conn()
    q = "SELECT * FROM calendars"
    if only_visible:
        q += " WHERE visivel=1"
    q += " ORDER BY origem='google', ordem, nome"
    out = rows(conn.execute(q))
    for c in out:
        c["visivel"] = bool(c["visivel"])
        c["somente_leitura"] = bool(c["somente_leitura"])
    return out


def get(cal_id: int, conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or get_conn()
    c = row(conn.execute("SELECT * FROM calendars WHERE id=?", (cal_id,)))
    if not c:
        raise NotFound("Calendário não encontrado.")
    c["visivel"] = bool(c["visivel"])
    c["somente_leitura"] = bool(c["somente_leitura"])
    return c


def create(data: dict, conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or get_conn()
    nome = require_text(data, "nome", "O nome do calendário", 60)
    cor = data.get("cor") or "#7152F0"
    if not HEX.match(cor):
        raise ValidationError("Cor inválida.")
    stamp = config.iso(config.now())
    ordem = conn.execute("SELECT COALESCE(MAX(ordem),0)+1 FROM calendars").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO calendars (nome, cor, origem, ordem, criado_em, atualizado_em) "
        "VALUES (?,?, 'local', ?, ?, ?)",
        (nome, cor, ordem, stamp, stamp),
    )
    conn.commit()
    return get(cur.lastrowid, conn)


def update(cal_id: int, data: dict, conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or get_conn()
    get(cal_id, conn)
    fields = {}
    if "nome" in data:
        fields["nome"] = require_text(data, "nome", "O nome do calendário", 60)
    if "cor" in data:
        if not HEX.match(data["cor"] or ""):
            raise ValidationError("Cor inválida.")
        fields["cor"] = data["cor"]
    if "visivel" in data:
        fields["visivel"] = 1 if as_bool(data["visivel"]) else 0
    if not fields:
        return get(cal_id, conn)
    fields["atualizado_em"] = config.iso(config.now())
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE calendars SET {sets} WHERE id=?", (*fields.values(), cal_id))
    conn.commit()
    return get(cal_id, conn)


def delete(cal_id: int, conn: sqlite3.Connection | None = None) -> None:
    """Só calendários locais. Os compromissos vão para o primeiro calendário local que sobrar."""
    conn = conn or get_conn()
    c = get(cal_id, conn)
    if c["origem"] != "local":
        raise ValidationError("Calendários do Google não podem ser apagados aqui; esconda-o.")
    other = conn.execute(
        "SELECT id FROM calendars WHERE origem='local' AND id!=? ORDER BY ordem LIMIT 1", (cal_id,)
    ).fetchone()
    if not other:
        raise ValidationError("É preciso manter pelo menos um calendário local.")
    conn.execute("UPDATE events SET calendar_id=? WHERE calendar_id=?", (other["id"], cal_id))
    conn.execute("DELETE FROM calendars WHERE id=?", (cal_id,))
    conn.commit()
