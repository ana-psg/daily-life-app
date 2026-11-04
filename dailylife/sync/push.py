"""Envia ao Google o que foi criado, editado ou excluído no app (events.pendente_sync=1)."""

import json
import logging
import sqlite3
from datetime import timedelta
from typing import Any

from dailylife import config
from dailylife.db import rows
from dailylife.sync.common import STATE, HttpError
from dailylife.sync.convert import event_body, original_start, to_local

log = logging.getLogger("dailylife.google")


def _find_instance(svc: Any, cal_gid: str, master_gid: str, ocorrencia: str, dia_inteiro: bool) -> str | None:
    """Id no Google de uma ocorrência de série, pela data original."""
    occ = config.parse_iso(ocorrencia)
    if dia_inteiro:
        t0, t1 = occ, occ + timedelta(days=1)
    else:
        t0, t1 = occ - timedelta(minutes=1), occ + timedelta(minutes=1)
    resp = (
        svc.events()
        .instances(
            calendarId=cal_gid,
            eventId=master_gid,
            showDeleted=True,
            timeMin=t0.replace(tzinfo=config.TZ).isoformat(),
            timeMax=t1.replace(tzinfo=config.TZ).isoformat(),
        )
        .execute()
    )
    found = resp.get("items", [])
    for it in found:
        try:
            if original_start(it) == ocorrencia:
                return it["id"]
        except (KeyError, ValueError):
            continue
    return found[0]["id"] if found else None


def _push_override(svc: Any, conn: sqlite3.Connection, ev: dict) -> None:
    master = conn.execute("SELECT google_event_id FROM events WHERE id=?", (ev["serie_id"],)).fetchone()
    if not master or not master["google_event_id"]:
        return  # a série ainda não chegou ao Google; tenta na próxima
    inst = ev["google_event_id"] or _find_instance(
        svc, ev["cal_gid"], master["google_event_id"], ev["ocorrencia"], ev["dia_inteiro"]
    )
    if not inst:
        log.warning("ocorrência %s não encontrada no Google", ev["ocorrencia"])
        conn.execute("UPDATE events SET pendente_sync=0 WHERE id=?", (ev["id"],))
        STATE["erro"] = "Uma alteração de um compromisso que se repete ficou só no app (não achei no Google)."
        return
    if ev["cancelado"]:
        try:
            svc.events().delete(calendarId=ev["cal_gid"], eventId=inst).execute()
        except HttpError as e:
            if e.resp.status not in (404, 410):
                raise
        conn.execute("UPDATE events SET google_event_id=?, pendente_sync=0 WHERE id=?", (inst, ev["id"]))
    else:
        res = (
            svc.events()
            .patch(calendarId=ev["cal_gid"], eventId=inst, body=event_body(ev, patch=True))
            .execute()
        )
        _mark_pushed(conn, ev, inst, res)


PERMISSION_REASONS = {
    "forbidden",
    "requiredaccesslevel",
    "insufficientpermissions",
    "forbiddenfornonorganizer",
    "access_token_scope_insufficient",
}


def _error_reasons(e: Exception) -> set:
    """Motivos do erro do Google, em minúsculas (vêm de error_details e do corpo da resposta)."""
    out = set()
    details = getattr(e, "error_details", None) or []
    if isinstance(details, list):
        for d in details:
            if isinstance(d, dict) and d.get("reason"):
                out.add(str(d["reason"]).lower())
    try:
        body = json.loads(getattr(e, "content", b"") or b"{}")
        err = body.get("error", {}) if isinstance(body, dict) else {}
        for d in err.get("errors", []) or []:
            if d.get("reason"):
                out.add(str(d["reason"]).lower())
        if err.get("status"):
            out.add(str(err["status"]).lower())
    except Exception:
        pass
    return out


def _is_rate_limit(status: int | None, reasons: set[str]) -> bool:
    return status == 429 or any("ratelimit" in r or "rate_limit" in r or "quota" in r for r in reasons)


