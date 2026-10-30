"""Testes dos bugs encontrados na revisão independente (Fase 1 da versão 2).

Rodar: python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_app  # noqa: F401
from test_app import dt, reset
from test_fase1 import FakeService, sync

from dailylife import (
    db,
)
from dailylife.core import (
    backup,
    events,
    reminders,
    settings,
    todos,
)
from dailylife.desktop import notifier
from dailylife.desktop.scheduler import Scheduler
from dailylife.sync import google as google_sync
from dailylife.web import app as appmod


class SegurancaTests(unittest.TestCase):
    """Revisão 1: sites de fora não podem mexer no app (CSRF e DNS rebinding)."""

    def setUp(self):
        reset()
        self.c = appmod.create_app(testing=True).test_client()

    def test_post_de_outro_site_e_bloqueado(self):
        r = self.c.post(
            "/api/importar", json={"app": "Daily Life"}, headers={"Origin": "https://site-ruim.example"}
        )
        self.assertEqual(r.status_code, 403)
        r = self.c.post("/api/janela/sair", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status_code, 403)
        self.assertGreater(db.get_conn().execute("SELECT COUNT(*) FROM calendars").fetchone()[0], 0)

    def test_dominio_no_host_e_bloqueado(self):
        r = self.c.get("/api/exportar", headers={"Host": "attacker.example:5055"})
        self.assertEqual(r.status_code, 403)

    def test_o_proprio_app_continua_funcionando(self):
        for host in ("127.0.0.1:5055", "localhost:5055"):
            r = self.c.post(
                "/api/todos", json={"titulo": "ok"}, headers={"Host": host, "Origin": f"http://{host}"}
            )
            self.assertEqual(r.status_code, 201, host)

    def test_trocar_pin_desconecta_outros_aparelhos(self):
        settings.set("acesso_rede", True)
        settings.set_password("chave1357")
        appmod._login_fails.clear()
        remote = {"REMOTE_ADDR": "192.168.0.60"}
        self.c.post("/entrar", data={"senha": "chave1357"}, environ_base=remote)
        self.assertEqual(self.c.get("/api/painel", environ_base=remote).status_code, 200)
        settings.set_password("chave9753")
        self.assertEqual(self.c.get("/api/painel", environ_base=remote).status_code, 401)


class LembreteTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_resolvido_que_vira_recorrente_volta_a_avisar(self):  # revisão 2
        r = reminders.create({"titulo": "Vitamina", "quando": "2026-10-22T08:00"})
        reminders.resolve(r["id"], now=dt("2026-10-22T08:05"))
        reminders.update(r["id"], {"titulo": "Vitamina", "quando": "2026-10-23T08:00", "repeticao": "diaria"})
        due = reminders.due(now=dt("2026-10-23T08:01"))
        self.assertEqual([x["titulo"] for x in due], ["Vitamina"])

    def test_mensal_perdido_fica_atrasado_e_avisa(self):  # revisão 3
        reminders.create({"titulo": "Fatura", "quando": "2026-10-15T09:00", "repeticao": "mensal"})
        due = reminders.due(now=dt("2026-10-16T10:00"))
        self.assertEqual([x["quando"] for x in due], ["2026-10-15T09:00"])
        item = reminders.list_filtered("hoje", now=dt("2026-10-16T10:00"))[0]
        self.assertTrue(item["atrasado"])

    def test_editar_titulo_nao_muda_hora_base(self):  # revisão 6
        r = reminders.create({"titulo": "Água", "quando": "2026-10-22T08:00", "repeticao": "horas:2"})
        for t in ("2026-10-22T08:01", "2026-10-22T10:01"):
            for x in reminders.due(now=dt(t)):
                reminders.mark_notified(x, now=dt(t))
        cur = reminders.get(r["id"])
        self.assertEqual(cur["quando"], "2026-10-22T12:00")
        reminders.update(r["id"], {"titulo": "Beber água", "quando": cur["quando"], "repeticao": "horas:2"})
        r2 = reminders.resolve(r["id"], now=dt("2026-10-22T15:00"))
        self.assertEqual(r2["quando"], "2026-10-23T08:00")

    def test_mensal_adiado_continua_no_mesmo_dia(self):  # revisão 7
        r = reminders.create({"titulo": "Aluguel", "quando": "2026-10-05T09:00", "repeticao": "mensal"})
        reminders.snooze(r["id"], 24 * 60, now=dt("2026-10-05T09:00"))
        r2 = reminders.resolve(r["id"], now=dt("2026-10-06T09:30"))
        self.assertEqual(r2["quando"], "2026-11-05T09:00")

    def test_desfazer_nao_avisa_de_novo(self):  # revisão 10
        r = reminders.create({"titulo": "Remédio", "quando": "2026-10-22T08:00", "repeticao": "diaria"})
        for x in reminders.due(now=dt("2026-10-22T08:01")):
            reminders.mark_notified(x, now=dt("2026-10-22T08:01"))
        reminders.resolve(r["id"], now=dt("2026-10-22T08:05"))
        reminders.undo(r["id"], now=dt("2026-10-22T08:06"))
        self.assertEqual(reminders.due(now=dt("2026-10-22T08:07")), [])

    def test_aviso_e_marcar_ao_mesmo_tempo(self):  # revisão 22
        r = reminders.create({"titulo": "Água", "quando": "2026-10-22T08:00", "repeticao": "horas:2"})
        stale = reminders.due(now=dt("2026-10-22T08:01"))[0]
        reminders.resolve(r["id"], now=dt("2026-10-22T08:01"))
        reminders.mark_notified(stale, now=dt("2026-10-22T08:01"))
        self.assertEqual(reminders.get(r["id"])["quando"], "2026-10-23T08:00")


class AgendadorTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_nao_perturbe_segura_e_depois_avisa(self):  # revisão 8
        settings.update({"nao_perturbe": True, "np_inicio": "22:00", "np_fim": "07:00"})
        reminders.create({"titulo": "Tarde da noite", "quando": "2026-10-22T22:30"})
        s = Scheduler()
        s._first = False
        before = notifier.last_id()
        self.assertEqual(s.check_reminders(db.get_conn(), dt("2026-10-22T22:31")), [])
        self.assertEqual(notifier.inbox_since(before), [])
        s.check_reminders(db.get_conn(), dt("2026-10-23T07:01"))
        self.assertEqual([n["titulo"] for n in notifier.inbox_since(before)], ["Tarde da noite"])

    def test_avisos_desligados_aparecem_so_no_app(self):
        settings.update({"notificacoes": False})
        reminders.create({"titulo": "Só no app", "quando": "2026-10-22T10:00"})
        s = Scheduler()
        s._first = False
        before = notifier.last_id()
        s.check_reminders(db.get_conn(), dt("2026-10-22T10:01"))
        self.assertEqual([n["titulo"] for n in notifier.inbox_since(before)], ["Só no app"])

    def test_caixa_de_avisos_tem_sessao(self):  # revisão 24
        c = appmod.create_app(testing=True).test_client()
        self.assertEqual(c.get("/api/estado").get_json()["sessao"], notifier.SESSION)


class CampoRapidoTests(unittest.TestCase):  # revisão 9
    def setUp(self):
        reset()

    def test_hashtag_vale_mais_que_a_aba(self):
        t = todos.create({"texto": "Ler relatório #projetos", "lista": "hoje"})
        self.assertEqual(t["lista"], "projetos")

    def test_sem_hashtag_usa_a_aba(self):
        t = todos.create({"texto": "Comprar pão", "lista": "semana"})
        self.assertEqual(t["lista"], "semana")


class ImportacaoTests(unittest.TestCase):  # revisão 15 e 23
    def setUp(self):
        reset()
        self.c = appmod.create_app(testing=True).test_client()

    def test_arquivo_incompleto_nao_apaga_nada(self):
        todos.create({"titulo": "Fica"})
        r = self.c.post("/api/importar", json={"app": "Daily Life", "reminders": []})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(todos.list_tab("hoje")), 1)

    def test_valor_perigoso_e_recusado(self):
        data = backup.export_data()
        data["todos"] = [
            {
                "id": 1,
                "lista": "hoje",
                "titulo": "x",
                "prioridade": '"><img src=x>',
                "criado_em": "2026-10-22T10:00",
                "atualizado_em": "2026-10-22T10:00",
            }
        ]
        self.assertEqual(self.c.post("/api/importar", json=data).status_code, 400)

    def test_backup_manual_nao_sobrescreve(self):
        a = backup.make_backup(force=True)
        b = backup.make_backup(force=True, motivo="antes-de-importar")
        self.assertNotEqual(a, b)
        self.assertTrue(os.path.exists(a) and os.path.exists(b))


class SyncRobustaTests(unittest.TestCase):
    def setUp(self):
        reset()
        settings.set("google_sync_v", google_sync.SYNC_VERSION)
        self.store = {"pessoa@example.com": {}}
        self.svc = FakeService(self.store)
        sync(self.svc)
        self.gcal = (
            db.get_conn()
            .execute("SELECT id FROM calendars WHERE google_id='pessoa@example.com'")
            .fetchone()["id"]
        )

    def _http_error(self, status, reason=""):
        class Resp(dict):
            pass

        resp = Resp()
        resp.status = status
        resp.reason = reason
        err = google_sync.HttpError(resp, b"{}") if google_sync.LIBS_OK else Exception()
        if not google_sync.LIBS_OK:
            err.resp = resp
        err.error_details = [{"reason": reason}] if reason else []
        return err

    def test_um_erro_nao_trava_os_outros(self):  # revisão 4
        a = events.create(
            {
                "titulo": "Com problema",
                "calendar_id": self.gcal,
                "inicio": "2026-10-25T09:00",
                "fim": "2026-10-25T10:00",
            }
        )
        events.create(
            {
                "titulo": "Normal",
                "calendar_id": self.gcal,
                "inicio": "2026-10-26T09:00",
                "fim": "2026-10-26T10:00",
            }
        )
        fake = self.svc._ev
        original = fake.insert
        err = self._http_error(400)

        def insert(calendarId, body):
            if body["summary"] == "Com problema":

                class Boom:
                    def execute(self_inner):
                        raise err

                return Boom()
            return original(calendarId, body)

        fake.insert = insert
        old_http = google_sync.HttpError
        google_sync.HttpError = type(err)
        try:
            google_sync.push_pending(self.svc, db.get_conn())
        finally:
            google_sync.HttpError = old_http
        pend = [
            r["titulo"]
            for r in db.rows(db.get_conn().execute("SELECT titulo FROM events WHERE pendente_sync=1"))
        ]
        self.assertEqual(pend, ["Com problema"])
        self.assertEqual(events.get(a["id"])["titulo"], "Com problema")

    def test_patch_zera_o_outro_tipo_de_data(self):  # revisão 4 (causa provável)
        body = google_sync._event_body(
            {
                "titulo": "x",
                "local": "",
                "notas": "",
                "inicio": "2026-11-02T00:00",
                "fim": "2026-11-03T00:00",
                "dia_inteiro": 1,
                "repeticao": "",
                "rrule": None,
                "aviso_min": None,
            },
            patch=True,
        )
        self.assertEqual(body["start"], {"date": "2026-11-02", "dateTime": None, "timeZone": None})

    def test_editado_durante_o_envio_continua_pendente(self):  # revisão 13
        e = events.create(
            {
                "titulo": "v1",
                "calendar_id": self.gcal,
                "inicio": "2026-10-25T09:00",
                "fim": "2026-10-25T10:00",
            }
        )
        row = db.row(db.get_conn().execute("SELECT * FROM events WHERE id=?", (e["id"],)))
        events.update(e["id"], {"titulo": "v2"})  # editado no mesmo minuto, enquanto subia
        db.get_conn().commit()
        google_sync._mark_pushed(
            db.get_conn(), row, "gid-1", {"etag": "e", "updated": "2026-10-22T12:00:00Z"}
        )
        r = (
            db.get_conn()
            .execute("SELECT pendente_sync, google_event_id FROM events WHERE id=?", (e["id"],))
            .fetchone()
        )
        self.assertEqual((r["pendente_sync"], r["google_event_id"]), (1, "gid-1"))


if __name__ == "__main__":
    unittest.main()
