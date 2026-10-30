"""API JSON das telas (/api/...). As rotas só chamam as regras de dailylife.core."""

import json
import logging
import os
import threading

from flask import Blueprint, Response, jsonify, request

from dailylife import config, push, qr, tailscale
from dailylife.core import ValidationError, backup, calendars, dashboard, events, reminders, settings, todos
from dailylife.desktop import notifier, startup
from dailylife.sync import google as google_sync
from dailylife.web.net import body, is_local_request, server_now

log = logging.getLogger("dailylife.api")
bp = Blueprint("api", __name__, url_prefix="/api")

# Ganchos que o desktop/app.py preenche (janelas, sempre por cima, sincronizar agora)
desktop_hooks = {}


def _ask_sync() -> None:
    fn = desktop_hooks.get("sincronizar")
    if fn:
        fn()
    elif google_sync.is_connected():
        threading.Thread(target=google_sync.sync_all, daemon=True).start()


@bp.get("/ping")
def ping():
    return jsonify(app=config.APP_NAME, ok=True, agora=server_now())


@bp.get("/painel")
def api_painel():
    return jsonify(dashboard.overview(semana=int(request.args.get("semana", 0))))


# to-do
@bp.get("/todos")
def api_todos():
    aba = request.args.get("aba", "hoje")
    return jsonify(itens=todos.list_tab(aba), contagem=todos.counts())


@bp.post("/todos")
def api_todo_create():
    return jsonify(todos.create(body())), 201


@bp.get("/todos/<int:tid>")
def api_todo_get(tid: int):
    return jsonify(todos.get(tid))


@bp.patch("/todos/<int:tid>")
def api_todo_update(tid: int):
    return jsonify(todos.update(tid, body()))


@bp.delete("/todos/<int:tid>")
def api_todo_delete(tid: int):
    todos.delete(tid)
    return jsonify(ok=True)


@bp.post("/todos/ordem")
def api_todo_order():
    todos.reorder(body().get("ids", []))
    return jsonify(ok=True)


# lembretes
@bp.get("/lembretes")
def api_rems():
    return jsonify(itens=reminders.list_filtered(request.args.get("filtro", "todos")))


@bp.post("/lembretes")
def api_rem_create():
    return jsonify(reminders.create(body())), 201


@bp.get("/lembretes/<int:rid>")
def api_rem_get(rid: int):
    return jsonify(reminders.get(rid))


@bp.patch("/lembretes/<int:rid>")
def api_rem_update(rid: int):
    return jsonify(reminders.update(rid, body()))


@bp.post("/lembretes/<int:rid>/resolver")
def api_rem_resolve(rid: int):
    return jsonify(reminders.resolve(rid))


@bp.post("/lembretes/<int:rid>/desfazer")
def api_rem_undo(rid: int):
    return jsonify(reminders.undo(rid))


@bp.post("/lembretes/<int:rid>/adiar")
def api_rem_snooze(rid: int):
    return jsonify(reminders.snooze(rid, body().get("minutos", 60)))


@bp.delete("/lembretes/<int:rid>")
def api_rem_delete(rid: int):
    reminders.delete(rid)
    return jsonify(ok=True)


# compromissos
@bp.get("/eventos")
def api_events():
    ini = config.parse_iso(request.args["inicio"])
    fim = config.parse_iso(request.args["fim"])
    if fim <= ini or (fim - ini).days > 400:
        raise ValidationError("Período inválido.")
    return jsonify(itens=events.list_range(ini, fim))


@bp.get("/eventos/conflitos")
def api_conflicts():
    ignore = request.args.get("ignorar", type=int)
    found = events.conflicts(
        request.args["inicio"],
        request.args["fim"],
        ignore_id=ignore,
        ignore_ocorrencia=request.args.get("ocorrencia"),
    )
    return jsonify(itens=[{"titulo": e["titulo"], "inicio": e["inicio"], "fim": e["fim"]} for e in found])


