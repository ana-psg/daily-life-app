"""Testes das correções da Fase 1 da versão 2.

Rodar: python -m unittest discover -s tests -v
"""

import os
import sys
import time
import unittest
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_app  # noqa: F401  (prepara o banco temporário)
from test_app import dt, reset

from dailylife import (
    config,
    db,
)
from dailylife.core import (
    ValidationError,
    backup,
    events,
    recurrence,
    reminders,
    settings,
)
from dailylife.desktop import notifier
from dailylife.sync import google as google_sync
from dailylife.web import app as appmod


def cal_id(nome="Trabalho"):
    return db.get_conn().execute("SELECT id FROM calendars WHERE nome=?", (nome,)).fetchone()["id"]


def titles_on(day):
    s = dt(day + "T00:00")
    return [(e["titulo"], e["inicio"][11:16]) for e in events.list_range(s, s + timedelta(days=1))]


class GoogleRuleTests(unittest.TestCase):
    def test_regras_que_viram_as_nossas(self):
        mon = dt("2026-10-19T09:00")
        self.assertEqual(recurrence.google_rule_to_simple("RRULE:FREQ=DAILY", mon), "diaria")
        self.assertEqual(recurrence.google_rule_to_simple("RRULE:FREQ=WEEKLY;BYDAY=MO", mon), "semanal")
        self.assertEqual(
            recurrence.google_rule_to_simple("RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", mon), "dias_uteis"
        )
        self.assertEqual(recurrence.google_rule_to_simple("RRULE:FREQ=MONTHLY;BYMONTHDAY=19", mon), "mensal")

    def test_regras_personalizadas_ficam_como_regra(self):
        mon = dt("2026-10-19T09:00")
        for rule in (
            "RRULE:FREQ=WEEKLY;BYDAY=TU,TH",
            "RRULE:FREQ=WEEKLY;INTERVAL=2",
            "RRULE:FREQ=DAILY;COUNT=5",
            "RRULE:FREQ=DAILY\nEXDATE:20261020T120000Z",
        ):
            self.assertIsNone(recurrence.google_rule_to_simple(rule, mon), rule)

    def test_expande_regra_com_exdate_e_until_em_utc(self):
        s, f = dt("2026-10-19T09:00"), dt("2026-10-19T09:30")
        text = "RRULE:FREQ=DAILY;UNTIL=20261023T235959Z\nEXDATE;TZID=America/Sao_Paulo:20261021T090000"
        occ = recurrence.rrule_occurrences(s, f, text, dt("2026-10-01T00:00"), dt("2026-11-01T00:00"))
        self.assertEqual([o[0].day for o in occ], [19, 20, 22, 23])

    def test_terca_e_quinta_quinzenal(self):
        s, f = dt("2026-10-20T08:00"), dt("2026-10-20T09:00")  # terça
        text = "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH"
        occ = recurrence.rrule_occurrences(s, f, text, dt("2026-10-19T00:00"), dt("2026-11-09T00:00"))
        self.assertEqual([o[0].day for o in occ], [20, 22, 3, 5])

    def test_regra_invalida_nao_derruba(self):
        s, f = dt("2026-10-20T08:00"), dt("2026-10-20T09:00")
        occ = recurrence.rrule_occurrences(
            s, f, "RRULE:FREQ=BANANA", dt("2026-10-01T00:00"), dt("2026-11-01T00:00")
        )
        self.assertEqual(len(occ), 1)


