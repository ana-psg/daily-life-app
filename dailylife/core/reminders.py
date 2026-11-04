"""Lembretes: data, hora, repetição, resolver, adiar.

Regra: um lembrete recorrente marcado conta como
concluído naquele dia e volta na próxima ocorrência (normalmente no dia seguinte).
"""

import sqlite3
from datetime import datetime, timedelta

from dailylife import config
from dailylife.core import NotFound, ValidationError, as_int, clean_text, recurrence, require_text
from dailylife.db import get_conn, row, rows

CORES = ("amarelo", "rosa", "azul", "verde", "lilas")
FILTROS = ("todos", "hoje", "recorrentes", "resolvidos")
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def when_text(dt: datetime, now: datetime | None = None) -> str:
    now = now or config.now()
    hora = dt.strftime("%H:%M")
    delta = (dt.date() - now.date()).days
    if delta == 0:
        return f"Hoje · {hora}"
    if delta == 1:
        return f"Amanhã · {hora}"
    if delta == -1:
        return f"Ontem · {hora}"
    return f"{DIAS[dt.weekday()]}, {dt.day} {MESES[dt.month - 1]} · {hora}"


def _serialize(r: dict, now: datetime) -> dict:
    today = now.date().isoformat()
    q = config.parse_iso(r["quando"])
    recorrente = bool(r["repeticao"])
    if recorrente:
        feito_hoje = r["ultimo_resolvido"] == today
        concluido = feito_hoje
    else:
        concluido = bool(r["resolvido"])
        feito_hoje = concluido and (r["resolvido_em"] or "")[:10] == today
    r["resolvido"] = bool(r["resolvido"])
    r["recorrente"] = recorrente
    r["concluido"] = concluido
    r["feito_hoje"] = feito_hoje
    r["repeticao_texto"] = recurrence.describe_reminder_rule(r["repeticao"])
    r["when_text"] = when_text(q, now)
    r["hora"] = q.strftime("%H:%M")
    delta = (q.date() - now.date()).days
    r["volta"] = (
        "hoje"
        if delta <= 0
        else "amanhã"
        if delta == 1
        else DIAS[q.weekday()].lower()
        if delta < 7
        else q.strftime("%d/%m")
    )
    r["atrasado"] = (not concluido) and q < now and not (recorrente and feito_hoje)
    r["de_hoje"] = feito_hoje or (not r["resolvido"] and q.date() <= now.date() and not feito_hoje)
    if (recorrente and feito_hoje) or concluido:
        r["estado"] = "feito"
    elif r["atrasado"]:
        r["estado"] = "atrasado"
    else:
        r["estado"] = "pendente"
    return r


def _anchor(r: dict) -> datetime:
    """Data de referência da repetição mensal (não muda quando o lembrete é adiado)."""
    hora = r.get("hora_base") or r["quando"][11:16]
    if r.get("data_base"):
        return config.parse_iso(f"{r['data_base']}T{hora}")
    return config.parse_iso(r["quando"])


def rollover(conn: sqlite3.Connection | None = None, now: datetime | None = None) -> int:
    """Lembretes diários e "a cada N horas" esquecidos em dias passados voltam para hoje.

    Os semanais e mensais ficam atrasados até serem marcados, para não sumirem sem aviso.
    """
    conn = conn or get_conn()
    now = now or config.now()
    today = now.date()
    changed = 0
    for r in rows(
        conn.execute(
            "SELECT * FROM reminders WHERE (repeticao='diaria' OR repeticao LIKE 'horas:%') "
            "AND resolvido=0 AND substr(quando,1,10)<?",
            (today.isoformat(),),
        )
    ):
        base = config.parse_iso(r["quando"])
        hora_base = r["hora_base"] or base.strftime("%H:%M")
        nxt = recurrence.today_or_next(r["repeticao"], base, today, hora_base)
        if nxt:
            conn.execute(
                "UPDATE reminders SET quando=?, atualizado_em=? WHERE id=?",
                (config.iso(nxt), config.iso(now), r["id"]),
            )
            changed += 1
    if changed:
        conn.commit()
    return changed


def get(rem_id: int, conn: sqlite3.Connection | None = None, now: datetime | None = None) -> dict:
    conn = conn or get_conn()
    r = row(conn.execute("SELECT * FROM reminders WHERE id=?", (rem_id,)))
    if not r:
        raise NotFound("Lembrete não encontrado.")
    return _serialize(r, now or config.now())