@bp.post("/eventos")
def api_event_create():
    ev = events.create(body())
    _ask_sync()
    return jsonify(ev), 201


@bp.get("/eventos/<int:eid>")
def api_event_get(eid: int):
    return jsonify(events.get(eid))


@bp.patch("/eventos/<int:eid>")
def api_event_update(eid: int):
    data = body()
    escopo = data.pop("escopo", "todos")
    ocorrencia = data.pop("ocorrencia", None)
    ev = events.update(eid, data, escopo=escopo, ocorrencia=ocorrencia)
    _ask_sync()
    return jsonify(ev)


@bp.delete("/eventos/<int:eid>")
def api_event_delete(eid: int):
    events.delete(eid, escopo=request.args.get("escopo", "todos"), ocorrencia=request.args.get("ocorrencia"))
    _ask_sync()
    return jsonify(ok=True)


# calendários
@bp.get("/calendarios")
def api_cals():
    return jsonify(itens=calendars.list_all())


@bp.post("/calendarios")
def api_cal_create():
    return jsonify(calendars.create(body())), 201


@bp.patch("/calendarios/<int:cid>")
def api_cal_update(cid: int):
    cal = calendars.update(cid, body())
    if cal["origem"] == "google" and cal["visivel"]:
        _ask_sync()
    return jsonify(cal)


@bp.delete("/calendarios/<int:cid>")
def api_cal_delete(cid: int):
    calendars.delete(cid)
    return jsonify(ok=True)


# configurações
@bp.get("/config")
def api_config():
    data = settings.get_all()
    data["abrir_com_windows"] = startup.is_enabled() if startup.is_supported() else data["abrir_com_windows"]
    data["inicializacao_suportada"] = startup.is_supported()
    data["desktop"] = "widget" in desktop_hooks
    data["backups"] = backup.list_backups()[:5]
    return jsonify(data)


@bp.patch("/config")
def api_config_update():
    data = body()
    if not is_local_request():
        for k in ("abrir_com_windows", "sempre_por_cima", "acesso_rede"):
            if k in data:
                raise ValidationError("Essa opção só pode ser mudada no computador.")
    out = settings.update(data)
    if "abrir_com_windows" in data and startup.is_supported():
        try:
            startup.set_enabled(out["abrir_com_windows"])
        except OSError as e:
            raise ValidationError(f"Não consegui mudar a inicialização do Windows: {e}") from None
    if "sempre_por_cima" in data and desktop_hooks.get("on_top"):
        desktop_hooks["on_top"](out["sempre_por_cima"])
    if "sync_min" in data:
        _ask_sync()
    return jsonify(out)


@bp.post("/config/senha")
def api_password_set():
    settings.set_password(body().get("senha", ""))
    return jsonify(ok=True)


# celular (Tailscale e avisos)
def _phone_state() -> dict:
    st = tailscale.status() if is_local_request() else {}
    address = tailscale.address(st)
    return {
        "local": is_local_request(),
        "tailscale": st,
        "endereco": address,
        "qr": qr.svg(address) if address and st.get("publicado") else "",
        "acesso": bool(settings.get("acesso_rede")),
        "tem_senha": bool(settings.get("pin_hash")),
        "push": {"disponivel": push.AVAILABLE, "chave": push.public_key(), "aparelhos": len(push.devices())},
    }


@bp.get("/celular")
def api_phone():
    return jsonify(_phone_state())


@bp.post("/celular/ligar")
def api_phone_on():
    if not settings.get("pin_hash"):
        raise ValidationError("Crie uma senha antes de ligar o acesso pelo celular.")
    st = tailscale.status()
    if not st["instalado"]:
        raise ValidationError("Instale o Tailscale neste PC primeiro.")
    if not st["conectado"]:
        raise ValidationError("Abra o Tailscale e entre na sua conta.")
    result = tailscale.publish()
    if result["ok"]:
        settings.set("acesso_rede", True)
    return jsonify({**result, **_phone_state()})