class SerieTests(unittest.TestCase):
    """Bug 7: alterar ou excluir só uma ocorrência."""

    def setUp(self):
        reset()
        self.s = events.create(
            {
                "titulo": "Daily",
                "calendar_id": cal_id(),
                "inicio": "2026-10-19T09:00",
                "fim": "2026-10-19T09:30",
                "repeticao": "dias_uteis",
            }
        )

    def test_alterar_so_este(self):
        ev = events.update(
            self.s["id"],
            {"titulo": "Daily (sala 2)", "inicio": "2026-10-21T10:00", "fim": "2026-10-21T10:30"},
            escopo="este",
            ocorrencia="2026-10-21T09:00",
        )
        self.assertTrue(ev["alterada"])
        self.assertEqual(titles_on("2026-10-21"), [("Daily (sala 2)", "10:00")])
        self.assertEqual(titles_on("2026-10-22"), [("Daily", "09:00")])
        # editar de novo a mesma ocorrência atualiza, não duplica
        events.update(
            self.s["id"],
            {"titulo": "Daily (sala 3)", "inicio": "2026-10-21T10:00", "fim": "2026-10-21T10:30"},
            escopo="este",
            ocorrencia="2026-10-21T09:00",
        )
        self.assertEqual(titles_on("2026-10-21"), [("Daily (sala 3)", "10:00")])

    def test_excluir_so_este(self):
        events.delete(self.s["id"], escopo="este", ocorrencia="2026-10-20T09:00")
        self.assertEqual(titles_on("2026-10-20"), [])
        self.assertEqual(titles_on("2026-10-21"), [("Daily", "09:00")])

    def test_excluir_ocorrencia_ja_alterada(self):
        ev = events.update(
            self.s["id"],
            {"inicio": "2026-10-21T11:00", "fim": "2026-10-21T11:30"},
            escopo="este",
            ocorrencia="2026-10-21T09:00",
        )
        events.delete(ev["id"])
        self.assertEqual(titles_on("2026-10-21"), [])

    def test_alterar_todos_muda_horario_e_descarta_alteracoes(self):
        events.update(self.s["id"], {"titulo": "Mudou"}, escopo="este", ocorrencia="2026-10-21T09:00")
        events.update(self.s["id"], {"inicio": "2026-10-19T08:00", "fim": "2026-10-19T08:30"}, escopo="todos")
        self.assertEqual(titles_on("2026-10-21"), [("Daily", "08:00")])

    def test_data_fora_da_serie_e_recusada(self):
        with self.assertRaises(ValidationError):  # sábado não faz parte de "dias úteis"
            events.update(self.s["id"], {"titulo": "X"}, escopo="este", ocorrencia="2026-10-24T09:00")

    def test_excluir_todos_apaga_tudo(self):
        events.update(self.s["id"], {"titulo": "Mudou"}, escopo="este", ocorrencia="2026-10-21T09:00")
        events.delete(self.s["id"])
        self.assertEqual(titles_on("2026-10-21"), [])
        self.assertEqual(db.get_conn().execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)

    def test_aviso_vale_para_ocorrencia_alterada(self):
        events.update(
            self.s["id"],
            {"inicio": "2026-10-21T10:00", "fim": "2026-10-21T10:30", "aviso_min": 15},
            escopo="este",
            ocorrencia="2026-10-21T09:00",
        )
        due = events.alerts_due(now=dt("2026-10-21T09:46"))
        self.assertEqual([e["inicio"] for e in due], ["2026-10-21T10:00"])

    def test_api_escopo(self):
        c = appmod.create_app(testing=True).test_client()
        r = c.patch(
            f"/api/eventos/{self.s['id']}",
            json={"titulo": "Só hoje", "escopo": "este", "ocorrencia": "2026-10-22T09:00"},
        )
        self.assertEqual(r.status_code, 200)
        r = c.delete(f"/api/eventos/{self.s['id']}?escopo=este&ocorrencia=2026-10-23T09:00")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(titles_on("2026-10-22"), [("Só hoje", "09:00")])
        self.assertEqual(titles_on("2026-10-23"), [])


class EventoVariosDiasTests(unittest.TestCase):
    """Bug 9: compromisso com horário que dura vários dias."""

    def setUp(self):
        reset()

    def test_tres_dias(self):
        events.create(
            {
                "titulo": "Congresso",
                "calendar_id": cal_id(),
                "inicio": "2026-11-03T09:00",
                "fim": "2026-11-05T18:00",
            }
        )
        for d in ("2026-11-03", "2026-11-04", "2026-11-05"):
            self.assertEqual([t for t, _ in titles_on(d)], ["Congresso"], d)
        self.assertEqual(titles_on("2026-11-06"), [])


