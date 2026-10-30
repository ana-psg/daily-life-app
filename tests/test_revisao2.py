"""Testes dos problemas encontrados na segunda revisão (verificação das correções da Fase 1).

Rodar: python -m unittest discover -s tests -v
"""

import os
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_app  # noqa: F401
from test_app import dt, reset
from test_fase1 import FakeService, cal_id, sync, titles_on

from dailylife import (
    config,
    db,
)
from dailylife.core import ValidationError, events, recurrence, reminders, settings
from dailylife.desktop.scheduler import Scheduler
from dailylife.sync import google as google_sync
from dailylife.web import app as appmod


def google_setup(store):
    reset()
    settings.set("google_sync_v", google_sync.SYNC_VERSION)
    svc = FakeService(store)
    sync(svc)
    gcal = (
        db.get_conn()
        .execute("SELECT id FROM calendars WHERE google_id='pessoa@example.com'")
        .fetchone()["id"]
    )
    return svc, gcal


class FusoTests(unittest.TestCase):
    """Revisão 2, item 1: série do Google em outro fuso."""

    def setUp(self):
        self.svc, self.gcal = google_setup(
            {
                "pessoa@example.com": {
                    "uk": {
                        "id": "uk",
                        "status": "confirmed",
                        "summary": "Reunião UK",
                        "updated": "2026-10-01T10:00:00Z",
                        "start": {"dateTime": "2026-11-02T09:00:00Z", "timeZone": "Europe/London"},
                        "end": {"dateTime": "2026-11-02T10:00:00Z", "timeZone": "Europe/London"},
                        "recurrence": ["RRULE:FREQ=WEEKLY"],
                    },
                    "uk_x": {
                        "id": "uk_x",
                        "status": "cancelled",
                        "recurringEventId": "uk",
                        "originalStartTime": {
                            "dateTime": "2027-04-05T09:00:00+01:00",
                            "timeZone": "Europe/London",
                        },
                    },
                }
            }
        )

    def test_guarda_fuso_e_regra(self):
        r = (
            db.get_conn()
            .execute("SELECT repeticao, rrule, fuso FROM events WHERE google_event_id='uk'")
            .fetchone()
        )
        self.assertEqual((r["repeticao"], r["rrule"], r["fuso"]), ("", "RRULE:FREQ=WEEKLY", "Europe/London"))

    def test_continua_as_9h_de_londres_no_horario_de_verao(self):
        # Inverno: 9h em Londres = 6h em São Paulo. Verão de Londres (abril): 9h = 5h.
        self.assertEqual(titles_on("2026-11-09"), [("Reunião UK", "06:00")])
        self.assertEqual(titles_on("2027-04-12"), [("Reunião UK", "05:00")])

    def test_excecao_no_verao_bate_com_a_ocorrencia(self):
        self.assertEqual(titles_on("2027-04-05"), [])  # cancelada no Google

    def test_editar_titulo_mantem_fuso_no_google(self):
        sid = db.get_conn().execute("SELECT id FROM events WHERE google_event_id='uk'").fetchone()["id"]
        events.update(sid, {"titulo": "Reunião UK (nova)"})
        google_sync.push_pending(self.svc, db.get_conn())
        body = [c for c in self.svc._ev.calls if c[0] == "patch"][-1][2]
        self.assertEqual(body["start"]["timeZone"], "Europe/London")
        self.assertTrue(body["start"]["dateTime"].startswith("2026-11-02T09:00:00"))

    def test_serie_de_sao_paulo_vira_regra_simples(self):
        self.assertEqual(
            recurrence.google_rule_to_simple(
                "RRULE:FREQ=WEEKLY", dt("2026-11-02T09:00"), "America/Sao_Paulo"
            ),
            "semanal",
        )
        self.assertIsNone(
            recurrence.google_rule_to_simple("RRULE:FREQ=WEEKLY", dt("2026-11-02T09:00"), "Europe/London")
        )


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.gcal = google_setup({"pessoa@example.com": {}})

    def test_segunda_edicao_no_mesmo_minuto_nao_se_perde(self):  # item 2
        e = events.create(
            {
                "titulo": "Dentista 10h",
                "calendar_id": self.gcal,
                "inicio": "2026-11-05T10:00",
                "fim": "2026-11-05T11:00",
            }
        )
        snapshot = db.row(db.get_conn().execute("SELECT * FROM events WHERE id=?", (e["id"],)))
        events.update(e["id"], {"titulo": "Dentista 14h"})
        google_sync._mark_pushed(
            db.get_conn(), snapshot, "g-d", {"etag": "e", "updated": "2026-10-30T12:00:00Z"}
        )
        self.assertEqual(
            db.get_conn().execute("SELECT pendente_sync FROM events WHERE id=?", (e["id"],)).fetchone()[0], 1
        )

    def test_migracao_nao_apaga_serie_com_alteracao_pendente(self):  # item 4
        conn = db.get_conn()
        s = events.create(
            {
                "titulo": "Yoga",
                "calendar_id": self.gcal,
                "inicio": "2026-11-02T07:00",
                "fim": "2026-11-02T08:00",
                "repeticao": "diaria",
            }
        )
        conn.execute("UPDATE events SET pendente_sync=0, google_event_id='yoga' WHERE id=?", (s["id"],))
        conn.commit()
        events.delete(s["id"], escopo="este", ocorrencia="2026-11-03T07:00")
        settings.set("google_sync_v", 1)
        google_sync._migrate(conn)
        self.assertIsNotNone(conn.execute("SELECT 1 FROM events WHERE id=?", (s["id"],)).fetchone())
        self.assertEqual(titles_on("2026-11-03"), [])

    def test_instancia_cancelada_sem_serie_some(self):  # item 5
        store = self.svc._ev.store["pessoa@example.com"]
        store["inv"] = {
            "id": "inv_1",
            "status": "confirmed",
            "recurringEventId": "de-outra-pessoa",
            "summary": "Convite",
            "updated": "2026-10-01T10:00:00Z",
            "originalStartTime": {"dateTime": "2026-11-04T15:00:00-03:00"},
            "start": {"dateTime": "2026-11-04T15:00:00-03:00"},
            "end": {"dateTime": "2026-11-04T16:00:00-03:00"},
        }
        sync(self.svc)
        self.assertEqual(titles_on("2026-11-04"), [("Convite", "15:00")])
        store["inv"] = {
            "id": "inv_1",
            "status": "cancelled",
            "recurringEventId": "de-outra-pessoa",
            "originalStartTime": {"dateTime": "2026-11-04T15:00:00-03:00"},
        }
        sync(self.svc)
        self.assertEqual(titles_on("2026-11-04"), [])

    def test_mover_serie_leva_as_alteracoes(self):  # item 6
        s = events.create(
            {
                "titulo": "Aula",
                "calendar_id": cal_id("Pessoal"),
                "inicio": "2026-11-02T19:00",
                "fim": "2026-11-02T20:00",
                "repeticao": "semanal",
            }
        )
        events.delete(s["id"], escopo="este", ocorrencia="2026-11-09T19:00")
        events.update(s["id"], {"calendar_id": cal_id("Trabalho")})
        db.get_conn().execute("UPDATE calendars SET visivel=0 WHERE id=?", (cal_id("Pessoal"),))
        db.get_conn().commit()
        self.assertEqual(titles_on("2026-11-09"), [])
        self.assertEqual(titles_on("2026-11-16"), [("Aula", "19:00")])

    def test_mudar_horario_de_serie_do_google_baixa_tudo_de_novo(self):  # item 7
        s = events.create(
            {
                "titulo": "Daily",
                "calendar_id": self.gcal,
                "inicio": "2026-11-02T09:00",
                "fim": "2026-11-02T09:30",
                "repeticao": "dias_uteis",
            }
        )
        self.assertIsNotNone(
            db.get_conn().execute("SELECT 1 FROM sync_state WHERE calendar_id=?", (self.gcal,)).fetchone()
        )
        events.update(s["id"], {"inicio": "2026-11-02T10:00", "fim": "2026-11-02T10:30"})
        self.assertIsNone(
            db.get_conn().execute("SELECT 1 FROM sync_state WHERE calendar_id=?", (self.gcal,)).fetchone()
        )

    def test_limite_de_uso_com_motivo_em_maiusculas(self):  # item 8
        class E(Exception):
            pass

        e = E()
        e.error_details = [{"reason": "RATE_LIMIT_EXCEEDED"}]
        e.content = b'{"error": {"errors": [{"reason": "rateLimitExceeded"}]}}'
        reasons = google_sync._error_reasons(e)
        self.assertTrue(google_sync._is_rate_limit(403, reasons))
        self.assertFalse(reasons & google_sync.PERMISSION_REASONS)

    def test_desconectar_durante_sincronizacao(self):  # item 14
        google_sync._lock.acquire()
        old = google_sync._lock.acquire

        class FastLock:
            def acquire(self, timeout=None, blocking=True):
                return False

            def release(self):
                pass

        google_sync._lock.release()
        google_sync._lock, real = FastLock(), google_sync._lock
        try:
            with self.assertRaises(ValidationError):
                google_sync.disconnect()
        finally:
            google_sync._lock = real
        self.assertIsNotNone(old)


class AgendadorTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_pedido_durante_sincronizacao_roda_depois(self):  # item 9
        calls = []
        gate = threading.Event()
        old = (google_sync.sync_all, google_sync.is_connected)

        def fake_sync():
            calls.append(1)
            if len(calls) == 1:
                gate.wait(2)

        google_sync.sync_all = fake_sync
        google_sync.is_connected = lambda: True
        try:
            s = Scheduler()
            s.sync(force=True)
            s.sync(force=True)  # chega enquanto a primeira roda
            gate.set()
            s._sync_thread.join(3)
        finally:
            google_sync.sync_all, google_sync.is_connected = old
        self.assertEqual(len(calls), 2)

    def test_alterar_so_este_nao_repete_aviso_de_hoje(self):  # item 10
        s = events.create(
            {
                "titulo": "Daily",
                "calendar_id": cal_id(),
                "inicio": "2026-11-02T09:00",
                "fim": "2026-11-02T09:30",
                "repeticao": "dias_uteis",
                "aviso_min": 5,
            }
        )
        now = dt("2026-11-02T08:56")
        for e in events.alerts_due(now=now):
            events.mark_alerted(e)
        events.update(s["id"], {"titulo": "Daily (quinta)"}, escopo="este", ocorrencia="2026-11-05T09:00")
        self.assertEqual(events.alerts_due(now=now), [])


class LembreteTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_mensal_depois_de_anos(self):  # item 11
        r = reminders.create({"titulo": "Anual-ish", "quando": "2022-01-10T09:00", "repeticao": "mensal"})
        r = reminders.resolve(r["id"], now=dt("2026-10-30T10:00"))
        self.assertEqual(r["quando"], "2026-11-10T09:00")

    def test_marcado_e_remarcado_para_hoje_volta_a_valer(self):  # item 12
        today = config.now().date()
        r = reminders.create({"titulo": "Ligar", "quando": f"{today}T07:00", "repeticao": "diaria"})
        reminders.resolve(r["id"])
        r = reminders.update(r["id"], {"titulo": "Ligar", "quando": f"{today}T23:58", "repeticao": "diaria"})
        self.assertFalse(r["feito_hoje"])


class HostTests(unittest.TestCase):  # item 13
    def test_local_e_tailscale_valem(self):
        for host in ("notebook.tail1234.ts.net", "100.101.102.103:5055", "localhost:5055"):
            self.assertTrue(appmod.host_allowed(host), host)
        for host in (
            "attacker.example:5055",
            "127.0.0.1.nip.io:5055",
            "desktop:5055",
            "ts.net.example.com",
        ):
            self.assertFalse(appmod.host_allowed(host), host)


if __name__ == "__main__":
    unittest.main()
