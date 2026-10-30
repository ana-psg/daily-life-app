"""Banco SQLite do Daily Life.

SCHEMA é o formato atual do banco. Bancos antigos são atualizados pelas MIGRATIONS,
em ordem, guardando o número da última em PRAGMA user_version.

Para mudar o banco: altere SCHEMA (bancos novos) e acrescente uma migração no fim
de MIGRATIONS (bancos existentes). Nunca apague o banco para migrar.
"""

import sqlite3
import threading
from collections.abc import Callable

from dailylife import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS calendars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    cor TEXT NOT NULL DEFAULT '#7152F0',
    origem TEXT NOT NULL DEFAULT 'local',          -- local | google
    google_id TEXT UNIQUE,
    visivel INTEGER NOT NULL DEFAULT 1,
    somente_leitura INTEGER NOT NULL DEFAULT 0,
    ordem INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    calendar_id INTEGER NOT NULL REFERENCES calendars(id),
    titulo TEXT NOT NULL,
    inicio TEXT NOT NULL,
    fim TEXT NOT NULL,
    dia_inteiro INTEGER NOT NULL DEFAULT 0,
    local TEXT NOT NULL DEFAULT '',
    notas TEXT NOT NULL DEFAULT '',
    repeticao TEXT NOT NULL DEFAULT '',            -- '' | diaria | dias_uteis | semanal | mensal
    rrule TEXT,                                    -- regra do Google que não cabe em repeticao
    serie_id INTEGER REFERENCES events(id) ON DELETE CASCADE,  -- ocorrência alterada de uma série
    ocorrencia TEXT,                               -- início original da ocorrência alterada
    cancelado INTEGER NOT NULL DEFAULT 0,          -- 1 = ocorrência excluída da série
    fuso TEXT,                                     -- fuso da série do Google (ex.: Europe/London)
    rev INTEGER NOT NULL DEFAULT 0,                -- sobe a cada edição no app
    aviso_min INTEGER,                             -- NULL = sem aviso
    google_event_id TEXT,
    google_etag TEXT,
    google_updated TEXT,
    pendente_sync INTEGER NOT NULL DEFAULT 0,      -- 1 = enviar ao Google
    excluido INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_inicio ON events(inicio);
