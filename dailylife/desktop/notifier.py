"""Avisos: notificação nativa do Windows (win11toast) + caixa de entrada para as telas.

A caixa de entrada faz o aviso aparecer também dentro do app e no celular.
Se o win11toast não carregar (fora do Windows, ou bloqueado pelo Controle de Aplicativos
Inteligente), o aviso sai como balão do ícone da bandeja, sem botões.
"""

import itertools
import logging
import os
import threading
from collections import deque
from typing import Any

from dailylife import config, push

log = logging.getLogger("dailylife.notifier")

try:
    from win11toast import toast as _toast  # type: ignore

    TOAST_OK = True
    TOAST_ERROR = ""
except Exception as e:  # pragma: no cover - fora do Windows ou bloqueado
    _toast = None
    TOAST_OK = False
    TOAST_ERROR = str(e)

_ids = itertools.count(1)
SESSION = os.urandom(4).hex()  # muda a cada abertura do app: as telas sabem que a contagem recomeçou
_inbox = deque(maxlen=50)
_inbox_lock = threading.Lock()

# desktop/app.py liga: "abrir" mostra a janela; "balao" mostra um aviso pelo ícone da bandeja
handlers = {"abrir": None, "balao": None}

# O win11toast entrega o argumento do botão com o prefixo "http:" (ativação por protocolo)
BUTTONS = {
    "lembrete": [
        {"activationType": "protocol", "arguments": "http:resolver", "content": "Resolvido"},
        {"activationType": "protocol", "arguments": "http:adiar", "content": "Adiar 10 min"},
    ],
    "outro": [{"activationType": "protocol", "arguments": "http:abrir", "content": "Abrir"}],
}


def inbox_since(last_id: int = 0) -> list[dict]:
    with _inbox_lock:
        return [n for n in _inbox if n["id"] > last_id]


def last_id() -> int:
    with _inbox_lock:
        return _inbox[-1]["id"] if _inbox else 0


def parse_action(args: Any) -> str:
    """'http:resolver' -> 'resolver'; clique no corpo do aviso ('http:') -> ''."""
    raw = args.get("arguments", "") if isinstance(args, dict) else str(args or "")
    raw = raw.strip()
    if raw.lower().startswith("http:"):
        raw = raw[5:]
    return raw.strip("/ ").lower()


def handle_click(kind: str, ref_id: int, args: Any) -> str | None:
    from dailylife.core import reminders  # import tardio: roda na thread do aviso

    action = parse_action(args)
    try:
        if kind == "lembrete" and ref_id and action == "resolver":
            reminders.resolve(ref_id)
        elif kind == "lembrete" and ref_id and action == "adiar":
            reminders.snooze(ref_id, 10)
        elif action in ("", "abrir") and handlers.get("abrir"):
            handlers["abrir"]()
        return action
    except Exception:
        log.exception("erro ao tratar clique no aviso")
        return None


def _balloon(titulo: str, corpo: str) -> bool | None:
    fn = handlers.get("balao")
    if not fn:
        return False
    try:
        fn(titulo, corpo)
        return True
    except Exception:
        log.exception("falha no balão da bandeja")
        return False


def notify(
    titulo: str,
    corpo: str = "",
    kind: str = "info",
    ref_id: int | None = None,
    som: bool = True,
    nativo: bool = True,
) -> dict:
    item = {
        "id": next(_ids),
        "titulo": titulo,
        "corpo": corpo,
        "tipo": kind,
        "ref_id": ref_id,
        "criado_em": config.iso(config.now()),
    }
    with _inbox_lock:
        _inbox.append(item)
    log.info("aviso: %s | %s", titulo, corpo)
    if not nativo:
        return item
    push.send_async(
        {
            "titulo": titulo,
            "corpo": corpo,
            "tipo": kind,
            "id": ref_id,
            "silencioso": not som,
            "url": "/lembretes" if kind == "lembrete" else "/calendario" if kind == "compromisso" else "/",
        }
    )
    if not TOAST_OK:
        _balloon(titulo, corpo)
        return item

    # Sem app_id próprio: um ID não registrado no Windows faz o aviso sumir em silêncio.
    kwargs = {
        "buttons": BUTTONS["lembrete" if kind == "lembrete" else "outro"],
        "on_click": lambda args: handle_click(kind, ref_id, args),
    }
    if not som:
        kwargs["audio"] = {"silent": "true"}
    if os.path.exists(config.ICON_PNG):
        kwargs["icon"] = config.ICON_PNG

    def run() -> None:
        try:
            _toast(titulo, corpo, **kwargs)
        except Exception:
            log.exception("falha no aviso do Windows; usando o balão da bandeja")
            _balloon(titulo, corpo)

    threading.Thread(target=run, daemon=True, name="toast").start()
    return item
