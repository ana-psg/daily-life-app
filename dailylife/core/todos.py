"""To-do: listas Hoje, Semana, Projetos, subtarefas, prioridade e vencimento."""

import re
import sqlite3
from datetime import timedelta
from typing import Any

from dailylife import config
from dailylife.core import NotFound, ValidationError, as_bool, as_int, clean_text, require_text
from dailylife.db import get_conn, row, rows

PRIORIDADES = ("alta", "media", "baixa")
PRIO_ORDEM = {"alta": 0, "media": 1, "baixa": 2}
LISTAS = ("hoje", "semana", "projetos")
ABAS = (*LISTAS, "feitas")


def _list_key(data: dict) -> str:
    lista = data.get("lista") or "hoje"
    if lista not in LISTAS:
        raise ValidationError("Lista não encontrada.")
    return lista


def _normalize_due(value: Any) -> str | None:
    if value in (None, ""):
        return None
    value = str(value).strip()
    try:
        if len(value) == 10:
            config.parse_iso(value)
            return value
        return config.iso(config.parse_iso(value))
    except ValueError:
        raise ValidationError("Data de vencimento inválida.") from None


def parse_quick(text: str) -> dict:
    """Campo rápido: 'Ligar pro banco amanhã !alta #semana'."""
    out = {}
    hoje = config.now().date()
    t = " " + text.strip() + " "
    m = re.search(r"\s!(alta|media|média|baixa)\b", t, re.I)
    if m:
        out["prioridade"] = m.group(1).lower().replace("média", "media")
        t = t.replace(m.group(0), " ")
    m = re.search(r"\s#(hoje|semana|projetos?)\b", t, re.I)
    if m:
        lista = m.group(1).lower()
        out["lista"] = "projetos" if lista.startswith("projeto") else lista
        t = t.replace(m.group(0), " ")
    m = re.search(r"\s(amanhã|amanha|hoje)\s", t, re.I)
    if m:
        palavra = m.group(1).lower()
        d = hoje + timedelta(days=0 if palavra == "hoje" else 1)
        out["vencimento"] = d.isoformat()
        t = t.replace(m.group(0), " ", 1)
        if palavra != "hoje" and "lista" not in out:
            out["lista"] = "semana"
    out["titulo"] = re.sub(r"\s+", " ", t).strip()
    return out


def _serialize(t: dict, today: str) -> dict:
    venc = t.get("vencimento")
    t["feito"] = bool(t["feito"])
    t["atrasada"] = bool(venc and not t["feito"] and venc[:10] < today)
    return t


