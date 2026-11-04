"""Dados do painel e do widget numa chamada só."""

import sqlite3
from datetime import datetime, timedelta

from dailylife import config
from dailylife.core import events, reminders, settings, todos
from dailylife.db import get_conn

DIAS_LONGOS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
MESES = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]


def greeting(now: datetime, nome: str) -> str:
    h = now.hour
    text = "Bom dia" if h < 12 else "Boa tarde" if h < 18 else "Boa noite"
    return f"{text}, {nome}" if nome else text


def time_until_text(start: datetime, now: datetime) -> str:
    mins = int((start - now).total_seconds() // 60)
    if mins <= 0:
        return "agora"
    if mins < 60:
        return f"em {mins} min"
    if start.date() == now.date():
        h, m = divmod(mins, 60)
        return f"em {h} h" + (f" {m} min" if m else "")
    if start.date() == now.date() + timedelta(days=1):
        return "amanhã"
    return f"{reminders.DIAS[start.weekday()].lower()}, {start.day}/{start.month:02d}"


def week_bounds(now: datetime, offset: int = 0) -> tuple[datetime, datetime]:
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0)
    monday += timedelta(weeks=offset)
    return monday, monday + timedelta(days=7)


def overview(conn: sqlite3.Connection | None = None, now: datetime | None = None, semana: int = 0) -> dict:
    conn = conn or get_conn()
    now = now or config.now()
    nome = settings.get("nome", conn)

    # Próximo compromisso (até 7 dias), ignorando os de dia inteiro
    proximos = [
        e
        for e in events.list_range(now, now + timedelta(days=7), conn)
        if not e["dia_inteiro"] and config.parse_iso(e["fim"]) > now
    ]
    proximo = None
    if proximos:
        e = proximos[0]
        s = config.parse_iso(e["inicio"])
        proximo = {**e, "em": time_until_text(s, now), "horario": f"{e['inicio'][11:16]} – {e['fim'][11:16]}"}

    start_day = now.replace(hour=0, minute=0)
    hoje_eventos = events.list_range(start_day, start_day + timedelta(days=1), conn)

    lista_hoje = todos.list_tab("hoje", conn)
    lembretes = reminders.list_filtered("hoje", conn, now)

    total = len(lista_hoje) + len(lembretes)
    feitos = sum(1 for t in lista_hoje if t["feito"]) + sum(1 for r in lembretes if r["estado"] == "feito")

    ini, fim = week_bounds(now, semana)
    dias = []
    for i in range(7):
        d = ini + timedelta(days=i)
        dias.append(
            {
                "data": d.date().isoformat(),
                "nome": reminders.DIAS[i],
                "num": d.day,
                "hoje": d.date() == now.date(),
            }
        )
    semana_eventos = events.list_range(ini, fim, conn)
    fim_menos = fim - timedelta(days=1)
    if ini.month == fim_menos.month:
        semana_titulo = f"{ini.day} – {fim_menos.day} de {MESES[ini.month - 1]}"
    else:
        semana_titulo = (
            f"{ini.day} {MESES[ini.month - 1][:3]} – {fim_menos.day} {MESES[fim_menos.month - 1][:3]}"
        )

    return {
        "agora": config.iso(now),
        "hora": now.strftime("%H:%M"),
        "greeting": greeting(now, nome),
        "data_texto": f"{DIAS_LONGOS[now.weekday()]}, {now.day} de {MESES[now.month - 1]}",
        "data_curta": f"{DIAS_LONGOS[now.weekday()]}, {now.day} {MESES[now.month - 1][:3]}",
        "proximo": proximo,
        "hoje_eventos": hoje_eventos,
        "todos": lista_hoje,
        "lembretes": lembretes,
        "progresso": {"feitos": feitos, "total": total, "pct": round(feitos * 100 / total) if total else 0},
        "semana": {"offset": semana, "titulo": semana_titulo, "dias": dias, "eventos": semana_eventos},
    }
