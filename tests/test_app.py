"""Testes do Daily Life (só biblioteca padrão).

Rodar: python -m unittest discover -s tests -v
"""

import atexit
import os
import shutil
import sys
import tempfile
import unittest
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="dailylife-test-")
os.environ["DAILYLIFE_DATA"] = TMP

from dailylife import (
    config,
    db,
)

config.DB_PATH = os.path.join(TMP, "test.db")
config.BACKUP_DIR = os.path.join(TMP, "backups")

from dailylife.core import (
    backup,
    events,
    recurrence,
    reminders,
    settings,
    todos,
)
from dailylife.desktop import notifier
from dailylife.desktop.scheduler import Scheduler
from dailylife.web import app as appmod


def reset():
    db.close_conn()
    if os.path.exists(config.DB_PATH):
        os.remove(config.DB_PATH)
    for ext in ("-wal", "-shm"):
        if os.path.exists(config.DB_PATH + ext):
            os.remove(config.DB_PATH + ext)
    db.init_db()


def dt(s):
    return config.parse_iso(s)


class RecurrenceTests(unittest.TestCase):
    def test_dias_uteis_pula_fim_de_semana(self):
        s, f = dt("2026-10-19T09:00"), dt("2026-10-19T09:30")  # segunda
        occ = recurrence.event_occurrences(s, f, "dias_uteis", dt("2026-10-19T00:00"), dt("2026-10-26T00:00"))
        self.assertEqual(len(occ), 5)
        self.assertTrue(all(o[0].weekday() < 5 for o in occ))

    def test_mensal_pula_mes_sem_dia_31(self):
        s, f = dt("2026-01-31T10:00"), dt("2026-01-31T11:00")
        occ = recurrence.event_occurrences(s, f, "mensal", dt("2026-01-01T00:00"), dt("2026-06-01T00:00"))
        self.assertEqual([o[0].month for o in occ], [1, 3, 5])

    def test_semanal_salta_para_o_periodo(self):
        s, f = dt("2025-01-06T08:00"), dt("2025-01-06T09:00")
        occ = recurrence.event_occurrences(s, f, "semanal", dt("2026-10-19T00:00"), dt("2026-10-26T00:00"))
        self.assertEqual(len(occ), 1)
        self.assertEqual(occ[0][0].weekday(), 0)

    def test_regras_de_lembrete(self):
        self.assertEqual(recurrence.parse_reminder_rule("horas:2"), ("horas", 2))
        self.assertEqual(recurrence.parse_reminder_rule("dias:0,3"), ("dias", {0, 3}))
        with self.assertRaises(ValueError):
            recurrence.parse_reminder_rule("dias:9")
        self.assertEqual(recurrence.describe_reminder_rule("dias:0,1,2,3,4"), "Dias úteis")


class TodoTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_campo_rapido(self):
        t = todos.create({"texto": "Ligar pro banco amanhã !alta"})
        self.assertEqual(t["titulo"], "Ligar pro banco")
        self.assertEqual(t["prioridade"], "alta")
        self.assertEqual(t["lista"], "semana")
        self.assertIsNotNone(t["vencimento"])

    def test_hoje_e_feitas(self):
        a = todos.create({"titulo": "A", "lista": "hoje"})
        todos.create({"titulo": "B", "lista": "projetos"})
        todos.update(a["id"], {"feito": True})
        hoje = todos.list_tab("hoje")
        self.assertEqual([t["titulo"] for t in hoje], ["A"])
        self.assertTrue(hoje[0]["feito"])
        self.assertEqual(len(todos.list_tab("feitas")), 1)
        self.assertEqual(todos.counts()["projetos"], 1)

    def test_vencida_aparece_em_hoje(self):
        ontem = (config.now() - timedelta(days=1)).date().isoformat()
        todos.create({"titulo": "Atrasada", "lista": "semana", "vencimento": ontem})
        hoje = todos.list_tab("hoje")
        self.assertEqual(len(hoje), 1)
        self.assertTrue(hoje[0]["atrasada"])

    def test_subtarefas_e_exclusao(self):
        p = todos.create({"titulo": "Projeto", "lista": "projetos"})
        todos.create({"titulo": "Etapa", "parent_id": p["id"]})
        self.assertEqual(len(todos.get(p["id"])["subtarefas"]), 1)
        todos.delete(p["id"])
        self.assertEqual(db.get_conn().execute("SELECT COUNT(*) FROM todos").fetchone()[0], 0)

    def test_reordenar(self):
        a = todos.create({"titulo": "A"})
        b = todos.create({"titulo": "B"})
        todos.reorder([b["id"], a["id"]])
        self.assertEqual([t["titulo"] for t in todos.list_tab("hoje")], ["B", "A"])


class ReminderTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_recorrente_conta_hoje_e_volta_amanha(self):
        now = dt("2026-10-22T09:00")
        r = reminders.create({"titulo": "Vitamina", "quando": "2026-10-22T08:00", "repeticao": "diaria"})
        r = reminders.resolve(r["id"], now=now)
        self.assertTrue(r["feito_hoje"])
        self.assertEqual(r["quando"], "2026-10-23T08:00")
        hoje = reminders.list_filtered("hoje", now=now)
        self.assertEqual(hoje[0]["estado"], "feito")
        amanha = dt("2026-10-23T07:00")
        r2 = reminders.get(r["id"], now=amanha)
        self.assertEqual(r2["estado"], "pendente")
        self.assertFalse(r2["feito_hoje"])

    def test_desfazer_recorrente(self):
        now = dt("2026-10-22T09:00")
        r = reminders.create({"titulo": "X", "quando": "2026-10-22T08:00", "repeticao": "diaria"})
        reminders.resolve(r["id"], now=now)
        r = reminders.undo(r["id"], now=now)
        self.assertEqual(r["quando"], "2026-10-22T08:00")
        self.assertFalse(r["feito_hoje"])

    def test_dias_da_semana(self):
        # quinta 22/10; dias seg (0) e qui (3)
        now = dt("2026-10-22T20:00")
        r = reminders.create({"titulo": "Plantas", "quando": "2026-10-22T19:00", "repeticao": "dias:0,3"})
        r = reminders.resolve(r["id"], now=now)
        self.assertEqual(r["quando"], "2026-10-26T19:00")

    def test_a_cada_horas_avanca_ao_avisar_e_volta_amanha(self):
        now = dt("2026-10-22T08:01")
        r = reminders.create({"titulo": "Água", "quando": "2026-10-22T08:00", "repeticao": "horas:2"})
        due = reminders.due(now=now)
        self.assertEqual(len(due), 1)
        reminders.mark_notified(due[0], now=now)
        self.assertEqual(reminders.get(r["id"])["quando"], "2026-10-22T10:00")
        self.assertEqual(reminders.due(now=now), [])
        r = reminders.resolve(r["id"], now=dt("2026-10-22T15:00"))
        self.assertEqual(r["quando"], "2026-10-23T08:00")

    def test_rollover_de_recorrente_esquecido(self):
        reminders.create({"titulo": "Remédio", "quando": "2026-10-20T08:00", "repeticao": "diaria"})
        now = dt("2026-10-22T07:00")
        items = reminders.list_filtered("todos", now=now)
        self.assertEqual(items[0]["quando"], "2026-10-22T08:00")

    def test_unico_e_adiar(self):
        now = dt("2026-10-22T12:05")
        r = reminders.create({"titulo": "Conta de luz", "quando": "2026-10-22T12:00"})
        self.assertTrue(reminders.get(r["id"], now=now)["atrasado"])
        r = reminders.snooze(r["id"], 60, now=now)
        self.assertEqual(r["quando"], "2026-10-22T13:05")
        r = reminders.resolve(r["id"], now=now)
        self.assertTrue(r["concluido"])

    def test_validacao(self):
        with self.assertRaises(Exception):
            reminders.create({"titulo": "", "quando": "2026-10-22T12:00"})
        with self.assertRaises(Exception):
            reminders.create({"titulo": "X", "quando": "2026-10-22T12:00", "repeticao": "horas:40"})


class EventTests(unittest.TestCase):
    def setUp(self):
        reset()
        self.cal = db.get_conn().execute("SELECT id FROM calendars WHERE nome='Trabalho'").fetchone()["id"]

    def test_criar_listar_e_conflito(self):
        events.create(
            {"titulo": "A", "calendar_id": self.cal, "inicio": "2026-10-22T10:00", "fim": "2026-10-22T11:00"}
        )
        b = events.create(
            {"titulo": "B", "calendar_id": self.cal, "inicio": "2026-10-22T10:30", "fim": "2026-10-22T11:30"}
        )
        self.assertEqual([c["titulo"] for c in b["conflitos"]], ["A"])
        lst = events.list_range(dt("2026-10-22T00:00"), dt("2026-10-23T00:00"))
        self.assertEqual(len(lst), 2)

    def test_fim_antes_do_inicio(self):
        with self.assertRaises(Exception):
            events.create(
                {
                    "titulo": "X",
                    "calendar_id": self.cal,
                    "inicio": "2026-10-22T10:00",
                    "fim": "2026-10-22T09:00",
                }
            )

    def test_dia_inteiro(self):
        e = events.create(
            {
                "titulo": "Feriado",
                "calendar_id": self.cal,
                "dia_inteiro": True,
                "inicio": "2026-11-02T00:00",
                "fim": "2026-11-02T00:00",
            }
        )
        self.assertEqual(e["fim"], "2026-11-03T00:00")

    def test_calendario_escondido_some(self):
        events.create(
            {"titulo": "A", "calendar_id": self.cal, "inicio": "2026-10-22T10:00", "fim": "2026-10-22T11:00"}
        )
        db.get_conn().execute("UPDATE calendars SET visivel=0 WHERE id=?", (self.cal,))
        db.get_conn().commit()
        self.assertEqual(events.list_range(dt("2026-10-22T00:00"), dt("2026-10-23T00:00")), [])

    def test_aviso_do_compromisso(self):
        e = events.create(
            {
                "titulo": "Reunião",
                "calendar_id": self.cal,
                "inicio": "2026-10-22T10:00",
                "fim": "2026-10-22T11:00",
                "aviso_min": 15,
            }
        )
        self.assertEqual(events.alerts_due(now=dt("2026-10-22T09:40")), [])
        due = events.alerts_due(now=dt("2026-10-22T09:46"))
        self.assertEqual(len(due), 1)
        events.mark_alerted(due[0])
        self.assertEqual(events.alerts_due(now=dt("2026-10-22T09:50")), [])
        self.assertEqual(e["aviso_min"], 15)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_resumo_quando_pc_estava_desligado(self):
        reminders.create({"titulo": "A", "quando": "2026-10-20T08:00"})
        reminders.create({"titulo": "B", "quando": "2026-10-21T08:00"})
        before = notifier.last_id()
        s = Scheduler()
        s.check_reminders(db.get_conn(), dt("2026-10-22T09:00"))
        notes = notifier.inbox_since(before)
        self.assertEqual(len(notes), 1)
        self.assertIn("2 lembretes", notes[0]["titulo"])

    def test_nao_perturbe(self):
        settings.update({"nao_perturbe": True, "np_inicio": "22:00", "np_fim": "07:00"})
        self.assertTrue(settings.in_quiet_hours(dt("2026-10-22T23:30")))
        self.assertTrue(settings.in_quiet_hours(dt("2026-10-22T06:00")))
        self.assertFalse(settings.in_quiet_hours(dt("2026-10-22T12:00")))