def list_filtered(
    filtro: str = "todos", conn: sqlite3.Connection | None = None, now: datetime | None = None
) -> list[dict]:
    conn = conn or get_conn()
    now = now or config.now()
    if filtro not in FILTROS:
        raise ValidationError("Filtro inválido.")
    rollover(conn, now)
    items = [_serialize(r, now) for r in rows(conn.execute("SELECT * FROM reminders"))]
    if filtro == "hoje":
        items = [r for r in items if r["de_hoje"]]
    elif filtro == "recorrentes":
        items = [r for r in items if r["recorrente"]]
    elif filtro == "resolvidos":
        items = [r for r in items if r["concluido"] or r["feito_hoje"]]
    else:
        # Todos: esconde não recorrentes resolvidos há mais de 1 dia
        cutoff = (now - timedelta(days=1)).date().isoformat()
        items = [r for r in items if not (r["resolvido"] and (r["resolvido_em"] or "")[:10] < cutoff)]
    items.sort(key=lambda r: (r["estado"] == "feito", r["quando"]))
    return items


def _validate(data: dict, partial: bool = False) -> dict:
    out = {}
    if not partial or "titulo" in data:
        out["titulo"] = require_text(data, "titulo", "O título do lembrete", 200)
    if "descricao" in data:
        out["descricao"] = clean_text(data.get("descricao"), "Descrição", 1000)
    if not partial or "quando" in data:
        try:
            q = config.parse_iso(data.get("quando") or "")
        except ValueError:
            raise ValidationError("Informe data e hora do lembrete.") from None
        out["quando"] = config.iso(q)
        out["hora_base"] = q.strftime("%H:%M")
    if "repeticao" in data:
        rule = clean_text(data.get("repeticao") or "", "Repetição")
        try:
            recurrence.parse_reminder_rule(rule)
        except ValueError as e:
            raise ValidationError(str(e)) from None
        out["repeticao"] = rule
    if "cor" in data:
        if data["cor"] not in CORES:
            raise ValidationError("Cor inválida.")
        out["cor"] = data["cor"]
    return out


def _align(fields: dict) -> dict:
    """Se a repetição é por dias da semana e a data não cai nesses dias, ajusta."""
    rule = fields.get("repeticao")
    if not rule or "quando" not in fields:
        return fields
    q = config.parse_iso(fields["quando"])
    kind, val = recurrence.parse_reminder_rule(rule)
    if kind == "dias" and q.weekday() not in val:
        nxt = recurrence.today_or_next(rule, q, q.date(), fields["hora_base"])
        fields["quando"] = config.iso(nxt)
    return fields


def create(data: dict, conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or get_conn()
    fields = _validate(data)
    fields.setdefault("repeticao", "")
    fields.setdefault("descricao", "")
    fields.setdefault("cor", "amarelo")
    fields = _align(fields)
    stamp = config.iso(config.now())
    cur = conn.execute(
        "INSERT INTO reminders (titulo, descricao, quando, repeticao, hora_base, data_base, cor, "
        "criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            fields["titulo"],
            fields["descricao"],
            fields["quando"],
            fields["repeticao"],
            fields["hora_base"],
            fields["quando"][:10],
            fields["cor"],
            stamp,
            stamp,
        ),
    )
    conn.commit()
    return get(cur.lastrowid, conn)