class SomenteLeituraTests(unittest.TestCase):
    """Bug 4: calendário do Google só de leitura."""

    def setUp(self):
        reset()
        conn = db.get_conn()
        stamp = config.iso(config.now())
        conn.execute(
            "INSERT INTO calendars (nome, cor, origem, google_id, somente_leitura, criado_em, atualizado_em) "
            "VALUES ('Feriados', '#0B8043', 'google', 'fer', 1, ?, ?)",
            (stamp, stamp),
        )
        cid = conn.execute("SELECT id FROM calendars WHERE google_id='fer'").fetchone()["id"]
        conn.execute(
            "INSERT INTO events (calendar_id, titulo, inicio, fim, dia_inteiro, google_event_id, "
            "criado_em, atualizado_em) VALUES (?, 'Finados', '2026-11-02T00:00', '2026-11-03T00:00', 1, "
            "'g-fin', ?, ?)",
            (cid, stamp, stamp),
        )
        conn.commit()
        self.eid = conn.execute("SELECT id FROM events WHERE titulo='Finados'").fetchone()["id"]

    def test_marcado_como_somente_leitura(self):
        self.assertTrue(events.get(self.eid)["somente_leitura"])

    def test_nao_edita_nem_exclui(self):
        with self.assertRaises(ValidationError):
            events.update(self.eid, {"titulo": "X"})
        with self.assertRaises(ValidationError):
            events.delete(self.eid)
        self.assertEqual(events.get(self.eid)["titulo"], "Finados")


# ---------------- Google: séries como regra (bugs 5 e 6) ----------------


class Exec:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeEvents:
    def __init__(self, store):
        self.store = store
        self.calls = []
        self.n = 0

    def list(self, calendarId, pageToken=None, **kw):
        self.calls.append(("list", kw.get("singleEvents")))
        items = list(self.store.get(calendarId, {}).values())
        return Exec(lambda: {"items": items, "nextSyncToken": "tok"})

    def insert(self, calendarId, body):
        self.n += 1
        self.calls.append(("insert", body))
        return Exec(lambda: {"id": f"m{self.n}", "etag": "e", "updated": "2026-10-22T12:00:00Z"})

    def patch(self, calendarId, eventId, body):
        self.calls.append(("patch", eventId, body))
        return Exec(lambda: {"id": eventId, "etag": "e2", "updated": "2026-10-22T13:00:00Z"})

    def delete(self, calendarId, eventId):
        self.calls.append(("delete", eventId))
        return Exec(lambda: {})

    def instances(self, calendarId, eventId, timeMin, timeMax, showDeleted=True):
        self.calls.append(("instances", eventId, timeMin))
        occ = google_sync._to_local(timeMin) + timedelta(minutes=1)
        inst = {
            "id": f"{eventId}_{occ:%Y%m%dT%H%M}",
            "recurringEventId": eventId,
            "originalStartTime": {"dateTime": occ.replace(tzinfo=config.TZ).isoformat()},
        }
        return Exec(lambda: {"items": [inst]})


class FakeService:
    def __init__(self, store):
        self._ev = FakeEvents(store)

    def calendarList(self):
        cals = [
            {
                "id": "pessoa@example.com",
                "summary": "Minha agenda",
                "backgroundColor": "#039be5",
                "accessRole": "owner",
            }
        ]
        return types_ns(list=lambda pageToken=None, maxResults=250: Exec(lambda: {"items": cals}))

    def events(self):
        return self._ev


def types_ns(**kw):
    import types

    return types.SimpleNamespace(**kw)


def sync(svc):
    conn = db.get_conn()
    google_sync._migrate(conn)
    google_sync.push_pending(svc, conn)
    google_sync.sync_calendars(svc, conn)
    for cal in db.rows(conn.execute("SELECT * FROM calendars WHERE origem='google' AND visivel=1")):
        google_sync.pull_calendar(svc, conn, cal)


