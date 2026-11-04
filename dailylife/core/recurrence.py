"""Regras de repetição de compromissos e lembretes.

Compromissos (events.repeticao):  '' | diaria | dias_uteis | semanal | mensal
Lembretes (reminders.repeticao):  '' | diaria | horas:N | dias:0,3 (0=seg ... 6=dom) | mensal
"""

import calendar as _cal
import logging
import re
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from dailylife import config

try:
    from dateutil.rrule import rruleset, rrulestr

    DATEUTIL_OK = True
except ImportError:  # pragma: no cover
    DATEUTIL_OK = False

log = logging.getLogger("dailylife.recurrence")

EVENT_RULES = {"", "diaria", "dias_uteis", "semanal", "mensal"}
WEEKDAYS_PT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
BYDAY = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

# Nossas regras simples no formato do Google
SIMPLE_TO_RRULE = {
    "diaria": "RRULE:FREQ=DAILY",
    "dias_uteis": "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
    "semanal": "RRULE:FREQ=WEEKLY",
    "mensal": "RRULE:FREQ=MONTHLY",
}


# ---------- regras do Google (RRULE) ----------

SP = "America/Sao_Paulo"


def zone(name: str) -> tzinfo:
    """Fuso pelo nome; None, vazio ou desconhecido = São Paulo."""
    if not name or name == SP:
        return config.TZ
    try:
        return ZoneInfo(name)
    except Exception:
        log.warning("fuso desconhecido %r: usando o de São Paulo", name)
        return config.TZ


def convert(dt: datetime, src: tzinfo, dst: tzinfo) -> datetime:
    """Horário sem fuso de um fuso para outro."""
    if src is dst or src == dst:
        return dt
    return dt.replace(tzinfo=src).astimezone(dst).replace(tzinfo=None)


