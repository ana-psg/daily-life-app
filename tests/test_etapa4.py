"""Instalador: o app começa sem dados de ninguém, e nomes e versões continuam consistentes."""

import os
import re
import sqlite3
from datetime import datetime

import test_app
from test_app import reset

from dailylife import db
from dailylife.core import dashboard, settings
from tools import verificar_pacote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8-sig") as f:
        return f.read()


def test_app_novo_nao_traz_nome_de_ninguem():
    reset()
    assert settings.get("nome") == ""
    assert dashboard.greeting(datetime(2026, 11, 2, 9, 0), "") == "Bom dia"
    assert dashboard.overview()["greeting"] in ("Bom dia", "Boa tarde", "Boa noite")


def test_saudacao_com_nome_continua_igual():
    assert dashboard.greeting(datetime(2026, 11, 2, 9, 0), "Maria") == "Bom dia, Maria"


def test_apagar_o_nome_vale():
    reset()
    settings.update({"nome": "Maria"})
    assert settings.update({"nome": ""})["nome"] == ""


def test_migracao_nao_coloca_nome_padrao(tmp_path):
    path = tmp_path / "antigo.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)  # banco novo, na versão atual
    conn.execute("DELETE FROM settings WHERE chave='nome'")
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    db.init_db(conn)
    assert conn.execute("SELECT valor FROM settings WHERE chave='nome'").fetchone() is None
    conn.close()


def test_nome_escolhido_nao_e_trocado_pela_migracao(tmp_path):
    path = tmp_path / "antigo.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    conn.execute("""INSERT OR REPLACE INTO settings (chave, valor) VALUES ('nome', '"Maria"')""")
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    db.init_db(conn)
    assert conn.execute("SELECT valor FROM settings WHERE chave='nome'").fetchone()["valor"] == '"Maria"'
    conn.close()


def test_copia_de_teste_nao_troca_a_inicializacao_do_windows(monkeypatch):
    # Regressão: abrir um .exe de teste apontou "abrir com o Windows" para ele, e o app abriria vazio
    from dailylife.desktop import startup

    calls = []
    monkeypatch.setattr(startup, "is_enabled", lambda: True)
    monkeypatch.setattr(startup, "set_enabled", calls.append)
    monkeypatch.setenv("DAILYLIFE_DATA", "qualquer")
    startup.refresh()
    monkeypatch.delenv("DAILYLIFE_DATA")
    monkeypatch.setenv("DAILYLIFE_PORT", "5999")
    startup.refresh()
    assert calls == []
    monkeypatch.delenv("DAILYLIFE_PORT")
    startup.refresh()
    assert calls == [True]


def test_versao_e_a_mesma_em_todo_lugar():
    version = re.search(r'^version = "(.+)"', _read("pyproject.toml"), re.M).group(1)
    assert f'#define AppVersion "{version}"' in _read("packaging", "DailyLife.iss")
    assert f"StringStruct('ProductVersion', '{version}')" in _read("packaging", "version_info.txt")


def test_pacote_com_banco_ou_token_e_recusado(tmp_path):
    (tmp_path / "dailylife.db").write_text("x")
    (tmp_path / "token.json").write_text("x")
    (tmp_path / "credentials.json").write_text("x")
    (tmp_path / "secret.key").write_text("x")
    (tmp_path / "push_key.pem").write_text("x")
    assert len(verificar_pacote.bad_names(str(tmp_path))) == 5


def test_certificados_publicos_de_bibliotecas_sao_aceitos(tmp_path):
    (tmp_path / "certifi").mkdir()
    (tmp_path / "certifi" / "cacert.pem").write_text("x")
    assert verificar_pacote.bad_names(str(tmp_path)) == []


def test_texto_pessoal_dentro_de_arquivo_e_encontrado(tmp_path):
    (tmp_path / "pagina.html").write_text("escrito por Pessoa.Teste@exemplo.com")
    found = verificar_pacote.bad_contents(str(tmp_path), ["pessoa.teste@exemplo.com"])
    assert len(found) == 1


def test_texto_pessoal_em_modulo_compilado_e_encontrado():
    # Regressão: a verificação olhava só o repr do módulo, que não mostra os textos dentro dele
    code = compile('def f():\n    return "pessoa.teste@exemplo.com"\n', "x.py", "exec")
    assert b"pessoa.teste@exemplo.com" in verificar_pacote.code_text(code)


def test_codigo_nao_manda_rodar_bat_que_nao_existe_mais():
    for folder, _, files in os.walk(os.path.join(ROOT, "dailylife")):
        for name in files:
            if name.endswith((".py", ".js", ".html")):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    assert ".bat" not in f.read(), name


assert test_app  # o import prepara o banco temporário
