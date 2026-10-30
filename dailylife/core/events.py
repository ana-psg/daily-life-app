"""Compromissos: repetição, ocorrências alteradas ("só este"), conflitos e sincronização.

Modelo:
- Compromisso simples: uma linha com inicio/fim.
- Série: uma linha com repeticao (nossas regras) ou rrule (regra do Google).
- Ocorrência alterada: linha com serie_id + ocorrencia (início original). Substitui aquela
  ocorrência da série. Com cancelado=1, a ocorrência foi excluída.
"""

import sqlite3
from datetime import datetime, timedelta

from dailylife import config
from dailylife.core import NotFound, ValidationError, as_bool, recurrence, require_text
from dailylife.core import calendars as cal_service
from dailylife.db import get_conn, row, rows

AVISOS = (None, 0, 5, 10, 15, 30, 60, 120, 1440)
ESCOPOS = ("todos", "este")

_SELECT = (
    "SELECT e.*, c.nome AS calendario, c.cor, c.origem, c.visivel, "
    "c.somente_leitura AS cal_somente_leitura "
    "FROM events e JOIN calendars c ON c.id=e.calendar_id WHERE e.excluido=0 "
)


def _is_series(e: dict) -> bool:
    return not e.get("serie_id") and bool(e.get("repeticao") or e.get("rrule"))


def _serialize(e: dict, occ_start: datetime | None = None, occ_end: datetime | None = None) -> dict:
    s = config.parse_iso(e["inicio"])
    f = config.parse_iso(e["fim"])
    occ_start = occ_start or s
    occ_end = occ_end or f
    out = dict(e)
    out["dia_inteiro"] = bool(e["dia_inteiro"])
    out["serie_inicio"] = e["inicio"]
    out["serie_fim"] = e["fim"]
    out["inicio"] = config.iso(occ_start)
    out["fim"] = config.iso(occ_end)
    out["google"] = e["origem"] == "google"
    out["somente_leitura"] = bool(e.get("cal_somente_leitura"))
    out["recorrente"] = _is_series(e)
    out["alterada"] = bool(e.get("serie_id"))
    if out["recorrente"]:
        out["ocorrencia"] = config.iso(occ_start)
    for k in ("visivel", "cal_somente_leitura", "cancelado", "excluido"):
        out.pop(k, None)
    return out


