"""Casos de borda: meia-noite, fim de mês, ano bissexto, sem internet, muitos dados.

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

import test_app  # noqa: F401
from test_app import dt, reset
from test_fase1 import cal_id, titles_on

from dailylife import (
    config,
    db,
)
from dailylife.core import dashboard, events, reminders, todos
from dailylife.sync import google as google_sync


class MeiaNoiteTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_evento_que_passa_da_meia_noite_aparece_nos_dois_dias(self):
        events.create(
            {
                "titulo": "Festa",
                "calendar_id": cal_id(),
                "inicio": "2026-10-31T22:00",
                "fim": "2026-11-01T02:00",
            }
        )
        self.assertEqual([t for t, _ in titles_on("2026-10-31")], ["Festa"])
        self.assertEqual([t for t, _ in titles_on("2026-11-01")], ["Festa"])

    def test_serie_diaria_que_passa_da_meia_noite(self):
        events.create(
            {
                "titulo": "Plantão",
                "calendar_id": cal_id(),
                "inicio": "2026-10-19T23:00",
                "fim": "2026-10-20T01:00",
                "repeticao": "diaria",
            }
        )
        self.assertEqual(len(titles_on("2026-10-21")), 2)  # o de 20→21 e o de 21→22

    def test_lembrete_diario_as_23h59_volta_no_dia_seguinte(self):
        r = reminders.create({"titulo": "Diário", "quando": "2026-10-22T23:59", "repeticao": "diaria"})
        r = reminders.resolve(r["id"], now=dt("2026-10-22T23:59"))
        self.assertEqual(r["quando"], "2026-10-23T23:59")


class FimDeMesTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_lembrete_mensal_dia_31_pula_meses_curtos(self):
        r = reminders.create({"titulo": "Dia 31", "quando": "2026-10-31T09:00", "repeticao": "mensal"})
        r = reminders.resolve(r["id"], now=dt("2026-10-31T09:05"))
        self.assertEqual(r["quando"], "2026-12-31T09:00")

    def test_29_de_fevereiro_em_ano_bissexto(self):
        events.create(
            {
                "titulo": "Bissexto",
                "calendar_id": cal_id(),
                "inicio": "2028-02-29T10:00",
                "fim": "2028-02-29T11:00",
                "repeticao": "mensal",
            }
        )
        self.assertEqual([t for t, _ in titles_on("2028-03-29")], ["Bissexto"])
        self.assertEqual(titles_on("2028-02-28"), [])

    def test_virada_de_ano_na_semana(self):
        p = dashboard.overview(now=dt("2026-12-30T10:00"))
        self.assertEqual([d["num"] for d in p["semana"]["dias"]], [28, 29, 30, 31, 1, 2, 3])
        self.assertIn("dez", p["semana"]["titulo"])


class SemInternetTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_queda_de_conexao_nao_derruba_e_avisa(self):
        class Offline:
            def calendarList(self):
                raise OSError("sem rede")

            def events(self):
                raise OSError("sem rede")

        old = (google_sync.LIBS_OK, google_sync.is_connected, google_sync._service)
        google_sync.LIBS_OK = True
        google_sync.is_connected = lambda: True
        google_sync._service = lambda: Offline()
        try:
            self.assertFalse(google_sync.sync_all())
        finally:
            google_sync.LIBS_OK, google_sync.is_connected, google_sync._service = old
        self.assertIn("Sem internet", google_sync.STATE["erro"])
        self.assertFalse(google_sync.STATE["sincronizando"])


class VolumeTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_muitos_dados_continua_rapido(self):
        conn = db.get_conn()
        stamp = config.iso(config.now())
        cal = cal_id()
        start = dt("2026-01-01T08:00")
        conn.executemany(
            "INSERT INTO events (calendar_id, titulo, inicio, fim, criado_em, atualizado_em) VALUES (?,?,?,?,?,?)",
            [
                (
                    cal,
                    f"Evento {i}",
                    config.iso(start + timedelta(hours=7 * i)),
                    config.iso(start + timedelta(hours=7 * i + 1)),
                    stamp,
                    stamp,
                )
                for i in range(2000)
            ],
        )
        for i in range(30):
            events.create(
                {
                    "titulo": f"Série {i}",
                    "calendar_id": cal,
                    "inicio": "2026-01-05T07:00",
                    "fim": "2026-01-05T07:30",
                    "repeticao": "dias_uteis",
                }
            )
        for i in range(300):
            todos.create({"titulo": f"Tarefa {i}", "lista": "semana"})
        conn.commit()
        t0 = time.perf_counter()
        dashboard.overview(now=dt("2026-06-10T09:00"))
        events.list_range(dt("2026-06-01T00:00"), dt("2026-07-06T00:00"))
        self.assertLess(time.perf_counter() - t0, 2.0)

    def test_texto_longo_e_caracteres_especiais(self):
        t = todos.create({"titulo": "Ação <b>&</b> \"aspas\" 'simples' 😀 " + "x" * 250})
        self.assertIn("<b>", t["titulo"])  # guardado como texto; as telas escapam ao mostrar
        with self.assertRaises(Exception):
            todos.create({"titulo": "x" * 301})


if __name__ == "__main__":
    unittest.main()
