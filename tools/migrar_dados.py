"""Copia os dados da pasta data/ do projeto para a pasta do programa instalado (%APPDATA%\\Daily Life).

Uso, com o Daily Life fechado: python tools/migrar_dados.py
Só copia: a pasta de origem fica intacta, e um destino que já tem banco nunca é sobrescrito.
"""

import os
import shutil
import sqlite3
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRAS = ("token.json", "secret.key", "push_key.pem")
DB_NAME = "dailylife.db"


class MigrationError(Exception):
    """Motivo, em português, para não migrar."""


def app_is_open(port: int = 5055) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1.5):
            return True
    except OSError:
        return False


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for (t,) in names.fetchall()}


def _copy_database(source: str, dest: str) -> dict[str, int]:
    """A API de backup leva também o que ainda está no arquivo -wal; copiar só o .db perderia isso."""
    tmp = dest + ".tmp"
    src = sqlite3.connect(f"file:{source.replace(os.sep, '/')}?mode=ro", uri=True)
    out = sqlite3.connect(tmp)
    try:
        src.backup(out)
        if out.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("A cópia do banco não passou na verificação de integridade.")
        counts = _counts(src)
        if _counts(out) != counts:
            raise MigrationError("A cópia do banco não tem as mesmas contagens do original.")
    except Exception:
        out.close()
        os.remove(tmp)
        raise
    finally:
        out.close()
        src.close()
    os.replace(tmp, dest)
    return counts


def migrate(source_dir: str, dest_dir: str, credentials: str | None = None) -> dict[str, int]:
    source_db = os.path.join(source_dir, DB_NAME)
    dest_db = os.path.join(dest_dir, DB_NAME)
    if not os.path.exists(source_db):
        raise MigrationError(f"Não encontrei o banco em {source_db}.")
    if os.path.exists(dest_db):
        raise MigrationError(f"Já existe um banco em {dest_db}. Nada foi alterado.")
    os.makedirs(dest_dir, exist_ok=True)
    counts = _copy_database(source_db, dest_db)
    for name in EXTRAS:
        if os.path.exists(os.path.join(source_dir, name)):
            shutil.copy2(os.path.join(source_dir, name), os.path.join(dest_dir, name))
    if os.path.isdir(os.path.join(source_dir, "backups")):
        shutil.copytree(
            os.path.join(source_dir, "backups"), os.path.join(dest_dir, "backups"), dirs_exist_ok=True
        )
    if credentials and os.path.exists(credentials):
        shutil.copy2(credentials, os.path.join(dest_dir, "credentials.json"))
    return counts


def main() -> int:
    dest = os.path.join(os.environ["APPDATA"], "Daily Life")
    if app_is_open():
        print("Feche o Daily Life antes (bandeja > Sair do Daily Life) e rode de novo.")
        return 1
    try:
        counts = migrate(os.path.join(ROOT, "data"), dest, os.path.join(ROOT, "credentials.json"))
    except MigrationError as e:
        print(e)
        return 1
    print(f"Dados copiados para {dest}. A pasta data/ não foi alterada.")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