def _mark_pushed(conn: sqlite3.Connection, ev: dict, gid: str, res: dict) -> bool:
    """Marca como enviado, mas só se ninguém editou o compromisso durante o envio (mesma rev)."""
    updated = config.iso(to_local(res["updated"])) if res.get("updated") else None
    # uma cópia antiga com o mesmo id do Google (versão anterior do app) sai do caminho
    conn.execute(
        "DELETE FROM events WHERE calendar_id=? AND google_event_id=? AND id!=?",
        (ev["calendar_id"], gid, ev["id"]),
    )
    cur = conn.execute(
        "UPDATE events SET google_event_id=?, google_etag=?, google_updated=?, pendente_sync=0 "
        "WHERE id=? AND rev=?",
        (gid, res.get("etag"), updated, ev["id"], ev["rev"]),
    )
    if cur.rowcount == 0:  # editado no meio: guarda o id e deixa pendente para o próximo envio
        conn.execute(
            "UPDATE events SET google_event_id=?, google_etag=? WHERE id=?", (gid, res.get("etag"), ev["id"])
        )
        return conn.execute("SELECT 1 FROM events WHERE id=?", (ev["id"],)).fetchone() is not None
    return True


def push_pending(svc: Any, conn: sqlite3.Connection) -> None:
    # Séries e compromissos simples primeiro: as ocorrências alteradas dependem deles
    pend = rows(
        conn.execute(
            "SELECT e.*, c.google_id AS cal_gid FROM events e JOIN calendars c ON c.id=e.calendar_id "
            "WHERE e.pendente_sync=1 AND c.origem='google' ORDER BY e.serie_id IS NOT NULL, e.id"
        )
    )
    failures = 0
    for ev in pend:
        try:
            if ev["serie_id"]:
                _push_override(svc, conn, ev)
            elif ev["excluido"]:
                if ev["google_event_id"]:
                    try:
                        svc.events().delete(calendarId=ev["cal_gid"], eventId=ev["google_event_id"]).execute()
                    except HttpError as e:
                        if e.resp.status not in (404, 410):
                            raise
                conn.execute("DELETE FROM events WHERE serie_id=?", (ev["id"],))
                conn.execute("DELETE FROM events WHERE id=?", (ev["id"],))
            elif not ev["google_event_id"]:
                res = svc.events().insert(calendarId=ev["cal_gid"], body=event_body(ev)).execute()
                if not _mark_pushed(conn, ev, res["id"], res):
                    # foi excluído no app enquanto subia: apaga a cópia que acabou de chegar ao Google
                    svc.events().delete(calendarId=ev["cal_gid"], eventId=res["id"]).execute()
            else:
                res = (
                    svc.events()
                    .patch(
                        calendarId=ev["cal_gid"],
                        eventId=ev["google_event_id"],
                        body=event_body(ev, patch=True),
                    )
                    .execute()
                )
                _mark_pushed(conn, ev, ev["google_event_id"], res)
            conn.commit()
        except HttpError as e:
            status = getattr(getattr(e, "resp", None), "status", None)
            reasons = _error_reasons(e)
            if _is_rate_limit(status, reasons):
                STATE["erro"] = "O Google pediu uma pausa. As mudanças vão na próxima sincronização."
                return  # para por agora; tudo continua pendente
            if status == 403 and reasons & PERMISSION_REASONS:
                conn.execute("UPDATE calendars SET somente_leitura=1 WHERE id=?", (ev["calendar_id"],))
                conn.execute("UPDATE events SET pendente_sync=0 WHERE id=?", (ev["id"],))
                conn.commit()
                STATE["erro"] = "Um calendário do Google é somente leitura; a alteração ficou só no app."
            elif status == 404 and not ev["excluido"] and not ev["serie_id"]:
                conn.execute("UPDATE events SET google_event_id=NULL WHERE id=?", (ev["id"],))
                conn.commit()
            else:
                # Um compromisso com problema não trava os outros: fica pendente e segue
                failures += 1
                log.warning("não enviou o compromisso %s ao Google: %s", ev["id"], e)
                STATE["erro"] = (
                    f"{failures} compromisso(s) não foram enviados ao Google; tento de novo depois."
                )
