"""Testes da sincronização com o Google (com um Google falso) e do desktop/app.py (com pywebview falso).

Rodar: python -m unittest discover -s tests -v
"""

import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_app  # noqa: F401  (prepara banco temporário)
from test_app import reset

from dailylife import (
    db,
)
from dailylife.core import events
from dailylife.sync import google as google_sync


class Exec:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeEvents:
    def __init__(self, store):
        self.store = store  # {cal_gid: {event_id: item}}
        self.inserted, self.patched, self.deleted = [], [], []
        self.counter = 0

    def list(self, calendarId, pageToken=None, **kw):
        items = list(self.store.get(calendarId, {}).values())
        return Exec(lambda: {"items": items, "nextSyncToken": "tok-1"})

    def insert(self, calendarId, body):
        self.counter += 1
        eid = f"new{self.counter}"
        self.inserted.append((calendarId, body))
        return Exec(lambda: {"id": eid, "etag": "e1", "updated": "2026-10-22T12:00:00.000Z"})

    def patch(self, calendarId, eventId, body):
        self.patched.append((calendarId, eventId, body))
        return Exec(lambda: {"id": eventId, "etag": "e2", "updated": "2026-10-22T13:00:00.000Z"})

    def delete(self, calendarId, eventId):
        self.deleted.append((calendarId, eventId))
        return Exec(lambda: {})


class FakeCalendarList:
    def __init__(self, cals):
        self.cals = cals

    def list(self, pageToken=None, maxResults=250):
        return Exec(lambda: {"items": self.cals})


class FakeService:
    def __init__(self, cals, store):
        self._cl = FakeCalendarList(cals)
        self._ev = FakeEvents(store)

    def calendarList(self):
        return self._cl

    def events(self):
        return self._ev


class GoogleSyncTests(unittest.TestCase):
    def setUp(self):
        reset()
        self.conn = db.get_conn()
        cals = [
            {
                "id": "pessoa@example.com",
                "summary": "Minha agenda",
                "backgroundColor": "#039be5",
                "accessRole": "owner",
            },
            {
                "id": "pt.brazilian#holiday@group.v.calendar.google.com",
                "summary": "Feriados",
                "backgroundColor": "#0b8043",
                "accessRole": "reader",
            },
        ]
        store = {
            "pessoa@example.com": {
                "g1": {
                    "id": "g1",
                    "status": "confirmed",
                    "summary": "Consulta",
                    "updated": "2026-10-20T10:00:00Z",
                    "start": {"dateTime": "2026-10-23T14:00:00-03:00"},
                    "end": {"dateTime": "2026-10-23T15:00:00-03:00"},
                    "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]},
                },
                "g2": {
                    "id": "g2",
                    "status": "confirmed",
                    "summary": "Viagem",
                    "updated": "2026-10-20T10:00:00Z",
                    "start": {"date": "2026-10-30"},
                    "end": {"date": "2026-11-02"},
                },
                "g3": {
                    "id": "g3",
                    "status": "confirmed",
                    "summary": "UTC",
                    "updated": "2026-10-20T10:00:00Z",
                    "start": {"dateTime": "2026-10-24T13:00:00Z"},
                    "end": {"dateTime": "2026-10-24T14:00:00Z"},
                },
            }
        }
        self.svc = FakeService(cals, store)
        self.store = store

    def pull_all(self):
        google_sync.sync_calendars(self.svc, self.conn)
        for cal in db.rows(self.conn.execute("SELECT * FROM calendars WHERE origem='google' AND visivel=1")):
            google_sync.pull_calendar(self.svc, self.conn, cal)

    def test_importa_todos_os_calendarios_e_eventos(self):
        self.pull_all()
        cals = db.rows(self.conn.execute("SELECT * FROM calendars WHERE origem='google'"))
        self.assertEqual(len(cals), 2)
        self.assertTrue(all(c["visivel"] for c in cals))
        feriados = [c for c in cals if c["nome"] == "Feriados"][0]
        self.assertEqual(feriados["somente_leitura"], 1)
        ev = self.conn.execute("SELECT * FROM events WHERE google_event_id='g1'").fetchone()
        self.assertEqual(ev["inicio"], "2026-10-23T14:00")
        self.assertEqual(ev["aviso_min"], 30)
        viagem = self.conn.execute("SELECT * FROM events WHERE google_event_id='g2'").fetchone()
        self.assertEqual(
            (viagem["inicio"], viagem["fim"], viagem["dia_inteiro"]),
            ("2026-10-30T00:00", "2026-11-02T00:00", 1),
        )
        utc = self.conn.execute("SELECT * FROM events WHERE google_event_id='g3'").fetchone()
        self.assertEqual(utc["inicio"], "2026-10-24T10:00")  # 13h UTC = 10h em São Paulo

    def test_cancelado_no_google_some_daqui(self):
        self.pull_all()
        self.store["pessoa@example.com"]["g1"] = {"id": "g1", "status": "cancelled"}
        self.pull_all()
        self.assertIsNone(self.conn.execute("SELECT 1 FROM events WHERE google_event_id='g1'").fetchone())

    def test_envia_criado_editado_excluido(self):
        self.pull_all()
        cal = self.conn.execute("SELECT id FROM calendars WHERE google_id='pessoa@example.com'").fetchone()[
            "id"
        ]
        novo = events.create(
            {
                "titulo": "Do app",
                "calendar_id": cal,
                "inicio": "2026-10-25T09:00",
                "fim": "2026-10-25T10:00",
                "repeticao": "semanal",
                "aviso_min": 10,
            }
        )
        g1 = self.conn.execute("SELECT id FROM events WHERE google_event_id='g1'").fetchone()["id"]
        events.update(g1, {"titulo": "Consulta (mudou)"})
        g3 = self.conn.execute("SELECT id FROM events WHERE google_event_id='g3'").fetchone()["id"]
        events.delete(g3)
        google_sync.push_pending(self.svc, self.conn)
        ev = self.svc._ev
        self.assertEqual(len(ev.inserted), 1)
        body = ev.inserted[0][1]
        self.assertEqual(body["recurrence"], ["RRULE:FREQ=WEEKLY"])
        self.assertTrue(body["start"]["dateTime"].endswith("-03:00"))
        self.assertEqual(ev.patched[0][1], "g1")
        self.assertEqual(ev.deleted[0][1], "g3")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM events WHERE pendente_sync=1").fetchone()[0], 0
        )
        self.assertEqual(events.get(novo["id"])["google_event_id"], "new1")

    def test_edicao_local_mais_recente_vence(self):
        self.pull_all()
        g1 = self.conn.execute("SELECT id FROM events WHERE google_event_id='g1'").fetchone()["id"]
        events.update(g1, {"titulo": "Minha versão"})
        self.pull_all()  # o Google ainda tem a versão antiga (updated 20/10)
        self.assertEqual(events.get(g1)["titulo"], "Minha versão")

    def test_calendario_somente_leitura_recusa_criar(self):
        self.pull_all()
        fer = self.conn.execute("SELECT id FROM calendars WHERE nome='Feriados'").fetchone()["id"]
        with self.assertRaises(Exception):
            events.create(
                {"titulo": "X", "calendar_id": fer, "inicio": "2026-10-25T09:00", "fim": "2026-10-25T10:00"}
            )

    def test_desconectar_tira_calendarios_do_google(self):
        self.pull_all()
        google_sync.disconnect()
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM calendars WHERE origem='google'").fetchone()[0], 0
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM calendars WHERE origem='local'").fetchone()[0], 4
        )


