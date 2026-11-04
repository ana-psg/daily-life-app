"""Conversões entre o formato do Google Agenda e o do app."""

from datetime import UTC, datetime, timedelta

from dailylife import config
from dailylife.core import events, recurrence

AVISOS = tuple(a for a in events.AVISOS if a is not None)


def to_local(value: str) -> datetime:
    """RFC3339 do Google -> horário local de São Paulo sem fuso."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(config.TZ).replace(tzinfo=None, second=0, microsecond=0)


def _google_times(item: dict) -> tuple[datetime, datetime, bool]:
    s, e = item.get("start", {}), item.get("end", {})
    if "date" in s:
        ini = datetime.fromisoformat(s["date"])
        fim = datetime.fromisoformat(e.get("date", s["date"]))
        if fim <= ini:
            fim = ini + timedelta(days=1)
        return ini, fim, True
    return to_local(s["dateTime"]), to_local(e["dateTime"]), False


def event_body(ev: dict, patch: bool = False) -> dict:
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


def _alert_minutes(item: dict) -> int | None:
    rem = item.get("reminders") or {}
    if rem.get("useDefault", True):
        return 10
    pops = [o["minutes"] for o in rem.get("overrides", []) if o.get("method") == "popup"]
    if not pops:
        return None
    return min(AVISOS, key=lambda x: abs(x - min(pops)))


def original_start(item: dict) -> str:
    o = item.get("originalStartTime") or {}
    if "date" in o:
        return config.iso(datetime.fromisoformat(o["date"]))
    return config.iso(to_local(o["dateTime"]))


def item_fields(item: dict) -> dict:
    ini, fim, allday = _google_times(item)
    updated = to_local(item["updated"]) if item.get("updated") else config.now()
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
