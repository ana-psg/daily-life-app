"""Dados de exemplo, para testar as telas.

Uso:  python tools/seed.py          (só cria se o banco estiver vazio)
      python tools/seed.py --forcar (apaga tarefas, lembretes e compromissos locais e recria)
"""

import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dailylife import config, db
from dailylife.core import events, reminders, todos


def run(force=False):
    conn = db.init_db()
    has_data = conn.execute(
        "SELECT (SELECT COUNT(*) FROM todos) + (SELECT COUNT(*) FROM reminders) + "
        "(SELECT COUNT(*) FROM events)"
    ).fetchone()[0]
    if has_data and not force:
        print("O banco já tem dados. Use --forcar para recriar os exemplos.")
        return
    if force:
        conn.execute("DELETE FROM todos")
        conn.execute("DELETE FROM reminders")
        conn.execute("DELETE FROM event_alerts")
        conn.execute(
            "DELETE FROM events WHERE calendar_id IN (SELECT id FROM calendars WHERE origem='local')"
        )
        conn.commit()

    cal = {r["nome"]: r["id"] for r in conn.execute("SELECT id, nome FROM calendars WHERE origem='local'")}
    now = config.now()
    today = now.replace(hour=0, minute=0)
    monday = today - timedelta(days=today.weekday())

    def at(day, hhmm):
        h, m = (int(x) for x in hhmm.split(":"))
        return config.iso(day.replace(hour=h, minute=m))

    # Compromissos
    events.create(
        {
            "titulo": "Daily do time",
            "calendar_id": cal["Trabalho"],
            "inicio": at(monday, "09:00"),
            "fim": at(monday, "09:30"),
            "repeticao": "dias_uteis",
            "local": "https://meet.google.com/",
            "aviso_min": 5,
        },
        conn,
    )
    exemplos = [
        (0, "14:00", "15:00", "Reunião com cliente", "Projetos", "Google Meet"),
        (1, "11:00", "12:00", "Planejamento mensal", "Pessoal", "Casa"),
        (1, "18:30", "19:30", "Academia", "Saúde", "Academia do bairro"),
        (2, "16:00", "17:00", "Dentista", "Saúde", "Consultório"),
        (3, "10:30", "11:30", "Revisão de relatórios", "Projetos", "Sala 2"),
        (3, "13:00", "14:00", "Almoço com amigos", "Pessoal", "Restaurante"),
        (3, "18:30", "19:30", "Academia", "Saúde", "Academia do bairro"),
        (4, "15:00", "16:00", "Reunião de equipe", "Trabalho", "Google Meet"),
        (5, "10:00", "12:00", "Feira e mercado", "Pessoal", "Feira do bairro"),
        (6, "11:00", "12:30", "Almoço em família", "Pessoal", "Casa da família"),
    ]
    for d, ini, fim, titulo, c, local in exemplos:
        day = monday + timedelta(days=d)
        events.create(
            {
                "titulo": titulo,
                "calendar_id": cal[c],
                "inicio": at(day, ini),
                "fim": at(day, fim),
                "local": local,
                "aviso_min": 15,
            },
            conn,
        )

    # To-do
    t = todos.create({"titulo": "Responder e-mails pendentes", "lista": "hoje", "prioridade": "media"}, conn)
    todos.update(t["id"], {"feito": True}, conn)
    t = todos.create(
        {"titulo": "Atualizar planilha de gastos do mês", "lista": "hoje", "prioridade": "baixa"}, conn
    )
    todos.update(t["id"], {"feito": True}, conn)
    t = todos.create(
        {"titulo": "Preparar pauta da revisão de relatórios", "lista": "hoje", "prioridade": "alta"}, conn
    )
    s = todos.create({"titulo": "Separar números da semana", "parent_id": t["id"]}, conn)
    todos.update(s["id"], {"feito": True}, conn)
    todos.create({"titulo": "Listar dúvidas do time", "parent_id": t["id"]}, conn)
    todos.create({"titulo": "Agendar revisão do carro", "lista": "hoje", "prioridade": "media"}, conn)
    todos.create({"titulo": "Ler 20 páginas do livro", "lista": "hoje", "prioridade": "baixa"}, conn)
    todos.create(
        {
            "titulo": "Comprar presente de aniversário",
            "lista": "semana",
            "vencimento": (today + timedelta(days=2)).date().isoformat(),
        },
        conn,
    )
    todos.create(
        {
            "titulo": "Enviar documentos para o contador",
            "lista": "semana",
            "prioridade": "alta",
            "vencimento": (today + timedelta(days=1)).date().isoformat(),
        },
        conn,
    )
    p = todos.create({"titulo": "Montar o app Daily Life", "lista": "projetos", "prioridade": "alta"}, conn)
    for i, etapa in enumerate(
        [
            "Desenhar as telas",
            "Definir o banco de dados",
            "Conectar o Google Agenda",
            "Abrir junto com o Windows",
        ]
    ):
        s = todos.create({"titulo": etapa, "parent_id": p["id"]}, conn)
        if i < 2:
            todos.update(s["id"], {"feito": True}, conn)

    # Lembretes
    reminders.create(
        {
            "titulo": "Beber água",
            "descricao": "Meta do dia: 2 litros.",
            "quando": at(today, "08:00"),
            "repeticao": "horas:2",
            "cor": "azul",
        },
        conn,
    )
    reminders.create(
        {
            "titulo": "Pagar conta de luz",
            "descricao": "Pagar pelo app do banco antes do almoço.",
            "quando": at(today, "12:00"),
            "cor": "rosa",
        },
        conn,
    )
    reminders.create(
        {
            "titulo": "Regar as plantas",
            "descricao": "Varanda e sala.",
            "quando": at(today, "19:00"),
            "repeticao": "dias:0,3",
            "cor": "verde",
        },
        conn,
    )
    reminders.create(
        {
            "titulo": "Renovar assinatura da academia",
            "descricao": "Ver se tem desconto no plano anual.",
            "quando": at(today + timedelta(days=1), "09:00"),
            "cor": "amarelo",
        },
        conn,
    )
    reminders.create(
        {
            "titulo": "Backup do computador",
            "descricao": "HD externo na gaveta.",
            "quando": at(today + timedelta(days=3), "10:00"),
            "repeticao": "mensal",
            "cor": "lilas",
        },
        conn,
    )
    print("Dados de exemplo criados.")


if __name__ == "__main__":
    run(force="--forcar" in sys.argv)
