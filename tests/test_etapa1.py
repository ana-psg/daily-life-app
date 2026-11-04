"""Bugs corrigidos na refatoração v2: cada teste aqui falhava antes da correção."""

import threading
from datetime import datetime
from unittest import mock

import pytest
import test_app
from test_app import reset

from dailylife import config, push, tailscale
from dailylife.core import ValidationError, backup, reminders, settings, todos
from dailylife.desktop import notifier
from dailylife.desktop.scheduler import Scheduler
from dailylife.sync import google as google_sync
from dailylife.web import app as appmod

WRONG_TYPES = [123, 1.5, True, [1], {"a": 1}]
EVENT = {"titulo": "a", "inicio": "2026-11-02T10:00", "fim": "2026-11-02T11:00", "calendar_id": 1}
REMINDER = {"titulo": "a", "quando": "2026-11-02T10:00"}


@pytest.fixture
def client():
    reset()
    return appmod.create_app().test_client()


def _export_with(**changes):
    data = backup.export_data()
    data.update(changes)
    return data


# ---------- importar um arquivo ruim não pode travar o app ----------
@pytest.mark.parametrize(
    "bad",
    [
        {"events": [{"titulo": "x", "inicio": "ontem", "fim": "2026-11-02T11:00", "calendar_id": 1}]},
        {"events": [{"titulo": "x", "inicio": "2026-11-02T10:00", "fim": None, "calendar_id": 1}]},
        {"reminders": [{"titulo": "x", "quando": "amanhã", "cor": "azul"}]},
        {"settings": [{"chave": "tema", "valor": "isto não é json"}]},
    ],
)
def test_importar_dado_invalido_e_recusado_sem_apagar_nada(bad):
    reset()
    keep = reminders.create({"titulo": "Fica", "quando": "2026-11-02T10:00"})
    with pytest.raises(ValueError):
        backup.import_data(_export_with(**bad))
    assert reminders.get(keep["id"])["titulo"] == "Fica"


def test_importar_com_campo_obrigatorio_faltando_responde_400(client):
    keep = reminders.create({"titulo": "Fica", "quando": "2026-11-02T10:00"})
    bad = _export_with(
        reminders=[
            {"id": 1, "cor": "azul", "quando": "2026-11-02T10:00"}
        ]  # sem título e sem datas de criação
    )
    assert client.post("/api/importar", json=bad).status_code == 400
    assert reminders.get(keep["id"])["titulo"] == "Fica"


def test_dois_backups_manuais_no_mesmo_segundo_nao_se_sobrescrevem():
    reset()
    fixed = datetime(2026, 11, 2, 10, 0, 0, tzinfo=config.TZ)
    with mock.patch.object(backup, "datetime", wraps=datetime) as fake:
        fake.now.return_value = fixed
        first = backup.make_backup(force=True, motivo="teste")
        second = backup.make_backup(force=True, motivo="teste")
    assert first != second


# ---------- configurações ----------
def test_configuracao_invalida_nao_grava_as_outras():
    reset()
    with pytest.raises(ValidationError):
        settings.update({"tema": "escuro", "sync_min": 7})
    assert settings.get("tema") == "claro"


# ---------- Tailscale ----------
def test_desligar_nunca_derruba_o_serve_de_outros_apps():
    calls = []

    def run(*args, **_kwargs):
        calls.append(args)
        return 1, "falhou"

    with mock.patch.object(tailscale, "_run", run):
        result = tailscale.unpublish()
    assert result["ok"] is False
    assert all("reset" not in c for c in calls)


def test_porta_que_comeca_igual_nao_conta_como_publicada():
    other = {"Web": {"x:443": {"Handlers": {"/": {"Proxy": f"http://127.0.0.1:{config.PORT}0"}}}}}
    assert tailscale._serving(other) is False


# ---------- sessão ----------
def test_cookie_de_sessao_tem_nome_proprio_do_app(client):
    # O cookie vale para o endereço inteiro, em qualquer porta: com o nome padrão, um app derruba o login do outro
    assert client.application.config["SESSION_COOKIE_NAME"] == "dailylife_session"


# ---------- Google ----------
def test_login_do_google_abandonado_nao_trava_o_botao_conectar():
    flow = mock.Mock()
    flow.run_local_server.side_effect = AttributeError("'NoneType' object has no attribute 'replace'")
    with (
        mock.patch.object(google_sync, "LIBS_OK", True),
        mock.patch.object(google_sync, "has_credentials", return_value=True),
        mock.patch.object(google_sync, "InstalledAppFlow") as installed,
    ):
        installed.from_client_secrets_file.return_value = flow
        with pytest.raises(RuntimeError, match="não foi concluído"):
            google_sync.connect()
    assert flow.run_local_server.call_args.kwargs["timeout_seconds"] > 0
    assert google_sync.STATE["conectando"] is False


