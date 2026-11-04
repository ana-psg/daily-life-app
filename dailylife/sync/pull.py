"""Baixa do Google o que mudou: calendários, compromissos, séries e ocorrências alteradas."""

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from dailylife import config
from dailylife.core import recurrence
from dailylife.db import rows
from dailylife.sync.common import HttpError
from dailylife.sync.convert import item_fields, original_start, to_local

log = logging.getLogger("dailylife.google")


def sync_calendars(svc: Any, conn: sqlite3.Connection) -> None:
    stamp = config.iso(config.now())
    seen = set()
    token = None
    while True:
        resp = svc.calendarList().list(pageToken=token, maxResults=250).execute()
        for c in resp.get("items", []):
            gid = c["id"]
            seen.add(gid)
            ro = 1 if c.get("accessRole") in ("reader", "freeBusyReader") else 0
            nome = c.get("summaryOverride") or c.get("summary") or gid
            cor = (c.get("backgroundColor") or "#5B7FFF").upper()
            existing = conn.execute("SELECT id FROM calendars WHERE google_id=?", (gid,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE calendars SET nome=?, somente_leitura=?, atualizado_em=? WHERE id=?",
                    (nome, ro, stamp, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO calendars (nome, cor, origem, google_id, visivel, somente_leitura, "
                    "ordem, criado_em, atualizado_em) VALUES (?,?, 'google', ?, 1, ?, 100, ?, ?)",
                    (nome, cor, gid, ro, stamp, stamp),
                )
        token = resp.get("nextPageToken")
        if not token:
            break
    # calendários removidos da conta
    for r in rows(conn.execute("SELECT id, google_id FROM calendars WHERE origem='google'")):
        if r["google_id"] not in seen:
            conn.execute("DELETE FROM events WHERE calendar_id=?", (r["id"],))
            conn.execute("DELETE FROM sync_state WHERE calendar_id=?", (r["id"],))
            conn.execute("DELETE FROM calendars WHERE id=?", (r["id"],))
    conn.commit()


def _local_is_newer(local: sqlite3.Row | None, item: dict) -> bool:
    """Edição feita no app e ainda não enviada, mais recente que a do Google."""
    if not local or not local["pendente_sync"]:
        return False
    updated = to_local(item["updated"]) if item.get("updated") else config.now()
    return local["atualizado_em"] > config.iso(updated)


def _upsert(conn: sqlite3.Connection, local_id: int | None, fields: dict) -> None:
    stamp = config.iso(config.now())
    fields = {**fields, "pendente_sync": 0, "excluido": 0, "atualizado_em": stamp}
    if local_id:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE events SET {sets} WHERE id=?", (*fields.values(), local_id))
    else:
        fields["criado_em"] = stamp
        conn.execute(
            f"INSERT INTO events ({','.join(fields)}) VALUES ({','.join('?' * len(fields))})",
            tuple(fields.values()),
        )


def _apply_series_or_single(conn: sqlite3.Connection, cal_id: int, item: dict) -> None:
    """Compromisso simples ou série (com a regra de repetição)."""
    gid = item["id"]
    local = conn.execute(
        "SELECT * FROM events WHERE calendar_id=? AND google_event_id=?", (cal_id, gid)
    ).fetchone()
    if item.get("status") == "cancelled":
        if local:
            conn.execute("DELETE FROM events WHERE serie_id=?", (local["id"],))
            conn.execute("DELETE FROM events WHERE id=?", (local["id"],))
        return
    if _local_is_newer(local, item):
        return  # vai subir no próximo envio
    try:
        fields = item_fields(item)
    except (KeyError, ValueError):
        return
    rec = "\n".join(item.get("recurrence") or [])
    tz = None if fields["dia_inteiro"] else (item.get("start") or {}).get("timeZone")
    simple = recurrence.google_rule_to_simple(rec, config.parse_iso(fields["inicio"]), tz) if rec else ""
    fields.update(
        repeticao=simple or "",
        rrule=None if (simple or not rec) else rec,
        fuso=tz if (rec and not simple) else None,
        calendar_id=cal_id,
        google_event_id=gid,
        serie_id=None,
        ocorrencia=None,
        cancelado=0,
    )
    _upsert(conn, local["id"] if local else None, fields)


def _apply_instance(conn: sqlite3.Connection, cal_id: int, item: dict) -> None:
    """Uma ocorrência alterada ou excluída de uma série do Google."""
    master = conn.execute(
        "SELECT * FROM events WHERE calendar_id=? AND google_event_id=?", (cal_id, item["recurringEventId"])
    ).fetchone()
    cancelled = item.get("status") == "cancelled"
    if not master:
        if cancelled:  # convite para uma ocorrência só, cancelado: some daqui também
            conn.execute("DELETE FROM events WHERE calendar_id=? AND google_event_id=?", (cal_id, item["id"]))
        else:  # série fora do período baixado: guarda como compromisso simples
            _apply_series_or_single(conn, cal_id, item)
        return
    try:
        occ = original_start(item)
    except (KeyError, ValueError):
        return
    found = conn.execute(
        "SELECT * FROM events WHERE (calendar_id=? AND google_event_id=?) OR (serie_id=? AND ocorrencia=?) "
        "ORDER BY serie_id IS NULL",
        (cal_id, item["id"], master["id"], occ),
    ).fetchall()
    local = found[0] if found else None
    for extra in found[1:]:  # cópia antiga da mesma ocorrência (versão anterior do app)
        conn.execute("DELETE FROM events WHERE id=?", (extra["id"],))
    if _local_is_newer(local, item):
        return
    if cancelled:
        dur = config.parse_iso(master["fim"]) - config.parse_iso(master["inicio"])
        fields = {
            "titulo": master["titulo"],
            "inicio": occ,
            "fim": config.iso(config.parse_iso(occ) + dur),
            "dia_inteiro": master["dia_inteiro"],
            "local": master["local"],
            "notas": master["notas"],
            "aviso_min": master["aviso_min"],
            "google_etag": item.get("etag"),
        }
    else:
        try:
            fields = item_fields(item)
        except (KeyError, ValueError):
            return
    fields.update(
        calendar_id=cal_id,
        google_event_id=item["id"],
        serie_id=master["id"],
        ocorrencia=occ,
        repeticao="",
        rrule=None,
        cancelado=1 if cancelled else 0,
    )
    _upsert(conn, local["id"] if local else None, fields)


def pull_calendar(svc: Any, conn: sqlite3.Connection, cal: dict) -> None:
    """Baixa as mudanças de um calendário. Séries vêm como uma regra só (singleEvents=False)."""
    state = conn.execute("SELECT sync_token FROM sync_state WHERE calendar_id=?", (cal["id"],)).fetchone()
    sync_token = state["sync_token"] if state else None
    params = {"calendarId": cal["google_id"], "singleEvents": False, "showDeleted": True, "maxResults": 250}
    if sync_token:
        params["syncToken"] = sync_token
    else:
        params["timeMin"] = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    page = None
    next_sync = None
    items = []
    while True:
        try:
            resp = svc.events().list(pageToken=page, **params).execute()
        except HttpError as e:
            if getattr(e, "resp", None) is not None and e.resp.status == 410:
                conn.execute("DELETE FROM sync_state WHERE calendar_id=?", (cal["id"],))
                conn.commit()
                return pull_calendar(svc, conn, cal)
            raise
        items += resp.get("items", [])
        page = resp.get("nextPageToken")
        next_sync = resp.get("nextSyncToken") or next_sync
        if not page:
            break
    # Primeiro as séries e compromissos simples, depois as ocorrências alteradas
    for instance_pass in (False, True):
        for item in items:
            if bool(item.get("recurringEventId")) != instance_pass:
                continue
            try:
                (_apply_instance if instance_pass else _apply_series_or_single)(conn, cal["id"], item)
            except sqlite3.Error:
                log.exception("não aplicou o evento %s do Google", item.get("id"))
    conn.execute(
        "INSERT INTO sync_state (calendar_id, sync_token, ultima_sync) VALUES (?,?,?) "
        "ON CONFLICT(calendar_id) DO UPDATE SET sync_token=excluded.sync_token, "
        "ultima_sync=excluded.ultima_sync",
        (cal["id"], next_sync, config.iso(config.now())),
    )
    conn.commit()