class GoogleSeriesTests(unittest.TestCase):
    def setUp(self):
        reset()
        self.store = {
            "pessoa@example.com": {
                "s1": {
                    "id": "s1",
                    "status": "confirmed",
                    "summary": "Inglês",
                    "updated": "2026-10-01T10:00:00Z",
                    "start": {"dateTime": "2026-10-20T19:00:00-03:00"},
                    "end": {"dateTime": "2026-10-20T20:00:00-03:00"},
                    "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=TU,TH"],
                },
                "s2": {
                    "id": "s2",
                    "status": "confirmed",
                    "summary": "Remédio",
                    "updated": "2026-10-01T10:00:00Z",
                    "start": {"dateTime": "2026-10-01T08:00:00-03:00"},
                    "end": {"dateTime": "2026-10-01T08:15:00-03:00"},
                    "recurrence": ["RRULE:FREQ=DAILY"],
                },
                "s1_x": {
                    "id": "s1_x",
                    "status": "confirmed",
                    "recurringEventId": "s1",
                    "summary": "Inglês (reposição)",
                    "updated": "2026-10-10T10:00:00Z",
                    "originalStartTime": {"dateTime": "2026-10-22T19:00:00-03:00"},
                    "start": {"dateTime": "2026-10-23T19:00:00-03:00"},
                    "end": {"dateTime": "2026-10-23T20:00:00-03:00"},
                },
                "s1_c": {
                    "id": "s1_c",
                    "status": "cancelled",
                    "recurringEventId": "s1",
                    "originalStartTime": {"dateTime": "2026-10-27T19:00:00-03:00"},
                },
            }
        }
        self.svc = FakeService(self.store)
        settings.set("google_sync_v", google_sync.SYNC_VERSION)
        sync(self.svc)

    def test_pede_series_e_nao_copias(self):
        self.assertIn(("list", False), self.svc._ev.calls)
        n = db.get_conn().execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(n, 4)  # 2 séries + 2 ocorrências alteradas, e não centenas de linhas

    def test_regra_simples_e_personalizada(self):
        conn = db.get_conn()
        s2 = conn.execute("SELECT repeticao, rrule FROM events WHERE google_event_id='s2'").fetchone()
        self.assertEqual((s2["repeticao"], s2["rrule"]), ("diaria", None))
        s1 = conn.execute("SELECT repeticao, rrule FROM events WHERE google_event_id='s1'").fetchone()
        self.assertEqual((s1["repeticao"], s1["rrule"]), ("", "RRULE:FREQ=WEEKLY;BYDAY=TU,TH"))

    def test_ocorrencias_alterada_e_cancelada_respeitadas(self):
        self.assertIn(("Inglês", "19:00"), titles_on("2026-10-20"))
        self.assertNotIn("Inglês", [t for t, _ in titles_on("2026-10-22")])
        self.assertIn(("Inglês (reposição)", "19:00"), titles_on("2026-10-23"))
        self.assertNotIn("Inglês", [t for t, _ in titles_on("2026-10-27")])
        self.assertIn(("Inglês", "19:00"), titles_on("2026-10-29"))

    def test_editar_serie_do_google_mantem_a_regra(self):
        sid = db.get_conn().execute("SELECT id FROM events WHERE google_event_id='s1'").fetchone()["id"]
        events.update(sid, {"titulo": "Inglês avançado"})
        google_sync.push_pending(self.svc, db.get_conn())
        body = [c for c in self.svc._ev.calls if c[0] == "patch"][-1][2]
        self.assertEqual(body["recurrence"], ["RRULE:FREQ=WEEKLY;BYDAY=TU,TH"])

    def test_alterar_so_este_vai_para_a_ocorrencia_no_google(self):
        sid = db.get_conn().execute("SELECT id FROM events WHERE google_event_id='s2'").fetchone()["id"]
        events.update(
            sid,
            {"inicio": "2026-10-25T09:00", "fim": "2026-10-25T09:15"},
            escopo="este",
            ocorrencia="2026-10-25T08:00",
        )
        events.delete(sid, escopo="este", ocorrencia="2026-10-26T08:00")
        google_sync.push_pending(self.svc, db.get_conn())
        calls = self.svc._ev.calls
        patched = [c for c in calls if c[0] == "patch"][-1]
        self.assertEqual(patched[1], "s2_20261025T0800")
        self.assertNotIn("recurrence", patched[2])
        self.assertIn(("delete", "s2_20261026T0800"), calls)
        self.assertEqual(
            db.get_conn().execute("SELECT COUNT(*) FROM events WHERE pendente_sync=1").fetchone()[0], 0
        )

    def test_serie_criada_no_app_sobe_com_regra(self):
        gcal = (
            db.get_conn()
            .execute("SELECT id FROM calendars WHERE google_id='pessoa@example.com'")
            .fetchone()["id"]
        )
        events.create(
            {
                "titulo": "Yoga",
                "calendar_id": gcal,
                "inicio": "2026-10-21T07:00",
                "fim": "2026-10-21T08:00",
                "repeticao": "semanal",
            }
        )
        google_sync.push_pending(self.svc, db.get_conn())
        ins = [c for c in self.svc._ev.calls if c[0] == "insert"][-1][1]
        self.assertEqual(ins["recurrence"], ["RRULE:FREQ=WEEKLY"])

    def test_cancelar_serie_inteira_no_google(self):
        self.store["pessoa@example.com"] = {"s1": {"id": "s1", "status": "cancelled"}}
        sync(self.svc)
        n = (
            db.get_conn()
            .execute(
                "SELECT COUNT(*) FROM events e JOIN events m ON e.serie_id=m.id WHERE m.google_event_id='s1'"
            )
            .fetchone()[0]
        )
        self.assertEqual(n, 0)
        self.assertIsNone(db.get_conn().execute("SELECT 1 FROM events WHERE google_event_id='s1'").fetchone())

    def test_migracao_apaga_copias_antigas(self):
        conn = db.get_conn()
        gcal = conn.execute("SELECT id FROM calendars WHERE google_id='pessoa@example.com'").fetchone()["id"]
        stamp = config.iso(config.now())
        conn.execute(
            "INSERT INTO events (calendar_id, titulo, inicio, fim, google_event_id, criado_em, atualizado_em) "
            "VALUES (?, 'cópia antiga', '2026-10-24T08:00', '2026-10-24T08:15', 's2_20261024', ?, ?)",
            (gcal, stamp, stamp),
        )
        conn.commit()
        settings.set("google_sync_v", 1)
        sync(self.svc)
        self.assertIsNone(conn.execute("SELECT 1 FROM events WHERE titulo='cópia antiga'").fetchone())
        self.assertEqual(settings.get("google_sync_v"), google_sync.SYNC_VERSION)


