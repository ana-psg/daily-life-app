"""Agendador em segundo plano.

A cada 30 s: lembretes vencidos, avisos de compromissos, sincronização com o Google
(no intervalo escolhido) e backup diário.
"""

import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from dailylife import config, db
from dailylife.core import backup, events, reminders, settings
from dailylife.desktop import notifier
from dailylife.sync import google as google_sync

log = logging.getLogger("dailylife.scheduler")
TICK = 30


class Scheduler(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="agendador")
        self._stopping = threading.Event()
        self._sync_now = threading.Event()
        self._first = True
        self._last_sync = 0.0
        self._sync_thread: threading.Thread | None = None
        self._sync_lock = threading.Lock()  # protege _sync_running e _sync_again
        self._sync_running = False
        self._sync_again = False

    def stop(self) -> None:
        self._stopping.set()

    def request_sync(self) -> None:
        self._sync_now.set()

    def run(self) -> None:
        db.init_db()
        while not self._stopping.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("erro no agendador")
            # acorda antes se pedirem sincronização
            if self._sync_now.wait(TICK):
                self._sync_now.clear()
                self.sync(force=True)

    # ---------- uma volta ----------
    def tick(self, now: datetime | None = None) -> None:
        now = now or config.now()
        conn = db.get_conn()
        self.check_reminders(conn, now)
        self.check_events(conn, now)
        self.sync()
        backup.make_backup(conn)

    def check_reminders(self, conn: sqlite3.Connection, now: datetime) -> list[dict]:
        # Não perturbe: os lembretes esperam e avisam quando o horário acabar
        if settings.in_quiet_hours(now, conn):
            return []
        first, self._first = self._first, False
        due = reminders.due(conn, now)
        if not due:
            return []
        # Avisos do Windows desligados: o aviso aparece só dentro do app
        alert = bool(settings.get("notificacoes", conn))
        som = settings.get("som", conn)
        old = [r for r in due if config.parse_iso(r["quando"]) < now - timedelta(minutes=10)]
        fresh = [r for r in due if r not in old]
        if first and len(old) > 1:
            # PC estava desligado: um aviso só com o resumo
            nomes = ", ".join(r["titulo"] for r in old[:3])
            mais = f" e mais {len(old) - 3}" if len(old) > 3 else ""
            notifier.notify(
                f"{len(old)} lembretes venceram enquanto o PC estava desligado",
                nomes + mais,
                kind="resumo",
                som=som,
                nativo=alert,
            )
            for r in old:
                reminders.mark_notified(r, conn, now)
        else:
            fresh = due
        for r in fresh:
            corpo = r["descricao"] or f"Agora · {config.parse_iso(r['quando']).strftime('%H:%M')}"
            notifier.notify(r["titulo"], corpo, kind="lembrete", ref_id=r["id"], som=som, nativo=alert)
            reminders.mark_notified(r, conn, now)
        return due

    def check_events(self, conn: sqlite3.Connection, now: datetime) -> list[dict]:
        due = events.alerts_due(conn, now)
        # Compromisso não espera: no não perturbe ou com avisos desligados, aparece só no app
        alert = bool(settings.get("notificacoes", conn)) and not settings.in_quiet_hours(now, conn)
        som = settings.get("som", conn)
        for e in due:
            s = config.parse_iso(e["inicio"])
            mins = int((s - now).total_seconds() // 60)
            quando = "agora" if mins <= 0 else f"em {mins} min"
            corpo = f"{e['inicio'][11:16]} – {e['fim'][11:16]}" + (f" · {e['local']}" if e["local"] else "")
            notifier.notify(
                f"{e['titulo']} {quando}", corpo, kind="compromisso", ref_id=e["id"], som=som, nativo=alert
            )
            events.mark_alerted(e, conn)
        return due

    def sync(self, force: bool = False) -> None:
        if not google_sync.is_connected():
            return
        minutes = settings.get("sync_min") or 5
        if force or time.monotonic() - self._last_sync >= minutes * 60 or self._last_sync == 0:
            with self._sync_lock:
                if self._sync_running:
                    if force:
                        self._sync_again = True  # roda de novo assim que a atual terminar
                    return
                self._sync_running = True
            self._last_sync = time.monotonic()
            # Em outra thread: uma conexão lenta com o Google não atrasa os lembretes
            self._sync_thread = threading.Thread(target=self._run_sync, daemon=True, name="google-sync")
            self._sync_thread.start()

    def _run_sync(self) -> None:
        try:
            while True:
                google_sync.sync_all()
                # olhar e zerar o pedido junto com o fim da rodada: um pedido que chega
                # bem no fim nunca se perde (ou roda aqui, ou abre uma rodada nova)
                with self._sync_lock:
                    if not self._sync_again:
                        self._sync_running = False
                        return
                    self._sync_again = False
        except Exception:
            log.exception("falha ao sincronizar com o Google")
            with self._sync_lock:
                self._sync_running = False
                self._sync_again = False
        finally:
            db.close_conn()


scheduler = Scheduler()