def update(rem_id: int, data: dict, conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or get_conn()
    current = get(rem_id, conn)
    fields = _validate(data, partial=True)
    # A janela de edição manda sempre data e repetição: só conta como mudança se mudou mesmo
    if fields.get("quando") == current["quando"]:
        fields.pop("quando")
        fields.pop("hora_base", None)
    if fields.get("repeticao") == current["repeticao"]:
        fields.pop("repeticao")
    if "repeticao" in fields and "quando" not in fields:
        fields["quando"] = current["quando"]
        fields["hora_base"] = current["hora_base"] or current["hora"]
    fields = _align(fields)
    if "quando" in fields or "repeticao" in fields:
        # Nova data ou nova regra: o lembrete volta a valer e a avisar
        fields.update(
            ultimo_aviso=None,
            resolvido=0,
            resolvido_em=None,
            data_base=fields.get("quando", current["quando"])[:10],
        )
        if fields.get("quando", current["quando"])[:10] <= config.now().date().isoformat():
            fields["ultimo_resolvido"] = None  # remarcado para hoje: ainda não foi feito
    if not fields:
        return current
    fields["atualizado_em"] = config.iso(config.now())
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE reminders SET {sets} WHERE id=?", (*fields.values(), rem_id))
    conn.commit()
    return get(rem_id, conn)


def resolve(rem_id: int, conn: sqlite3.Connection | None = None, now: datetime | None = None) -> dict:
    conn = conn or get_conn()
    now = now or config.now()
    r = get(rem_id, conn, now)
    stamp = config.iso(now)
    if r["recorrente"]:
        q = config.parse_iso(r["quando"])
        base_day = max(now.date(), q.date())
        hora_base = r["hora_base"] or r["hora"]
        nxt = recurrence.first_day_match(r["repeticao"], _anchor(r), base_day, hora_base)
        conn.execute(
            "UPDATE reminders SET quando_anterior=quando, quando=?, ultimo_resolvido=?, "
            "ultimo_aviso=NULL, atualizado_em=? WHERE id=?",
            (config.iso(nxt), now.date().isoformat(), stamp, rem_id),
        )
    else:
        conn.execute(
            "UPDATE reminders SET resolvido=1, resolvido_em=?, atualizado_em=? WHERE id=?",
            (stamp, stamp, rem_id),
        )
    conn.commit()
    return get(rem_id, conn, now)


def undo(rem_id: int, conn: sqlite3.Connection | None = None, now: datetime | None = None) -> dict:
    conn = conn or get_conn()
    now = now or config.now()
    r = get(rem_id, conn, now)
    stamp = config.iso(now)
    if r["recorrente"]:
        if r["quando_anterior"]:
            conn.execute(
                "UPDATE reminders SET quando=quando_anterior, ultimo_aviso=quando_anterior, "
                "quando_anterior=NULL, ultimo_resolvido=NULL, atualizado_em=? WHERE id=?",
                (stamp, rem_id),
            )
        else:
            conn.execute(
                "UPDATE reminders SET ultimo_resolvido=NULL, atualizado_em=? WHERE id=?", (stamp, rem_id)
            )
    else:
        conn.execute(
            "UPDATE reminders SET resolvido=0, resolvido_em=NULL, atualizado_em=? WHERE id=?", (stamp, rem_id)
        )
    conn.commit()
    return get(rem_id, conn, now)


def snooze(
    rem_id: int, minutos: int = 60, conn: sqlite3.Connection | None = None, now: datetime | None = None
) -> dict:
    conn = conn or get_conn()
    now = now or config.now()
    minutos = as_int(minutos, "Adiamento")
    if not 1 <= minutos <= 24 * 60:
        raise ValidationError("Adiamento inválido.")
    get(rem_id, conn, now)
    conn.execute(
        "UPDATE reminders SET quando=?, resolvido=0, resolvido_em=NULL, ultimo_resolvido=NULL, "
        "ultimo_aviso=NULL, atualizado_em=? WHERE id=?",
        (config.iso(now + timedelta(minutes=minutos)), config.iso(now), rem_id),
    )
    conn.commit()
    return get(rem_id, conn, now)


def delete(rem_id: int, conn: sqlite3.Connection | None = None) -> None:
    conn = conn or get_conn()
    get(rem_id, conn)
    conn.execute("DELETE FROM reminders WHERE id=?", (rem_id,))
    conn.commit()


# ---------- usados pelo agendador ----------


def due(conn: sqlite3.Connection | None = None, now: datetime | None = None) -> list[dict]:
    """Lembretes que venceram e ainda não foram avisados."""
    conn = conn or get_conn()
    now = now or config.now()
    rollover(conn, now)
    return rows(
        conn.execute(
            "SELECT * FROM reminders WHERE resolvido=0 AND quando<=? "
            "AND (ultimo_aviso IS NULL OR ultimo_aviso<quando) ORDER BY quando",
            (config.iso(now),),
        )
    )


def mark_notified(r: dict, conn: sqlite3.Connection | None = None, now: datetime | None = None) -> None:
    """Marca como avisado. 'A cada N h' já agenda o próximo aviso do dia."""
    conn = conn or get_conn()
    now = now or config.now()
    fields = {"ultimo_aviso": r["quando"]}
    kind, val = recurrence.parse_reminder_rule(r["repeticao"])
    if kind == "horas":
        q = config.parse_iso(r["quando"])
        nxt = q + timedelta(hours=val)
        while nxt <= now:
            nxt += timedelta(hours=val)
        if nxt.date() != q.date():
            nxt = recurrence.first_day_match(
                r["repeticao"], q, q.date(), r["hora_base"] or q.strftime("%H:%M")
            )
        fields["quando"] = config.iso(nxt)
    sets = ", ".join(f"{k}=?" for k in fields)
    # Só se ninguém mexeu no lembrete desde que ele foi lido (ex.: marcado no mesmo instante)
    conn.execute(
        f"UPDATE reminders SET {sets} WHERE id=? AND quando=?", (*fields.values(), r["id"], r["quando"])
    )
    conn.commit()