def get(event_id: int, conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or get_conn()
    e = row(conn.execute(_SELECT + "AND e.id=? AND e.cancelado=0", (event_id,)))
    if not e:
        raise NotFound("Compromisso não encontrado.")
    return _serialize(e)


def list_range(
    start: datetime,
    end: datetime,
    conn: sqlite3.Connection | None = None,
    calendar_ids: list[int] | None = None,
    include_hidden: bool = False,
) -> list[dict]:
    """Ocorrências (já expandidas e com as alterações aplicadas) entre start e end."""
    conn = conn or get_conn()
    filt, params = "", []
    if not include_hidden:
        filt += "AND c.visivel=1 "
    if calendar_ids:
        filt += f"AND e.calendar_id IN ({','.join('?' * len(calendar_ids))}) "
        params += list(calendar_ids)
    s_iso, e_iso = config.iso(start), config.iso(end)

    singles = rows(
        conn.execute(
            _SELECT + filt + "AND e.serie_id IS NULL AND e.repeticao='' AND e.rrule IS NULL "
            "AND e.cancelado=0 AND e.inicio<? AND e.fim>?",
            [*params, e_iso, s_iso],
        )
    )
    series = rows(
        conn.execute(
            _SELECT + filt + "AND e.serie_id IS NULL AND (e.repeticao!='' OR e.rrule IS NOT NULL) "
            "AND e.inicio<?",
            [*params, e_iso],
        )
    )
    series_ids = [s["id"] for s in series]
    q = _SELECT + filt + "AND e.serie_id IS NOT NULL AND ((e.inicio<? AND e.fim>?)"
    p = [*params, e_iso, s_iso]
    if series_ids:
        q += f" OR e.serie_id IN ({','.join('?' * len(series_ids))})"
        p += series_ids
    overrides = rows(conn.execute(q + ")", p))

    replaced = {(o["serie_id"], o["ocorrencia"]) for o in overrides}
    out = [_serialize(e) for e in singles]
    out += [
        _serialize(o) for o in overrides if not o["cancelado"] and o["inicio"] < e_iso and o["fim"] > s_iso
    ]
    for e in series:
        s = config.parse_iso(e["inicio"])
        f = config.parse_iso(e["fim"])
        for occ_s, occ_f in recurrence.event_occurrences(
            s, f, e["repeticao"], start, end, e["rrule"], e["fuso"]
        ):
            if (e["id"], config.iso(occ_s)) not in replaced:
                out.append(_serialize(e, occ_s, occ_f))
    out.sort(key=lambda x: (x["inicio"], not x["dia_inteiro"], x["titulo"]))
    return out


def _times(data: dict, cur: datetime, dia_inteiro: bool) -> tuple[str, str]:
    try:
        inicio = config.parse_iso(data.get("inicio") or cur.get("serie_inicio") or "")
        fim = config.parse_iso(data.get("fim") or cur.get("serie_fim") or "")
    except ValueError:
        raise ValidationError("Informe data e horário de início e fim.") from None
    if dia_inteiro:
        inicio = inicio.replace(hour=0, minute=0)
        fim = fim.replace(hour=0, minute=0)
        if fim <= inicio:
            fim = inicio + timedelta(days=1)
    if fim <= inicio:
        raise ValidationError("O fim precisa ser depois do início.")
    return config.iso(inicio), config.iso(fim)


def _validate(data: dict, conn: sqlite3.Connection, current: dict | None = None) -> dict:
    cur = current or {}
    out = {"titulo": require_text({**cur, **data}, "titulo", "O título", 200)}
    cal_id = int(data.get("calendar_id") or cur.get("calendar_id") or 0)
    if not cal_id:
        raise ValidationError("Escolha um calendário.")
    cal = cal_service.get(cal_id, conn)
    if cal["somente_leitura"]:
        raise ValidationError("Esse calendário do Google é somente leitura.")
    out["calendar_id"] = cal_id
    dia_inteiro = as_bool(data.get("dia_inteiro", cur.get("dia_inteiro", False)))
    out["dia_inteiro"] = 1 if dia_inteiro else 0
    out["inicio"], out["fim"] = _times(data, cur, dia_inteiro)
    for k in ("local", "notas"):
        out[k] = (data.get(k, cur.get(k)) or "").strip()[:2000]
    rep = data.get("repeticao", cur.get("repeticao", "")) or ""
    if rep not in recurrence.EVENT_RULES:
        raise ValidationError("Repetição inválida.")
    out["repeticao"] = rep
    # Escolher uma repetição nossa substitui a regra personalizada do Google
    out["rrule"] = None if "repeticao" in data else cur.get("rrule")
    out["fuso"] = None if "repeticao" in data else cur.get("fuso")
    aviso = data.get("aviso_min", cur.get("aviso_min", 15))
    aviso = None if aviso in (None, "", "null", "none") else int(aviso)
    if aviso not in AVISOS:
        raise ValidationError("Aviso inválido.")
    out["aviso_min"] = aviso
    out["_origem"] = cal["origem"]
    return out


def conflicts(
    inicio: str,
    fim: str,
    conn: sqlite3.Connection | None = None,
    ignore_id: int | None = None,
    ignore_ocorrencia: str | None = None,
) -> list[dict]:
    conn = conn or get_conn()
    s = config.parse_iso(inicio)
    f = config.parse_iso(fim)
    out = []
    for e in list_range(s, f, conn):
        if e["dia_inteiro"]:
            continue
        if e["id"] == ignore_id and (
            ignore_ocorrencia is None or e.get("ocorrencia") in (None, ignore_ocorrencia)
        ):
            continue
        out.append(e)
    return out


def _with_conflicts(ev: dict, conn: sqlite3.Connection) -> dict:
    ev["conflitos"] = (
        []
        if ev["dia_inteiro"]
        else [
            {"titulo": c["titulo"], "inicio": c["inicio"]}
            for c in conflicts(
                ev["inicio"], ev["fim"], conn, ignore_id=ev["id"], ignore_ocorrencia=ev.get("ocorrencia")
            )
        ]
    )
    return ev


_COLS = (
    "calendar_id",
    "titulo",
    "inicio",
    "fim",
    "dia_inteiro",
    "local",
    "notas",
    "repeticao",
    "rrule",
    "fuso",
    "aviso_min",
)


def create(data: dict, conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or get_conn()
    f = _validate(data, conn)
    origem = f.pop("_origem")
    stamp = config.iso(config.now())
    cur = conn.execute(
        f"INSERT INTO events ({','.join(_COLS)}, pendente_sync, criado_em, atualizado_em) "
        f"VALUES ({','.join('?' * len(_COLS))},?,?,?)",
        (*(f[c] for c in _COLS), 1 if origem == "google" else 0, stamp, stamp),
    )
    conn.commit()
    return _with_conflicts(get(cur.lastrowid, conn), conn)


def _occurrence_times(series: dict, ocorrencia: str) -> tuple[datetime, datetime]:
    """Início e fim de uma ocorrência da série, validando que ela existe."""
    try:
        occ = config.parse_iso(ocorrencia)
    except ValueError:
        raise ValidationError("Ocorrência inválida.") from None
    s = config.parse_iso(series["serie_inicio"])
    f = config.parse_iso(series["serie_fim"])
    found = recurrence.event_occurrences(
        s, f, series["repeticao"], occ, occ + timedelta(minutes=1), series.get("rrule"), series.get("fuso")
    )
    if not any(o[0] == occ for o in found):
        raise ValidationError("Essa data não faz parte da série.")
    return occ, occ + (f - s)


def _upsert_override(
    conn: sqlite3.Connection, series: dict, ocorrencia: str, fields: dict, cancelado: bool = False
) -> int:
    stamp = config.iso(config.now())
    pend = 1 if series["origem"] == "google" else 0
    existing = conn.execute(
        "SELECT id FROM events WHERE serie_id=? AND ocorrencia=?", (series["id"], ocorrencia)
    ).fetchone()
    values = {
        **fields,
        "calendar_id": series["calendar_id"],
        "repeticao": "",
        "rrule": None,
        "fuso": None,
        "cancelado": 1 if cancelado else 0,
        "pendente_sync": pend,
        "atualizado_em": stamp,
    }
    if existing:
        sets = ", ".join(f"{k}=?" for k in values)
        conn.execute(f"UPDATE events SET {sets}, rev=rev+1 WHERE id=?", (*values.values(), existing["id"]))
        oid = existing["id"]
    else:
        values.update(serie_id=series["id"], ocorrencia=ocorrencia, criado_em=stamp)
        cur = conn.execute(
            f"INSERT INTO events ({','.join(values)}) VALUES ({','.join('?' * len(values))})",
            tuple(values.values()),
        )
        oid = cur.lastrowid
    conn.execute(
        "DELETE FROM event_alerts WHERE (event_id=? AND ocorrencia=?) OR event_id=?",
        (series["id"], ocorrencia, oid),
    )
    conn.commit()
    return oid


def update(
    event_id: int,
    data: dict,
    conn: sqlite3.Connection | None = None,
    escopo: str = "todos",
    ocorrencia: str | None = None,
) -> dict:
    conn = conn or get_conn()
    if escopo not in ESCOPOS:
        raise ValidationError("Escolha alterar só este ou todos.")
    current = get(event_id, conn)
    if current["somente_leitura"]:
        raise ValidationError("Esse calendário do Google é somente leitura.")
    if current["alterada"]:
        # Ocorrência alterada fica sempre no calendário da série e sem repetição própria
        data = {k: v for k, v in data.items() if k not in ("calendar_id", "repeticao")}

    if current["recorrente"] and escopo == "este":
        if not ocorrencia:
            raise ValidationError("Informe qual ocorrência alterar.")
        occ_s, occ_f = _occurrence_times(current, ocorrencia)
        base = {**current, "serie_inicio": config.iso(occ_s), "serie_fim": config.iso(occ_f)}
        data = {k: v for k, v in data.items() if k not in ("repeticao", "calendar_id")}
        f = _validate(data, conn, base)
        f.pop("_origem")
        fields = {c: f[c] for c in _COLS if c not in ("calendar_id", "repeticao", "rrule", "fuso")}
        oid = _upsert_override(conn, current, config.iso(occ_s), fields)
        return _with_conflicts(get(oid, conn), conn)

    f = _validate(data, conn, current)
    origem = f.pop("_origem")
    stamp = config.iso(config.now())
    if current["origem"] == "google" and f["calendar_id"] != current["calendar_id"]:
        # Saiu de um calendário do Google: apaga lá e cria uma cópia nova
        conn.execute(
            "UPDATE events SET excluido=1, pendente_sync=1, atualizado_em=?, rev=rev+1 WHERE id=?",
            (stamp, event_id),
        )
        conn.execute("DELETE FROM events WHERE serie_id=?", (event_id,))
        conn.commit()
        new = create({**current, **data, "inicio": f["inicio"], "fim": f["fim"]}, conn)
        if f["rrule"]:  # mantém a regra personalizada do Google na cópia
            conn.execute("UPDATE events SET rrule=?, fuso=? WHERE id=?", (f["rrule"], f["fuso"], new["id"]))
            conn.commit()
            new = _with_conflicts(get(new["id"], conn), conn)
        return new
    if current["alterada"]:
        f["repeticao"], f["rrule"], f["fuso"] = "", None, None
        f["calendar_id"] = current["calendar_id"]
    timing_changed = (f["inicio"], f["fim"], f["repeticao"], f["rrule"]) != (
        current["serie_inicio"],
        current["serie_fim"],
        current["repeticao"],
        current.get("rrule"),
    )
    sets = ", ".join(f"{c}=?" for c in _COLS)
    conn.execute(
        f"UPDATE events SET {sets}, pendente_sync=?, atualizado_em=?, rev=rev+1 WHERE id=?",
        (*(f[c] for c in _COLS), 1 if origem == "google" else 0, stamp, event_id),
    )
    if current["recorrente"] and f["calendar_id"] != current["calendar_id"]:
        # As ocorrências alteradas vão junto para o novo calendário
        conn.execute(
            "UPDATE events SET calendar_id=?, pendente_sync=?, rev=rev+1 WHERE serie_id=?",
            (f["calendar_id"], 1 if origem == "google" else 0, event_id),
        )
    if current["recorrente"] and timing_changed:
        # As datas da série mudaram: alterações antigas de ocorrências não se aplicam mais
        conn.execute("DELETE FROM events WHERE serie_id=?", (event_id,))
        if origem == "google":
            # Baixa tudo de novo depois de enviar: o Google decide quais exceções continuam
            conn.execute("DELETE FROM sync_state WHERE calendar_id=?", (f["calendar_id"],))
    conn.execute("DELETE FROM event_alerts WHERE event_id=?", (event_id,))
    conn.commit()
    return _with_conflicts(get(event_id, conn), conn)


def delete(
    event_id: int,
    conn: sqlite3.Connection | None = None,
    escopo: str = "todos",
    ocorrencia: str | None = None,
) -> None:
    conn = conn or get_conn()
    if escopo not in ESCOPOS:
        raise ValidationError("Escolha excluir só este ou todos.")
    e = get(event_id, conn)
    if e["somente_leitura"]:
        raise ValidationError("Esse calendário do Google é somente leitura.")
    google = e["origem"] == "google"
    stamp = config.iso(config.now())

    if e["alterada"]:
        # Ocorrência já alterada: vira "excluída" (continua escondendo a original da série)
        conn.execute(
            "UPDATE events SET cancelado=1, pendente_sync=?, atualizado_em=?, rev=rev+1 WHERE id=?",
            (1 if google else 0, stamp, event_id),
        )
    elif e["recorrente"] and escopo == "este":
        if not ocorrencia:
            raise ValidationError("Informe qual ocorrência excluir.")
        occ_s, occ_f = _occurrence_times(e, ocorrencia)
        _upsert_override(
            conn,
            e,
            config.iso(occ_s),
            {
                "titulo": e["titulo"],
                "inicio": config.iso(occ_s),
                "fim": config.iso(occ_f),
                "dia_inteiro": 1 if e["dia_inteiro"] else 0,
                "local": e["local"],
                "notas": e["notas"],
                "aviso_min": e["aviso_min"],
            },
            cancelado=True,
        )
    elif google and e["google_event_id"]:
        conn.execute(
            "UPDATE events SET excluido=1, pendente_sync=1, atualizado_em=?, rev=rev+1 WHERE id=?",
            (stamp, event_id),
        )
        conn.execute("DELETE FROM events WHERE serie_id=?", (event_id,))
    else:
        conn.execute("DELETE FROM events WHERE serie_id=?", (event_id,))
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
    conn.execute("DELETE FROM event_alerts WHERE event_id=?", (event_id,))
    conn.commit()


# ---------- usados pelo agendador ----------


def alerts_due(conn: sqlite3.Connection | None = None, now: datetime | None = None) -> list[dict]:
    """Ocorrências cujo aviso já chegou e que ainda não foram avisadas."""
    conn = conn or get_conn()
    now = now or config.now()
    out = []
    for e in list_range(now - timedelta(minutes=1), now + timedelta(days=1, hours=1), conn):
        if e["aviso_min"] is None or e["dia_inteiro"]:
            continue
        s = config.parse_iso(e["inicio"])
        if s - timedelta(minutes=e["aviso_min"]) <= now < s + timedelta(minutes=1):
            done = conn.execute(
                "SELECT 1 FROM event_alerts WHERE event_id=? AND ocorrencia=?", (e["id"], e["inicio"])
            ).fetchone()
            if not done:
                out.append(e)
    return out


def mark_alerted(e: dict, conn: sqlite3.Connection | None = None) -> None:
    conn = conn or get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO event_alerts (event_id, ocorrencia, avisado_em) VALUES (?,?,?)",
        (e["id"], e["inicio"], config.iso(config.now())),
    )
    conn.commit()