# ---------- agendador ----------
def test_agendador_nao_esconde_metodo_interno_da_thread():
    # Até o Python 3.12 a Thread usa self._stop(): um atributo com esse nome quebra o join()
    assert not isinstance(getattr(Scheduler(), "_stop", None), threading.Event)


# ---------- lembretes e tarefas ----------
def test_adiar_lembrete_recorrente_ja_marcado_volta_como_pendente():
    reset()
    r = reminders.create({"titulo": "Água", "quando": "2026-10-22T08:00", "repeticao": "diaria"})
    now = test_app.dt("2026-10-22T09:00")
    reminders.resolve(r["id"], now=now)
    r = reminders.snooze(r["id"], 60, now=now)
    assert r["estado"] == "pendente"
    assert r["concluido"] is False


def test_subtarefa_com_parent_id_vazio_vira_tarefa_normal():
    reset()
    assert todos.create({"titulo": "x", "parent_id": ""})["parent_id"] is None


def test_ordem_com_lista_invalida_e_recusada():
    reset()
    with pytest.raises(ValidationError):
        todos.reorder(123)


# ---------- avisos ----------
def test_inscricao_de_aviso_que_nao_e_objeto_e_recusada():
    reset()
    for bad in ("abc", 123, ["x"]):
        with pytest.raises(ValidationError):
            push.subscribe(bad)
    with pytest.raises(ValidationError):
        push.subscribe({"endpoint": "https://x", "keys": "abc"})


def test_testes_nao_disparam_aviso_real_do_windows():
    assert notifier._toast is test_app.fake_toast


# ---------- valores de tipo errado respondem 400, nunca 500 ----------
@pytest.mark.parametrize("value", WRONG_TYPES)
@pytest.mark.parametrize(
    ("method", "path", "base", "field"),
    [
        ("POST", "/api/todos", {"titulo": "a"}, "titulo"),
        ("POST", "/api/todos", {"titulo": "a"}, "notas"),
        ("POST", "/api/lembretes", REMINDER, "titulo"),
        ("POST", "/api/lembretes", REMINDER, "descricao"),
        ("POST", "/api/lembretes", REMINDER, "quando"),
        ("POST", "/api/lembretes", REMINDER, "repeticao"),
        ("POST", "/api/eventos", EVENT, "titulo"),
        ("POST", "/api/eventos", EVENT, "inicio"),
        ("POST", "/api/eventos", EVENT, "fim"),
        ("POST", "/api/eventos", EVENT, "local"),
        ("POST", "/api/eventos", EVENT, "notas"),
        ("POST", "/api/calendarios", {"nome": "a"}, "nome"),
        ("POST", "/api/calendarios", {"nome": "a"}, "cor"),
        ("POST", "/api/config/senha", {"senha": "abcdef"}, "senha"),
    ],
)
def test_tipo_errado_responde_400(client, method, path, base, field, value):
    if field in ("repeticao",) and value is True:
        pytest.skip("True vira texto vazio de regra: não é erro")
    assert client.open(path, method=method, json={**base, field: value}).status_code == 400


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("PATCH", "/api/config", {"sync_min": None}),
        ("PATCH", "/api/config", {"sync_min": [1]}),
        ("POST", "/api/eventos", {**EVENT, "aviso_min": []}),
        ("POST", "/api/eventos", {**EVENT, "calendar_id": [1]}),
        ("POST", "/api/eventos", {**EVENT, "calendar_id": 10**30}),
        ("POST", "/api/eventos", {**EVENT, "repeticao": [1]}),
        ("POST", "/api/todos", {"titulo": "a", "parent_id": [1]}),
        ("POST", "/api/todos/ordem", {"ids": 123}),
        ("POST", "/api/todos/ordem", {"ids": [10**30]}),
        ("POST", "/api/push/inscrever", {"inscricao": "abc"}),
    ],
)
def test_valor_invalido_responde_400(client, method, path, payload):
    assert client.open(path, method=method, json=payload).status_code == 400


@pytest.mark.parametrize(
    "url",
    [
        "/api/painel?semana=99999999999999999999",
        "/api/eventos/conflitos?inicio=2026-01-01T00:00&fim=9999-12-31T23:59",
    ],
)
def test_data_fora_do_intervalo_responde_400(client, url):
    # Com uma série no banco, somar ao ano 9999 estoura ao calcular as ocorrências
    client.post("/api/eventos", json={**EVENT, "repeticao": "semanal"})
    assert client.get(url).status_code == 400


def test_adiar_com_minutos_invalidos_responde_400(client):
    r = reminders.create(REMINDER)
    assert client.post(f"/api/lembretes/{r['id']}/adiar", json={"minutos": None}).status_code == 400