# ---------------- avisos (bug 1) ----------------


class NotifierTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_le_o_argumento_com_prefixo_http(self):
        self.assertEqual(notifier.parse_action({"arguments": "http:resolver", "user_input": {}}), "resolver")
        self.assertEqual(notifier.parse_action({"arguments": "http:", "user_input": {}}), "")
        self.assertEqual(notifier.parse_action({"arguments": "http:Adiar"}), "adiar")

    def test_botao_resolvido_resolve_o_lembrete(self):
        r = reminders.create({"titulo": "Conta de luz", "quando": "2026-10-22T12:00"})
        notifier.handle_click("lembrete", r["id"], {"arguments": "http:resolver", "user_input": {}})
        self.assertTrue(reminders.get(r["id"])["concluido"])

    def test_botao_adiar_adia(self):
        r = reminders.create({"titulo": "Remédio", "quando": "2026-10-22T12:00"})
        notifier.handle_click("lembrete", r["id"], {"arguments": "http:adiar", "user_input": {}})
        self.assertGreater(reminders.get(r["id"])["quando"], "2026-10-22T12:00")

    def test_sem_win11toast_usa_balao(self):
        shown = []
        old_ok, old_balao = notifier.TOAST_OK, notifier.handlers["balao"]
        notifier.TOAST_OK = False
        notifier.handlers["balao"] = lambda t, c: shown.append((t, c))
        try:
            notifier.notify("Água", "Agora", kind="lembrete", ref_id=1)
        finally:
            notifier.TOAST_OK, notifier.handlers["balao"] = old_ok, old_balao
        self.assertEqual(shown, [("Água", "Agora")])

    def test_botoes_corretos(self):
        args = [b["arguments"] for b in notifier.BUTTONS["lembrete"]]
        self.assertEqual(args, ["http:resolver", "http:adiar"])