class ApiTests(unittest.TestCase):
    def setUp(self):
        reset()
        self.app = appmod.create_app(testing=True)
        self.c = self.app.test_client()

    def test_telas_respondem(self):
        for url in (
            "/",
            "/widget",
            "/calendario",
            "/todo",
            "/lembretes",
            "/config",
            "/entrar",
            "/api/painel",
            "/api/config",
            "/manifest.webmanifest",
        ):
            self.assertEqual(self.c.get(url).status_code, 200, url)

    def test_erro_de_validacao_vira_400(self):
        r = self.c.post("/api/todos", json={"titulo": ""})
        self.assertEqual(r.status_code, 400)
        self.assertIn("obrigatório", r.get_json()["erro"])

    def test_fluxo_tarefa(self):
        t = self.c.post("/api/todos", json={"texto": "Comprar pão"}).get_json()
        self.c.patch(f"/api/todos/{t['id']}", json={"feito": True})
        p = self.c.get("/api/painel").get_json()
        self.assertEqual(p["progresso"]["feitos"], 1)

    def test_acesso_pelo_celular_exige_senha(self):
        remote = {"REMOTE_ADDR": "192.168.0.20"}
        self.assertEqual(self.c.get("/", environ_base=remote).status_code, 403)
        settings.set("acesso_rede", True)
        self.assertEqual(self.c.get("/", environ_base=remote).status_code, 403)  # sem senha definida
        settings.set_password("abc1234")
        r = self.c.get("/", environ_base=remote)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.c.get("/api/painel", environ_base=remote).status_code, 401)
        r = self.c.post("/entrar", data={"senha": "errada0"}, environ_base=remote)
        self.assertIn("Senha incorreta", r.get_data(as_text=True))
        self.c.post("/entrar", data={"senha": "abc1234"}, environ_base=remote)
        self.assertEqual(self.c.get("/api/painel", environ_base=remote).status_code, 200)
        # opções do computador ficam bloqueadas pela rede
        self.assertEqual(
            self.c.post("/api/config/senha", json={"senha": "nova9999"}, environ_base=remote).status_code, 403
        )
        self.assertEqual(
            self.c.patch("/api/config", json={"acesso_rede": False}, environ_base=remote).status_code, 400
        )

    def test_exportar_importar(self):
        self.c.post("/api/todos", json={"titulo": "Guardar isto"})
        data = self.c.get("/api/exportar").get_json()
        self.c.post("/api/todos", json={"titulo": "Vai sumir"})
        r = self.c.post("/api/importar", json=data)
        self.assertEqual(r.status_code, 200)
        titulos = [t["titulo"] for t in self.c.get("/api/todos?aba=hoje").get_json()["itens"]]
        self.assertEqual(titulos, ["Guardar isto"])
        self.assertTrue(backup.list_backups())

    def test_config_valida(self):
        self.assertEqual(self.c.patch("/api/config", json={"tema": "roxo"}).status_code, 400)
        r = self.c.patch("/api/config", json={"tema": "escuro", "np_inicio": "21:30"})
        self.assertEqual(r.get_json()["tema"], "escuro")

    def test_janela_fora_do_desktop(self):
        self.assertEqual(self.c.post("/api/janela/widget").status_code, 400)


@atexit.register
def _cleanup():
    db.close_conn()
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
