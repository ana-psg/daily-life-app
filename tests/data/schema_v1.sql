-- Banco da versão 1, para testar as migrações.
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
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_google ON events(calendar_id, google_event_id);

CREATE TABLE IF NOT EXISTS todo_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chave TEXT UNIQUE,
    nome TEXT NOT NULL,
    ordem INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER NOT NULL REFERENCES todo_lists(id),
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
    cor TEXT NOT NULL DEFAULT 'amarelo',
    resolvido INTEGER NOT NULL DEFAULT 0,
    resolvido_em TEXT,
    ultimo_resolvido TEXT,                         -- data (YYYY-MM-DD) da última vez marcado
    adiado_ate TEXT,
    ultimo_aviso TEXT,
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
