"""Testes da Fase 2 e 3 da versão 2: banco com versão, nome Daily Life e dados antigos.

Rodar: python -m unittest discover -s tests -v
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_app  # noqa: F401  (prepara o banco temporário)
from test_app import reset

from dailylife import db
from dailylife.core import backup, todos
from dailylife.web import app as appmod

V1_SCHEMA = os.path.join(ROOT, "tests", "data", "schema_v1.sql")
STAMP = "2026-10-22T10:00"


def make_v1_db(path: str) -> None:
    """Um banco como o da versão 1, com uma tarefa em Semana e uma subtarefa."""
    conn = sqlite3.connect(path)
    with open(V1_SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.executemany(
        "INSERT INTO todo_lists (id, chave, nome, ordem) VALUES (?, ?, ?, ?)",
        [(1, "hoje", "Hoje", 0), (2, "semana", "Semana", 1), (3, "projetos", "Projetos", 2)],
    )
    conn.execute(
        "INSERT INTO todos (id, list_id, titulo, criado_em, atualizado_em) VALUES (10, 2, 'Mercado', ?, ?)",
        (STAMP, STAMP),
    )
    conn.execute(
        "INSERT INTO todos (id, list_id, parent_id, titulo, feito, criado_em, atualizado_em) "
        "VALUES (11, 2, 10, 'Leite', 1, ?, ?)",
        (STAMP, STAMP),
    )
    conn.execute(
        "INSERT INTO reminders (titulo, quando, repeticao, adiado_ate, criado_em, atualizado_em) "
        "VALUES ('Água', '2026-10-22T09:00', 'mensal', NULL, ?, ?)",
        (STAMP, STAMP),
    )
    conn.execute(
        "INSERT INTO calendars (nome, cor, origem, criado_em, atualizado_em) VALUES ('Pessoal', '#36B072', 'local', ?, ?)",
        (STAMP, STAMP),
    )
    conn.commit()
    conn.close()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="dailylife-mig-")
        self.path = os.path.join(self.dir, "v1.db")
        make_v1_db(self.path)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_banco_v1_vira_o_atual_sem_perder_nada(self):
        conn = db.init_db(db.connect(self.path))
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], len(db.MIGRATIONS))
        self.assertIsNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name='todo_lists'").fetchone())
        got = {r["id"]: (r["lista"], r["parent_id"], r["feito"]) for r in conn.execute("SELECT * FROM todos")}
        self.assertEqual(got, {10: ("semana", None, 0), 11: ("semana", 10, 1)})
        rem = conn.execute("SELECT * FROM reminders").fetchone()
        self.assertEqual(rem["data_base"], "2026-10-22")
        self.assertNotIn("adiado_ate", rem.keys())
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        conn.close()

    def test_banco_migrado_fica_igual_ao_banco_novo(self):
        def shape(conn):
            out = {}
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','index') "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ):
                out[name] = sorted(
                    (c[1], c[2], c[3], c[4]) for c in conn.execute(f"PRAGMA table_info({name})")
                )
            return out

        old = db.init_db(db.connect(self.path))
        new = db.init_db(db.connect(os.path.join(self.dir, "novo.db")))
        self.assertEqual(shape(old), shape(new))
        old.close()
        new.close()

    def test_apagar_tarefa_apaga_subtarefas_depois_da_migracao(self):
        conn = db.init_db(db.connect(self.path))
        todos.delete(10, conn)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM todos").fetchone()[0], 0)
        conn.close()

    def test_migracao_com_erro_nao_muda_nada(self):
        def broken(conn):
            conn.execute("ALTER TABLE todos ADD COLUMN lixo TEXT")
            raise RuntimeError("falhou no meio")

        with mock.patch.object(db, "MIGRATIONS", [*db.MIGRATIONS, broken]):
            with self.assertRaises(RuntimeError):
                db.init_db(db.connect(self.path))
        conn = sqlite3.connect(self.path)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
        cols = {c[1] for c in conn.execute("PRAGMA table_info(todos)")}
        self.assertIn("list_id", cols)
        self.assertNotIn("lixo", cols)
        conn.close()


class TodoListTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_lista_invalida_e_recusada(self):
        with self.assertRaises(Exception):
            todos.create({"titulo": "x", "lista": "outra"})

    def test_mudar_lista_leva_as_subtarefas(self):
        t = todos.create({"titulo": "Casa", "lista": "hoje"})
        todos.create({"titulo": "Varrer", "parent_id": t["id"]})
        todos.update(t["id"], {"lista": "projetos"})
        sub = todos.get(t["id"])["subtarefas"][0]
        self.assertEqual(sub["lista"], "projetos")


class OldExportTests(unittest.TestCase):
    def setUp(self):
        reset()
        self.c = appmod.create_app().test_client()

    def test_exportacao_antiga_ainda_importa(self):
        data = backup.export_data()
        data["app"] = "Daily Life"
        data["versao"] = 1
        data["todo_lists"] = [{"id": 7, "chave": "projetos", "nome": "Projetos", "ordem": 2}]
        data["todos"] = [
            {
                "id": 1,
                "list_id": 7,
                "titulo": "Antiga",
                "prioridade": "alta",
                "criado_em": STAMP,
                "atualizado_em": STAMP,
            }
        ]
        data["reminders"] = [
            {
                "id": 1,
                "titulo": "R",
                "quando": "2026-10-22T09:00",
                "cor": "amarelo",
                "adiado_ate": None,
                "criado_em": STAMP,
                "atualizado_em": STAMP,
            }
        ]
        r = self.c.post("/api/importar", json=data)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual([t["titulo"] for t in todos.list_tab("projetos")], ["Antiga"])

    def test_exportacao_nova_usa_o_nome_novo(self):
        data = backup.export_data()
        self.assertEqual(data["app"], "Daily Life")
        self.assertNotIn("todo_lists", data)

    def test_arquivo_de_outro_app_e_recusado(self):
        data = backup.export_data()
        data["app"] = "OutroApp"
        self.assertEqual(self.c.post("/api/importar", json=data).status_code, 400)


class StartupNameTests(unittest.TestCase):
    def test_atualiza_o_caminho_da_entrada(self):
        from dailylife.desktop import startup

        values = {"DailyLife": "antigo"}

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def query(_key, name):
            if name not in values:
                raise FileNotFoundError(name)
            return values[name], 1

        fake = mock.Mock(HKEY_CURRENT_USER=0, KEY_READ=1, KEY_SET_VALUE=2, REG_SZ=1)
        fake.OpenKey.side_effect = lambda *a: Key()
        fake.QueryValueEx.side_effect = query
        fake.DeleteValue.side_effect = lambda _k, name: values.pop(name)
        fake.SetValueEx.side_effect = lambda _k, name, _r, _t, cmd: values.__setitem__(name, cmd)
        with mock.patch.object(startup, "winreg", fake):
            startup.refresh()
        self.assertEqual(list(values), ["DailyLife"])
        self.assertIn("main.py", values["DailyLife"])


if __name__ == "__main__":
    unittest.main()