def _ical_to_local(value: str, tzid: str | None = None, target: tzinfo | None = None) -> datetime:
    """Data do iCalendar (20261023T090000Z, 20261023T090000 ou 20261023) -> horário sem fuso no fuso alvo."""
    target = target or config.TZ
    v = value.strip()
    if len(v) == 8:
        return datetime.strptime(v, "%Y%m%d")
    if v.endswith("Z"):
        dt = datetime.strptime(v[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
        return dt.astimezone(target).replace(tzinfo=None)
    dt = datetime.strptime(v, "%Y%m%dT%H%M%S")
    if tzid:
        dt = convert(dt, zone(tzid), target)
    return dt


def _parse_rrule_text(
    text: str, target: tzinfo | None = None
) -> tuple[list[str], list[datetime], list[datetime]]:
    """Separa as linhas RRULE, EXDATE e RDATE. Datas convertidas para o fuso alvo."""
    rules, exdates, rdates = [], [], []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        head, values = line.split(":", 1)
        name, *params = head.split(";")
        name = name.upper()
        tzid = next((p.split("=", 1)[1] for p in params if p.upper().startswith("TZID=")), None)
        if name == "RRULE":
            rules.append(values)
        elif name in ("EXDATE", "RDATE"):
            target_list = exdates if name == "EXDATE" else rdates
            for v in values.split(","):
                try:
                    target_list.append(_ical_to_local(v, tzid, target))
                except ValueError:
                    pass
    return rules, exdates, rdates


def _naive_until(rule: str, target: tzinfo | None = None) -> str:
    """UNTIL em UTC vira horário sem fuso no fuso da série (o dateutil não mistura os dois)."""

    def repl(m: re.Match) -> str:
        dt = _ical_to_local(m.group(1), target=target)
        if len(m.group(1)) == 8:
            dt = dt.replace(hour=23, minute=59, second=59)
        return "UNTIL=" + dt.strftime("%Y%m%dT%H%M%S")

    return re.sub(r"UNTIL=([0-9]{8}(?:T[0-9]{6}Z?)?)", repl, rule, flags=re.I)


def rrule_occurrences(
    start: datetime,
    end: datetime,
    text: str,
    range_start: datetime,
    range_end: datetime,
    tz: str | None = None,
) -> list[tuple[datetime, datetime]]:
    """Ocorrências de uma regra do Google que tocam [range_start, range_end).

    start/end e o período estão no horário de São Paulo. A regra é aplicada no fuso da série
    (tz, ex.: Europe/London) e cada ocorrência volta para São Paulo: assim uma reunião às 9h de
    Londres continua às 9h de Londres quando o horário de verão de lá muda.
    """
    dur = end - start
    if not DATEUTIL_OK:
        log.warning("python-dateutil ausente: regra do Google mostrada só na primeira data")
        return [(start, end)] if start < range_end and end > range_start else []
    z = zone(tz)
    start_z = convert(start, config.TZ, z)
    rules, exdates, rdates = _parse_rrule_text(text, z)
    try:
        rs = rruleset()
        for r in rules:
            rs.rrule(rrulestr(_naive_until(r, z), dtstart=start_z))
        for d in rdates:
            rs.rdate(d)
        for d in exdates:
            rs.exdate(d)
        if not rules:
            rs.rdate(start_z)
        margin = timedelta(days=1)
        starts_z = rs.between(
            convert(range_start, config.TZ, z) - dur - margin,
            convert(range_end, config.TZ, z) + margin,
            inc=True,
        )
    except Exception:
        log.exception("regra de repetição inválida: %r", text)
        return [(start, end)] if start < range_end and end > range_start else []
    out = []
    for sz in starts_z:
        s = convert(sz, z, config.TZ)
        if s + dur > range_start and s < range_end:
            out.append((s, s + dur))
    return out


def google_rule_to_simple(text: str, start: datetime, tz: str | None = None) -> str | None:
    """Se a regra do Google equivale a uma das nossas, devolve o nome dela; senão None.

    Séries em outro fuso nunca viram regra simples: precisam ser aplicadas no fuso delas.
    """
    if zone(tz) is not config.TZ:
        return None
    rules, exdates, rdates = _parse_rrule_text(text)
    if len(rules) != 1 or exdates or rdates:
        return None
    params = {}
    for part in rules[0].split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k.upper()] = v.upper()
    params.pop("WKST", None)
    freq = params.pop("FREQ", None)
    if params.get("INTERVAL", "1") != "1":
        return None
    params.pop("INTERVAL", None)
    byday = params.pop("BYDAY", None)
    bymonthday = params.pop("BYMONTHDAY", None)
    if params:  # COUNT, UNTIL, BYMONTH, BYSETPOS...
        return None
    if freq == "DAILY" and not byday and not bymonthday:
        return "diaria"
    if freq == "WEEKLY" and not bymonthday:
        if not byday or byday == BYDAY[start.weekday()]:
            return "semanal"
        if set(byday.split(",")) == {"MO", "TU", "WE", "TH", "FR"} and start.weekday() < 5:
            return "dias_uteis"
    if freq == "MONTHLY" and not byday and (not bymonthday or bymonthday == str(start.day)):
        return "mensal"
    return None


def _add_months(d: datetime, months: int) -> datetime | None:
    """Mesmo dia em outro mês; None se o mês não tem esse dia (ex.: 31)."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    if d.day > _cal.monthrange(y, m)[1]:
        return None
    return d.replace(year=y, month=m)


def event_occurrences(
    start: datetime,
    end: datetime,
    rule: str,
    range_start: datetime,
    range_end: datetime,
    rrule_text: str | None = None,
    tz: str | None = None,
) -> list[tuple[datetime, datetime]]:
    """Lista (inicio, fim) das ocorrências que tocam [range_start, range_end)."""
    if rrule_text:
        return rrule_occurrences(start, end, rrule_text, range_start, range_end, tz)
    dur = end - start
    if not rule:
        if start < range_end and end > range_start:
            return [(start, end)]
        return []

    out = []
    if rule in ("diaria", "dias_uteis", "semanal"):
        step = 7 if rule == "semanal" else 1
        cur = start
        if range_start - dur > start:
            jump = ((range_start - dur) - start).days // step
            cur = start + timedelta(days=jump * step)
        while cur < range_end:
            if cur + dur > range_start and cur >= start and (rule != "dias_uteis" or cur.weekday() < 5):
                out.append((cur, cur + dur))
            cur += timedelta(days=step)
        return out

    if rule == "mensal":
        i = 0
        if range_start > start:
            i = max(0, (range_start.year - start.year) * 12 + range_start.month - start.month - 1)
        while True:
            cur = _add_months(start, i)
            i += 1
            if cur is None:
                if i > 2400:
                    break
                continue
            if cur >= range_end:
                break
            if cur + dur > range_start:
                out.append((cur, cur + dur))
        return out
    return []


def parse_reminder_rule(rule: str) -> tuple[str, Any]:
    """Devolve (tipo, valor): ('', None), ('diaria', None), ('horas', 2),
    ('dias', {0,3}), ('mensal', None)."""
    rule = (rule or "").strip()
    if not rule:
        return "", None
    if rule == "diaria":
        return "diaria", None
    if rule == "mensal":
        return "mensal", None
    if rule.startswith("horas:"):
        n = int(rule.split(":", 1)[1])
        if n < 1 or n > 23:
            raise ValueError("intervalo de horas deve ser entre 1 e 23")
        return "horas", n
    if rule.startswith("dias:"):
        dias = {int(x) for x in rule.split(":", 1)[1].split(",") if x.strip() != ""}
        if not dias or any(d < 0 or d > 6 for d in dias):
            raise ValueError("dias da semana inválidos")
        return "dias", dias
    raise ValueError(f"repetição desconhecida: {rule}")


def describe_reminder_rule(rule: str) -> str:
    kind, val = parse_reminder_rule(rule)
    if kind == "":
        return ""
    if kind == "diaria":
        return "Todo dia"
    if kind == "mensal":
        return "Todo mês"
    if kind == "horas":
        return f"A cada {val} h"
    if kind == "dias":
        if val == {0, 1, 2, 3, 4}:
            return "Dias úteis"
        return ", ".join(WEEKDAYS_PT[d] for d in sorted(val)).capitalize()
    return ""


def _at(d: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m)


def first_day_match(rule: str, base_time: datetime, after_day: date, hora_base: str) -> datetime:
    """Primeira ocorrência num dia ESTRITAMENTE depois de after_day."""
    kind, val = parse_reminder_rule(rule)
    d = after_day + timedelta(days=1)
    if kind in ("diaria", "horas"):
        return _at(d, hora_base)
    if kind == "dias":
        for _ in range(8):
            if d.weekday() in val:
                return _at(d, hora_base)
            d += timedelta(days=1)
    if kind == "mensal":
        anchor = base_time
        start_i = max(1, (after_day.year - anchor.year) * 12 + after_day.month - anchor.month)
        for i in range(start_i, start_i + 48):
            cand = _add_months(anchor, i)
            if cand is not None and cand.date() > after_day:
                return _at(cand.date(), hora_base)
    return None


def today_or_next(rule: str, base_time: datetime, today: date, hora_base: str) -> datetime:
    """Ocorrência de hoje, se a regra cair hoje; senão a próxima."""
    kind, val = parse_reminder_rule(rule)
    if kind in ("diaria", "horas"):
        return _at(today, hora_base)
    if kind == "dias" and today.weekday() in val:
        return _at(today, hora_base)
    if kind == "mensal" and base_time.day == today.day:
        return _at(today, hora_base)
    return first_day_match(rule, base_time, today, hora_base)