@bp.post("/celular/desligar")
def api_phone_off():
    settings.set("acesso_rede", False)
    result = tailscale.unpublish()
    return jsonify({**result, **_phone_state()})


@bp.post("/push/inscrever")
def api_push_subscribe():
    data = body()
    push.subscribe(data.get("inscricao") or {}, str(data.get("aparelho") or ""))
    return jsonify(ok=True)


@bp.post("/push/cancelar")
def api_push_unsubscribe():
    push.unsubscribe(str(body().get("endpoint") or ""))
    return jsonify(ok=True)


@bp.post("/push/teste")
def api_push_test():
    if not push.AVAILABLE:
        raise ValidationError("Avisos no celular indisponíveis: falta a biblioteca cryptography.")
    sent = push.send_all(
        {"titulo": "Teste do Daily Life", "corpo": "Os avisos chegam neste aparelho.", "url": "/"}
    )
    return jsonify(ok=True, enviados=sent)


# Google
@bp.get("/google")
def api_google():
    return jsonify(google_sync.status())


@bp.post("/google/conectar")
def api_google_connect():
    if google_sync.STATE["conectando"]:
        return jsonify(ok=True, mensagem="Login já aberto no navegador.")
    if not google_sync.LIBS_OK:
        raise ValidationError("Bibliotecas do Google não instaladas. Rode: pip install -r requirements.txt")
    if not google_sync.has_credentials():
        raise ValidationError("Coloque o arquivo credentials.json na pasta do Daily Life (veja o README).")

    def run() -> None:
        try:
            google_sync.connect()
        except Exception as e:
            log.exception("login Google")
            google_sync.STATE["erro"] = f"Não foi possível conectar: {e}"

    threading.Thread(target=run, daemon=True, name="google-login").start()
    return jsonify(ok=True, mensagem="Abri o navegador para você entrar na conta Google.")


@bp.post("/google/desconectar")
def api_google_disconnect():
    google_sync.disconnect()
    return jsonify(ok=True)


@bp.post("/google/sincronizar")
def api_google_sync():
    _ask_sync()
    return jsonify(ok=True)


# avisos para as telas
@bp.get("/estado")
def api_state():
    """Consulta única das telas: avisos novos (desde o número que a tela já viu) e o Google."""
    desde = request.args.get("desde", type=int)
    itens = [] if desde is None else notifier.inbox_since(desde)
    return jsonify(
        itens=itens, ultimo=notifier.last_id(), sessao=notifier.SESSION, google=google_sync.status()
    )


# backup, exportar, importar
@bp.post("/backup")
def api_backup():
    path = backup.make_backup(force=True)
    return jsonify(ok=True, arquivo=os.path.basename(path))


@bp.get("/exportar")
def api_export():
    data = backup.export_data()
    name = f"{config.APP_SLUG}-{config.now().date().isoformat()}.json"
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@bp.post("/importar")
def api_import():
    if "arquivo" in request.files:
        data = json.loads(request.files["arquivo"].read().decode("utf-8"))
    else:
        data = body()
    return jsonify(ok=True, importado=backup.import_data(data))


# janelas (só no app de computador)
@bp.post("/janela/abrir")
def api_window_open():
    url = str(body().get("url") or "/")
    if not url.startswith("/") or url.startswith("//"):
        raise ValidationError("Endereço inválido.")
    fn = desktop_hooks.get("abrir_url")
    if not fn:
        return jsonify(ok=False, erro="Disponível só no app de computador."), 400
    fn(url)
    return jsonify(ok=True)


@bp.post("/janela/<acao>")
def api_window(acao: str):
    fn = desktop_hooks.get(acao)
    if not fn:
        return jsonify(ok=False, erro="Disponível só no app de computador."), 400
    fn()
    return jsonify(ok=True)
