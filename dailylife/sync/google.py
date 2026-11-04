"""Sincronização com o Google Agenda: login, estado e a rodada completa.

Como funciona:
- Login OAuth uma vez (abre o navegador). O token fica em token.json, na pasta de dados.
- Todos os calendários da conta entram no app e podem ser escondidos.
- Baixa só o que mudou usando o syncToken do Google; se o token expira (410), refaz (pull.py).
- Envia ao Google o que mudou no app (push.py). Conflito: vence a alteração mais recente.
- Sem internet: as mudanças ficam marcadas e vão quando a conexão voltar.

Precisa de credentials.json (Google Cloud > Credenciais > ID do cliente OAuth > App para computador).
Passo a passo no README.
"""

import logging
import os
import sqlite3
import threading
from typing import Any

from dailylife import config
from dailylife.core import recurrence, settings
from dailylife.db import get_conn, rows
from dailylife.sync.common import STATE, HttpError
from dailylife.sync.pull import pull_calendar, sync_calendars
from dailylife.sync.push import push_pending

log = logging.getLogger("dailylife.google")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
LOGIN_TIMEOUT = 300  # segundos para concluir o login: quem fecha a aba não pode travar o botão Conectar

_lock = threading.Lock()

try:  # as bibliotecas do Google são opcionais
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    LIBS_OK = True
except ImportError:  # pragma: no cover
    LIBS_OK = False


def has_credentials() -> bool:
    return os.path.exists(config.CREDENTIALS_PATH)


def is_connected() -> bool:
    return os.path.exists(config.TOKEN_PATH)


def status() -> dict:
    return {
        "bibliotecas": LIBS_OK,
        "credenciais": has_credentials(),
        "pasta_credenciais": os.path.dirname(config.CREDENTIALS_PATH),
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
        raise RuntimeError(
            f"Coloque o arquivo credentials.json em {os.path.dirname(config.CREDENTIALS_PATH)}."
        )
    STATE["conectando"] = True
    STATE["erro"] = ""
    try:
        flow = InstalledAppFlow.from_client_secrets_file(config.CREDENTIALS_PATH, SCOPES)
        try:
            creds = flow.run_local_server(
                port=0,
                prompt="consent",
                success_message="Pronto! Pode fechar esta aba e voltar ao Daily Life.",
                timeout_seconds=LOGIN_TIMEOUT,
            )
        except AttributeError:  # a biblioteca falha assim quando o tempo acaba sem resposta do navegador
            raise RuntimeError("o login não foi concluído a tempo. Clique em Conectar de novo.") from None
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
        STATE["erro"] = "Falta a biblioteca python-dateutil. Reinstale o Daily Life."
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
