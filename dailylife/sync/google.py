"""Sincronização com o Google Agenda (Fase 5).

Como funciona:
- Login OAuth uma vez (abre o navegador). O token fica em data/token.json.
- Todos os calendários da conta entram no app e podem ser escondidos.
- Baixa só o que mudou usando o syncToken do Google; se o token expira (410), refaz.
- Envia ao Google o que foi criado, editado ou excluído no app (events.pendente_sync=1).
- Conflito: vence a alteração mais recente.
- Sem internet: as mudanças ficam marcadas e vão quando a conexão voltar.

Precisa de credentials.json (Google Cloud > Credenciais > ID do cliente OAuth > App para computador)
na pasta do app. Passo a passo no README.
"""

import json
import logging
import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from dailylife import config
from dailylife.core import recurrence, settings
from dailylife.db import get_conn, rows

log = logging.getLogger("dailylife.google")

SCOPES = ["https://www.googleapis.com/auth/calendar"]

_lock = threading.Lock()
STATE = {"sincronizando": False, "erro": "", "conectando": False}

try:  # as bibliotecas do Google são opcionais até a Fase 5
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    LIBS_OK = True
except ImportError:  # pragma: no cover
    LIBS_OK = False
    HttpError = Exception


# ---------- conversões de data ----------


def _to_local(value: str) -> datetime:
    """RFC3339 do Google -> horário local de São Paulo sem fuso."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(config.TZ).replace(tzinfo=None, second=0, microsecond=0)


def _google_times(item: dict) -> tuple[str, str, bool]:
    s, e = item.get("start", {}), item.get("end", {})
    if "date" in s:
        ini = datetime.fromisoformat(s["date"])
        fim = datetime.fromisoformat(e.get("date", s["date"]))
        if fim <= ini:
            fim = ini + timedelta(days=1)
        return ini, fim, True
    return _to_local(s["dateTime"]), _to_local(e["dateTime"]), False


def _event_body(ev: dict, patch: bool = False) -> dict:
    """Corpo do evento para o Google. No patch, zera o outro tipo de data (dia inteiro <-> horário),
    senão o Google mistura os dois e recusa."""
    body = {
        "summary": ev["titulo"],
        "location": ev["local"] or "",
        "description": ev["notas"] or "",
    }
    ini = config.parse_iso(ev["inicio"])
    fim = config.parse_iso(ev["fim"])
    if ev["dia_inteiro"]:
        body["start"] = {"date": ini.date().isoformat()}
        body["end"] = {"date": fim.date().isoformat()}
        if patch:
            for k in ("start", "end"):
                body[k].update(dateTime=None, timeZone=None)
    else:
        tz = ev.get("fuso") or recurrence.SP  # série de Londres continua no fuso de Londres
        z = recurrence.zone(tz)
        body["start"] = {"dateTime": ini.replace(tzinfo=config.TZ).astimezone(z).isoformat(), "timeZone": tz}
        body["end"] = {"dateTime": fim.replace(tzinfo=config.TZ).astimezone(z).isoformat(), "timeZone": tz}
        if patch:
            for k in ("start", "end"):
                body[k]["date"] = None
    if not ev.get("serie_id"):  # ocorrência alterada não leva regra
        if ev.get("rrule"):
            body["recurrence"] = [ln for ln in ev["rrule"].splitlines() if ln.strip()]
        else:
            rule = recurrence.SIMPLE_TO_RRULE.get(ev["repeticao"])
            body["recurrence"] = [rule] if rule else []
    if ev["aviso_min"] is None:
        body["reminders"] = {"useDefault": False, "overrides": []}
    else:
        body["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": int(ev["aviso_min"])}],
        }
    return body


# ---------- estado e login ----------


def has_credentials() -> bool:
    return os.path.exists(config.CREDENTIALS_PATH)


def is_connected() -> bool:
    return os.path.exists(config.TOKEN_PATH)


def status() -> dict:
    return {
        "bibliotecas": LIBS_OK,
        "credenciais": has_credentials(),
        "conectado": is_connected(),
        "conta": settings.get("google_conta") or "",
        "ultima_sync": settings.get("google_ultima_sync") or "",
        "sincronizando": STATE["sincronizando"],
        "conectando": STATE["conectando"],
        "erro": STATE["erro"],
        "pendentes": get_conn().execute("SELECT COUNT(*) FROM events WHERE pendente_sync=1").fetchone()[0],
    }


def _load_creds() -> Any:
    if not (LIBS_OK and is_connected()):
        return None
    creds = Credentials.from_authorized_user_file(config.TOKEN_PATH, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:  # token revogado ou app em modo teste expirado
            STATE["erro"] = "O acesso ao Google expirou. Conecte de novo nas Configurações."
            log.warning("refresh falhou: %s", e)
            return None
        if is_connected():  # pode ter sido desconectado enquanto isso
            with open(config.TOKEN_PATH, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
    return creds


def _service() -> Any:
    creds = _load_creds()
    if not creds:
        return None
    try:  # tempo limite: uma conexão travada não fica pendurada para sempre
        import google_auth_httplib2
        import httplib2

        http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=30))
        return build("calendar", "v3", http=http, cache_discovery=False)
    except ImportError:
        return build("calendar", "v3", credentials=creds, cache_discovery=False)


def connect() -> None:
    """Abre o navegador para o login. Roda em thread (bloqueia até a pessoa autorizar)."""
    if not LIBS_OK:
        raise RuntimeError("Instale as bibliotecas do Google (pip install -r requirements.txt).")
    if not has_credentials():
        raise RuntimeError("Coloque o arquivo credentials.json na pasta do Daily Life.")
    STATE["conectando"] = True
    STATE["erro"] = ""
    try:
        flow = InstalledAppFlow.from_client_secrets_file(config.CREDENTIALS_PATH, SCOPES)
        creds = flow.run_local_server(
            port=0, prompt="consent", success_message="Pronto! Pode fechar esta aba e voltar ao Daily Life."
        )
        with open(config.TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
        primary = svc.calendars().get(calendarId="primary").execute()
        settings.set("google_conta", primary.get("id", ""))
    finally:
        STATE["conectando"] = False
    sync_all()


def disconnect() -> None:
    """Esquece o token e tira do app os calendários do Google (eles continuam no Google)."""
    conn = get_conn()
    if not _lock.acquire(timeout=60):  # espera a sincronização em andamento terminar
        from dailylife.core import ValidationError

        raise ValidationError("A sincronização ainda está rodando. Tente desconectar de novo em instantes.")
    try:
        if os.path.exists(config.TOKEN_PATH):
            os.remove(config.TOKEN_PATH)
        _remove_google_data(conn)
    finally:
        _lock.release()
    settings.set("google_conta", "")
    settings.set("google_ultima_sync", "")
    STATE["erro"] = ""


def _remove_google_data(conn: sqlite3.Connection) -> None:
    google_ids = [r["id"] for r in conn.execute("SELECT id FROM calendars WHERE origem='google'")]
    for cid in google_ids:
        conn.execute(
            "DELETE FROM event_alerts WHERE event_id IN (SELECT id FROM events WHERE calendar_id=?)", (cid,)
        )
        conn.execute("DELETE FROM events WHERE calendar_id=?", (cid,))
        conn.execute("DELETE FROM sync_state WHERE calendar_id=?", (cid,))
        conn.execute("DELETE FROM calendars WHERE id=?", (cid,))
    conn.commit()


# ---------- sincronização ----------


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


AVISOS = (0, 5, 10, 15, 30, 60, 120, 1440)


def _alert_minutes(item: dict) -> int | None:
    rem = item.get("reminders") or {}
    if rem.get("useDefault", True):
        return 10
    pops = [o["minutes"] for o in rem.get("overrides", []) if o.get("method") == "popup"]
    if not pops:
        return None
    return min(AVISOS, key=lambda x: abs(x - min(pops)))


def _original_start(item: dict) -> str:
    o = item.get("originalStartTime") or {}
    if "date" in o:
        return config.iso(datetime.fromisoformat(o["date"]))
    return config.iso(_to_local(o["dateTime"]))


def _local_is_newer(local: bool, item: dict) -> bool:
    """Edição feita no app e ainda não enviada, mais recente que a do Google."""
    if not local or not local["pendente_sync"]:
        return False
    updated = _to_local(item["updated"]) if item.get("updated") else config.now()
    return local["atualizado_em"] > config.iso(updated)


def _item_fields(item: dict) -> dict:
    ini, fim, allday = _google_times(item)
    updated = _to_local(item["updated"]) if item.get("updated") else config.now()
    return {
        "titulo": item.get("summary") or "(sem título)",
        "inicio": config.iso(ini),
        "fim": config.iso(fim),
        "dia_inteiro": 1 if allday else 0,
        "local": item.get("location") or "",
        "notas": item.get("description") or "",
        "aviso_min": _alert_minutes(item),
        "google_etag": item.get("etag"),
        "google_updated": config.iso(updated),
    }


def _upsert(conn: sqlite3.Connection, local_id: int, fields: dict) -> None:
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
        fields = _item_fields(item)
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
        occ = _original_start(item)
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
            fields = _item_fields(item)
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
            if _original_start(it) == ocorrencia:
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
            .patch(calendarId=ev["cal_gid"], eventId=inst, body=_event_body(ev, patch=True))
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
    updated = config.iso(_to_local(res["updated"])) if res.get("updated") else None
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
                res = svc.events().insert(calendarId=ev["cal_gid"], body=_event_body(ev)).execute()
                if not _mark_pushed(conn, ev, res["id"], res):
                    # foi excluído no app enquanto subia: apaga a cópia que acabou de chegar ao Google
                    svc.events().delete(calendarId=ev["cal_gid"], eventId=res["id"]).execute()
            else:
                res = (
                    svc.events()
                    .patch(
                        calendarId=ev["cal_gid"],
                        eventId=ev["google_event_id"],
                        body=_event_body(ev, patch=True),
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


SYNC_VERSION = 2  # 2 = séries do Google guardadas como regra (antes: uma linha por repetição)


def _migrate(conn: sqlite3.Connection) -> None:
    """Bancos da versão anterior: apaga as cópias do Google e baixa tudo de novo no formato novo."""
    if settings.get("google_sync_v", conn) == SYNC_VERSION:
        return
    conn.execute(
        "DELETE FROM events WHERE pendente_sync=0 AND calendar_id IN "
        "(SELECT id FROM calendars WHERE origem='google') "
        "AND id NOT IN (SELECT serie_id FROM events WHERE serie_id IS NOT NULL AND pendente_sync=1)"
    )
    conn.execute("DELETE FROM sync_state")
    conn.commit()
    settings.set("google_sync_v", SYNC_VERSION, conn)


def sync_all() -> bool | None:
    """Envia pendências, atualiza calendários e baixa mudanças. Seguro chamar de qualquer thread."""
    if not (LIBS_OK and is_connected()):
        return False
    if not recurrence.DATEUTIL_OK:
        STATE["erro"] = "Falta a biblioteca python-dateutil. Rode o instalar.bat de novo."
        return False
    if not _lock.acquire(blocking=False):
        return False
    STATE["sincronizando"] = True
    conn = get_conn()
    try:
        svc = _service()
        if svc is None:
            return False
        STATE["erro"] = ""
        _migrate(conn)
        push_pending(svc, conn)
        sync_calendars(svc, conn)
        for cal in rows(conn.execute("SELECT * FROM calendars WHERE origem='google' AND visivel=1")):
            pull_calendar(svc, conn, cal)
        settings.set("google_ultima_sync", config.iso(config.now()))
        return True
    except (OSError, ConnectionError, TimeoutError) as e:
        log.warning("sem conexão: %s", e)
        STATE["erro"] = "Sem internet. As mudanças serão enviadas quando a conexão voltar."
        return False
    except HttpError as e:
        log.exception("erro do Google")
        status = getattr(getattr(e, "resp", None), "status", "?")
        STATE["erro"] = f"O Google respondeu com erro ({status})."
        return False
    except Exception as e:  # nunca derruba o app por causa da sincronização
        if type(e).__name__ in ("ServerNotFoundError", "TransportError", "RefreshError"):
            STATE["erro"] = "Sem internet. As mudanças serão enviadas quando a conexão voltar."
        else:
            log.exception("falha na sincronização")
            STATE["erro"] = f"Falha na sincronização: {e}"
        return False
    finally:
        STATE["sincronizando"] = False
        _lock.release()
