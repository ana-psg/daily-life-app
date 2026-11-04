"""Pasta de dados do programa instalado e migração dos dados: nada pode se perder."""

import os
import sqlite3

import pytest

from dailylife import config
from tools import migrar_dados


def _database(path, rows=3, wal=False):
    conn = sqlite3.connect(path)
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY, titulo TEXT)")
    conn.executemany("INSERT INTO reminders (titulo) VALUES (?)", [(f"r{i}",) for i in range(rows)])
    conn.commit()
    return conn


def test_programa_instalado_guarda_dados_no_appdata():
    path = config.default_data_dir(True, {"APPDATA": r"C:\Users\x\AppData\Roaming"}, r"C:\Programa")
    assert path == os.path.join(r"C:\Users\x\AppData\Roaming", "Daily Life")


def test_rodando_pelo_codigo_continua_na_pasta_data():
    assert config.default_data_dir(False, {"APPDATA": "ignorado"}, "projeto") == os.path.join(
        "projeto", "data"
    )


def test_migracao_leva_o_que_esta_no_wal_e_nao_toca_na_origem(tmp_path):
    source, dest = tmp_path / "data", tmp_path / "destino"
    source.mkdir()
    conn = _database(source / "dailylife.db", wal=True)  # conexão aberta: os dados seguem só no -wal
    (source / "secret.key").write_text("chave")
    (source / "backups").mkdir()
    (source / "backups" / "dailylife-2026-10-30.db").write_text("backup")
    (tmp_path / "credentials.json").write_text("{}")
    before = (source / "dailylife.db").read_bytes()

    counts = migrar_dados.migrate(str(source), str(dest), str(tmp_path / "credentials.json"))

    assert counts["reminders"] == 3
    copy = sqlite3.connect(dest / "dailylife.db")
    assert copy.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 3
    copy.close()
    assert (dest / "secret.key").read_text() == "chave"
    assert (dest / "backups" / "dailylife-2026-10-30.db").exists()
    assert (dest / "credentials.json").exists()
    assert (source / "dailylife.db").read_bytes() == before
    conn.close()


def test_migracao_nunca_sobrescreve_banco_existente(tmp_path):
    source, dest = tmp_path / "data", tmp_path / "destino"
    source.mkdir()
    dest.mkdir()
    _database(source / "dailylife.db").close()
    (dest / "dailylife.db").write_text("já tenho dados")
    with pytest.raises(migrar_dados.MigrationError):
        migrar_dados.migrate(str(source), str(dest))
    assert (dest / "dailylife.db").read_text() == "já tenho dados"


def test_migracao_sem_banco_de_origem_avisa(tmp_path):
    with pytest.raises(migrar_dados.MigrationError):
        migrar_dados.migrate(str(tmp_path / "nada"), str(tmp_path / "destino"))
    assert not (tmp_path / "destino").exists()