def get(todo_id: int, conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or get_conn()
    t = row(conn.execute("SELECT * FROM todos WHERE id=?", (todo_id,)))
    if not t:
        raise NotFound("Tarefa não encontrada.")
    today = config.now().date().isoformat()
    t = _serialize(t, today)
    t["subtarefas"] = [
        _serialize(s, today)
        for s in rows(conn.execute("SELECT * FROM todos WHERE parent_id=? ORDER BY ordem, id", (todo_id,)))
    ]
    return t


def list_tab(aba: str = "hoje", conn: sqlite3.Connection | None = None) -> list[dict]:
    """Tarefas principais de uma aba, com subtarefas."""
    conn = conn or get_conn()
    if aba not in ABAS:
        raise ValidationError("Aba inválida.")
    today = config.now().date().isoformat()
    base = "SELECT * FROM todos t WHERE t.parent_id IS NULL "
    if aba == "feitas":
        items = rows(conn.execute(base + "AND t.feito=1 ORDER BY t.feito_em DESC LIMIT 200"))
    elif aba == "hoje":
        items = rows(
            conn.execute(
                base + "AND ((t.lista='hoje' AND (t.feito=0 OR substr(t.feito_em,1,10)=?)) "
                "OR (t.vencimento IS NOT NULL AND substr(t.vencimento,1,10)<=? "
                "    AND (t.feito=0 OR substr(t.feito_em,1,10)=?)))",
                (today, today, today),
            )
        )
    else:
        items = rows(
            conn.execute(base + "AND t.lista=? AND (t.feito=0 OR substr(t.feito_em,1,10)=?)", (aba, today))
        )
    if aba != "feitas":
        items.sort(key=lambda t: (t["feito"], t["ordem"], PRIO_ORDEM.get(t["prioridade"], 1), t["id"]))
    ids = [t["id"] for t in items]
    subs = {}
    if ids:
        q = ",".join("?" * len(ids))
        for s in rows(conn.execute(f"SELECT * FROM todos WHERE parent_id IN ({q}) ORDER BY ordem, id", ids)):
            subs.setdefault(s["parent_id"], []).append(_serialize(s, today))
    for t in items:
        _serialize(t, today)
        t["subtarefas"] = subs.get(t["id"], [])
    return items


def counts(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    conn = conn or get_conn()
    out = {}
    for aba in ("hoje", "semana", "projetos"):
        out[aba] = sum(1 for t in list_tab(aba, conn) if not t["feito"])
    out["feitas"] = conn.execute("SELECT COUNT(*) FROM todos WHERE feito=1 AND parent_id IS NULL").fetchone()[
        0
    ]
    return out


def create(data: dict, conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or get_conn()
    if data.get("texto") and not data.get("titulo"):
        # O que foi escrito (#semana, !alta, amanhã) vale mais que a aba onde a tarefa foi digitada
        data = {**{k: v for k, v in data.items() if k != "texto"}, **parse_quick(data["texto"])}
    titulo = require_text(data, "titulo", "O título da tarefa")
    prioridade = data.get("prioridade") or "media"
    if prioridade not in PRIORIDADES:
        raise ValidationError("Prioridade inválida.")
    parent_id = as_int(data["parent_id"], "Tarefa principal") if data.get("parent_id") else None
    if parent_id:
        parent = conn.execute("SELECT lista FROM todos WHERE id=?", (parent_id,)).fetchone()
        if not parent:
            raise ValidationError("Tarefa principal não encontrada.")
        lista = parent["lista"]
    else:
        lista = _list_key(data)
    stamp = config.iso(config.now())
    ordem = conn.execute(
        "SELECT COALESCE(MAX(ordem), 0) + 1 FROM todos WHERE lista=? AND parent_id IS ?", (lista, parent_id)
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO todos (lista, parent_id, titulo, notas, prioridade, vencimento, ordem, "
        "criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            lista,
            parent_id,
            titulo,
            clean_text(data.get("notas"), "Notas"),
            prioridade,
            _normalize_due(data.get("vencimento")),
            ordem,
            stamp,
            stamp,
        ),
    )
    conn.commit()
    return get(cur.lastrowid, conn)


def update(todo_id: int, data: dict, conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or get_conn()
    current = get(todo_id, conn)
    fields = {}
    if "titulo" in data:
        fields["titulo"] = require_text(data, "titulo", "O título da tarefa")
    if "notas" in data:
        fields["notas"] = clean_text(data.get("notas"), "Notas")
    if "prioridade" in data:
        if data["prioridade"] not in PRIORIDADES:
            raise ValidationError("Prioridade inválida.")
        fields["prioridade"] = data["prioridade"]
    if "vencimento" in data:
        fields["vencimento"] = _normalize_due(data.get("vencimento"))
    if "lista" in data:
        if current["parent_id"]:
            raise ValidationError("Subtarefas ficam na lista da tarefa principal.")
        fields["lista"] = _list_key(data)
    if "feito" in data:
        feito = as_bool(data["feito"])
        fields["feito"] = 1 if feito else 0
        fields["feito_em"] = config.iso(config.now()) if feito else None
    if not fields:
        return current
    fields["atualizado_em"] = config.iso(config.now())
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE todos SET {sets} WHERE id=?", (*fields.values(), todo_id))
    if "lista" in fields:
        conn.execute("UPDATE todos SET lista=? WHERE parent_id=?", (fields["lista"], todo_id))
    conn.commit()
    return get(todo_id, conn)


def delete(todo_id: int, conn: sqlite3.Connection | None = None) -> None:
    conn = conn or get_conn()
    get(todo_id, conn)
    conn.execute("DELETE FROM todos WHERE parent_id=?", (todo_id,))
    conn.execute("DELETE FROM todos WHERE id=?", (todo_id,))
    conn.commit()


def reorder(ids: list[int], conn: sqlite3.Connection | None = None) -> None:
    conn = conn or get_conn()
    if not isinstance(ids, list):
        raise ValidationError("Ordem inválida.")
    for i, todo_id in enumerate(ids):
        conn.execute("UPDATE todos SET ordem=? WHERE id=?", (i, as_int(todo_id, "Tarefa")))
    conn.commit()