CREATE INDEX IF NOT EXISTS idx_events_serie ON events(serie_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_google ON events(calendar_id, google_event_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_override ON events(serie_id, ocorrencia)
    WHERE serie_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lista TEXT NOT NULL DEFAULT 'hoje',            -- hoje | semana | projetos
    parent_id INTEGER REFERENCES todos(id) ON DELETE CASCADE,
    titulo TEXT NOT NULL,
    notas TEXT NOT NULL DEFAULT '',
    prioridade TEXT NOT NULL DEFAULT 'media',      -- alta | media | baixa
    vencimento TEXT,                               -- YYYY-MM-DD ou YYYY-MM-DDTHH:MM
    feito INTEGER NOT NULL DEFAULT 0,
    feito_em TEXT,
    ordem INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    descricao TEXT NOT NULL DEFAULT '',
    quando TEXT NOT NULL,                          -- próximo disparo
    repeticao TEXT NOT NULL DEFAULT '',            -- '' | diaria | horas:2 | dias:0,3 | semanal | mensal
    hora_base TEXT,                                -- HH:MM da primeira vez do dia
    data_base TEXT,                                -- dia de referência da repetição mensal
    cor TEXT NOT NULL DEFAULT 'amarelo',
    resolvido INTEGER NOT NULL DEFAULT 0,
    resolvido_em TEXT,
    ultimo_resolvido TEXT,                         -- data (YYYY-MM-DD) da última vez marcado
    ultimo_aviso TEXT,
    quando_anterior TEXT,                          -- para desfazer um recorrente marcado
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    calendar_id INTEGER PRIMARY KEY REFERENCES calendars(id),
    sync_token TEXT,
    ultima_sync TEXT
);

CREATE TABLE IF NOT EXISTS event_alerts (
    event_id INTEGER NOT NULL,
    ocorrencia TEXT NOT NULL,
    avisado_em TEXT NOT NULL,
    PRIMARY KEY (event_id, ocorrencia)
);

CREATE TABLE IF NOT EXISTS push_subs (
    endpoint TEXT PRIMARY KEY,                     -- endereço do serviço de push do navegador
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    aparelho TEXT NOT NULL DEFAULT '',
    criado_em TEXT NOT NULL
);
"""

DEFAULT_CALENDARS = [
    ("Trabalho", "#5B7FFF"),
    ("Pessoal", "#36B072"),
    ("Saúde", "#F2894A"),
    ("Projetos", "#7152F0"),
]


def _table(name: str) -> str:
    """O CREATE TABLE de uma tabela, copiado do SCHEMA (as migrações criam igual a um banco novo)."""
    start = SCHEMA.index(f"CREATE TABLE IF NOT EXISTS {name} (")
    return SCHEMA[start : SCHEMA.index(");", start) + 2]


# ---------------- migrações de bancos antigos ----------------
def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _m1_series_and_reminders(conn: sqlite3.Connection) -> None:
    """Fase 1 da v2: séries do Google, ocorrências alteradas e âncoras dos lembretes."""
    _add_column(conn, "reminders", "quando_anterior", "TEXT")
    _add_column(conn, "reminders", "data_base", "TEXT")
    conn.execute("UPDATE reminders SET data_base=substr(quando,1,10) WHERE data_base IS NULL")
    for column, decl in [
        ("rrule", "TEXT"),
        ("serie_id", "INTEGER REFERENCES events(id) ON DELETE CASCADE"),
        ("ocorrencia", "TEXT"),
        ("cancelado", "INTEGER NOT NULL DEFAULT 0"),
        ("fuso", "TEXT"),
        ("rev", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        _add_column(conn, "events", column, decl)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_serie ON events(serie_id)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_override "
        "ON events(serie_id, ocorrencia) WHERE serie_id IS NOT NULL"
    )


def _m2_todo_list_column(conn: sqlite3.Connection) -> None:
    """Fase 2 da v2: a tabela todo_lists vira o campo todos.lista; sai reminders.adiado_ate."""
    if "list_id" in _columns(conn, "todos"):
        conn.execute("ALTER TABLE todos RENAME TO todos_antiga")
        conn.execute(_table("todos"))
        conn.execute(
            "INSERT INTO todos (id, lista, parent_id, titulo, notas, prioridade, vencimento, feito, "
            "feito_em, ordem, criado_em, atualizado_em) "
            "SELECT t.id, COALESCE(l.chave, 'hoje'), t.parent_id, t.titulo, t.notas, t.prioridade, "
            "t.vencimento, t.feito, t.feito_em, t.ordem, t.criado_em, t.atualizado_em "
            "FROM todos_antiga t LEFT JOIN todo_lists l ON l.id = t.list_id"
        )
        conn.execute("DROP TABLE todos_antiga")
    conn.execute("DROP TABLE IF EXISTS todo_lists")
    if "adiado_ate" in _columns(conn, "reminders"):
        conn.execute("ALTER TABLE reminders DROP COLUMN adiado_ate")


def _m3_push_subscriptions(conn: sqlite3.Connection) -> None:
    """Fase 4 da v2: aparelhos que recebem avisos pelo navegador (Web Push)."""
    conn.execute(_table("push_subs"))


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _m1_series_and_reminders,
    _m2_todo_list_column,
    _m3_push_subscriptions,
]


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    is_new = not conn.execute("SELECT 1 FROM sqlite_master WHERE name='calendars'").fetchone()
    if is_new:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")
        return
    if version >= len(MIGRATIONS):
        return
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")  # refazer tabelas sem disparar as chaves estrangeiras
    try:
        conn.execute("BEGIN")
        for step in MIGRATIONS[version:]:
            step(conn)
        conn.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


# ---------------- conexões ----------------
_local = threading.local()


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_conn() -> sqlite3.Connection:
    """Uma conexão por thread (servidor, agendador e sincronização rodam em threads diferentes)."""
    conn = getattr(_local, "conn", None)
    if conn is None or getattr(_local, "path", None) != config.DB_PATH:
        conn = connect()
        _local.conn, _local.path = conn, config.DB_PATH
    return conn


def close_conn() -> None:
    """Fecha a conexão da thread atual (fim de uma requisição ou de uma sincronização)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def init_db(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    conn = conn or get_conn()
    _migrate(conn)
    if not conn.execute("SELECT 1 FROM calendars WHERE origem='local' LIMIT 1").fetchone():
        stamp = config.iso(config.now())
        conn.executemany(
            "INSERT INTO calendars (nome, cor, origem, ordem, criado_em, atualizado_em) "
            "VALUES (?, ?, 'local', ?, ?, ?)",
            [(nome, cor, i, stamp, stamp) for i, (nome, cor) in enumerate(DEFAULT_CALENDARS)],
        )
    conn.commit()
    return conn


def rows(cursor: sqlite3.Cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]


def row(cursor: sqlite3.Cursor) -> dict | None:
    r = cursor.fetchone()
    return dict(r) if r else None