# ---------------- PIN (bug 2) ----------------


class PinLimitTests(unittest.TestCase):
    def setUp(self):
        reset()
        appmod._login_fails.clear()
        settings.set("acesso_rede", True)
        settings.set_password("segredo2468")
        self.c = appmod.create_app(testing=True).test_client()
        self.remote = {"REMOTE_ADDR": "192.168.0.50"}

    def test_bloqueia_depois_de_cinco_erros(self):
        for _ in range(appmod.MAX_TRIES - 1):
            self.assertEqual(
                self.c.post("/entrar", data={"senha": "errada0"}, environ_base=self.remote).status_code, 401
            )
        r = self.c.post("/entrar", data={"senha": "errada0"}, environ_base=self.remote)
        self.assertEqual(r.status_code, 429)
        # nem o PIN certo entra durante o bloqueio
        r = self.c.post("/entrar", data={"senha": "segredo2468"}, environ_base=self.remote)
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.c.get("/api/painel", environ_base=self.remote).status_code, 401)

    def test_outro_aparelho_nao_e_bloqueado(self):
        for _ in range(appmod.MAX_TRIES):
            self.c.post("/entrar", data={"senha": "errada0"}, environ_base=self.remote)
        r = self.c.post(
            "/entrar", data={"senha": "segredo2468"}, environ_base={"REMOTE_ADDR": "192.168.0.51"}
        )
        self.assertEqual(r.status_code, 302)

    def test_bloqueio_dobra_e_tem_teto(self):
        t = time.monotonic()
        for _ in range(appmod.MAX_TRIES):
            appmod.register_login("x", False, now=t)
        self.assertEqual(appmod.login_blocked_for("x", now=t), 300)
        appmod.register_login("x", False, now=t)
        self.assertEqual(appmod.login_blocked_for("x", now=t), 600)
        for _ in range(10):
            appmod.register_login("x", False, now=t)
        self.assertEqual(appmod.login_blocked_for("x", now=t), 3600)
        appmod.register_login("x", True, now=t)
        self.assertEqual(appmod.login_blocked_for("x", now=t), 0)

    def test_redirecionamento_seguro(self):
        r = self.c.post(
            "/entrar?proximo=//site-ruim.com", data={"senha": "segredo2468"}, environ_base=self.remote
        )
        self.assertEqual(r.headers["Location"], "/")


# ---------------- relógio (bug 8) e outros ----------------


class MiscTests(unittest.TestCase):
    def setUp(self):
        reset()
        self.c = appmod.create_app(testing=True).test_client()

    def test_pagina_traz_a_hora_de_sao_paulo(self):
        html = self.c.get("/").get_data(as_text=True)
        self.assertRegex(html, r'data-agora="\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d"')
        self.assertIn("agora", self.c.get("/api/ping").get_json())

    def test_corpo_que_nao_e_objeto_nao_derruba(self):
        r = self.c.post("/api/todos", json=["lista"])
        self.assertEqual(r.status_code, 400)


class Fase8Tests(unittest.TestCase):
    """Funções da Fase 8 original: backup diário com rodízio."""

    def setUp(self):
        reset()

    def test_backup_uma_vez_por_dia_e_guarda_14(self):
        import glob

        os.makedirs(config.BACKUP_DIR, exist_ok=True)
        for f in glob.glob(os.path.join(config.BACKUP_DIR, "*")):
            os.remove(f)
        for i in range(20):
            open(os.path.join(config.BACKUP_DIR, f"dailylife-2026-09-{i + 1:02d}.db"), "w").close()
        self.assertIsNotNone(backup.make_backup())
        self.assertIsNone(backup.make_backup())  # mesmo dia: não repete
        self.assertEqual(len(backup.list_backups()), backup.KEEP)


if __name__ == "__main__":
    unittest.main()