class DesktopImportTests(unittest.TestCase):
    """desktop/app.py importa e cria as janelas com um pywebview falso."""

    def test_cria_janelas_e_ganchos(self):
        created = []

        class Ev:
            def __init__(self):
                self.handlers = []

            def __iadd__(self, fn):
                self.handlers.append(fn)
                return self

        class Win:
            def __init__(self, title, url, **kw):
                self.title, self.url, self.kw = title, url, kw
                self.events = types.SimpleNamespace(closing=Ev(), moved=Ev(), resized=Ev())
                self.visible = not kw.get("hidden")
                self.on_top = kw.get("on_top", False)

            def hide(self):
                self.visible = False

            def show(self):
                self.visible = True

            def restore(self):
                pass

            def destroy(self):
                pass

        fake = types.ModuleType("webview")
        fake.create_window = lambda title, url, **kw: created.append(Win(title, url, **kw)) or created[-1]
        fake.start = lambda *a, **k: None
        sys.modules["webview"] = fake
        reset()
        import importlib

        from dailylife.desktop import app as desktop

        importlib.reload(desktop)
        d = desktop.Desktop()
        d.create_windows()
        self.assertEqual(len(created), 2)
        painel, widget = created
        self.assertTrue(widget.kw["frameless"])
        self.assertTrue(painel.visible)
        self.assertFalse(widget.visible)
        d.show_widget()
        self.assertTrue(widget.visible)
        self.assertFalse(painel.visible)
        # fechar só esconde
        self.assertFalse(widget.events.closing.handlers[0]())
        d.set_on_top(True)
        self.assertTrue(widget.on_top)
        # posição é salva
        widget.events.moved.handlers[0](100, 200)
        self.assertEqual(d.geo["widget"]["x"], 100)


if __name__ == "__main__":
    unittest.main()
