"""Confere que nenhum dado pessoal entrou no pacote; o build para se encontrar algum.

Uso: python tools/verificar_pacote.py dist/DailyLife

Os textos procurados vêm de quem está gerando o build (usuário do Windows, e-mail do git e
endereço do Tailscale), para que este arquivo não precise guardar nenhum dado pessoal.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import types

FORBIDDEN_NAME = re.compile(
    r"(\.db|\.db-wal|\.db-shm|\.db\.bak|\.log|\.pem|\.env)$|^(token|credentials|secret\.key)(\.json)?$|client_secret",
    re.IGNORECASE,
)
# Bibliotecas trazem chaves e certificados públicos que não têm nada a ver com o usuário
ALLOWED_NAME = re.compile(r"cacert\.pem$|certifi[\\/]", re.IGNORECASE)
MIN_TEXT = 6  # textos curtos demais dariam alarme falso em arquivos binários


def _command_output(*args: str) -> str:
    if not shutil.which(args[0]) and not os.path.exists(args[0]):
        return ""
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=15, check=False).stdout.strip()
    except OSError:
        return ""


def _tailscale_name() -> str:
    cli = shutil.which("tailscale") or os.path.join(
        os.environ.get("ProgramFiles", ""), "Tailscale", "tailscale.exe"
    )
    try:
        name = json.loads(_command_output(cli, "status", "--json") or "{}")["Self"]["DNSName"]
    except (ValueError, KeyError):
        return ""
    return name.rstrip(".")


def personal_texts() -> list[str]:
    home = os.path.expanduser("~")
    email = _command_output("git", "config", "user.email")
    tailnet = _tailscale_name()
    found = [home, home.replace("\\", "/"), email, email.split("@")[0], tailnet, *tailnet.split(".")[1:2]]
    return sorted({t for t in found if len(t) >= MIN_TEXT})


def bad_names(root: str) -> list[str]:
    out = []
    for folder, _, files in os.walk(root):
        for name in files:
            path = os.path.join(folder, name)
            if FORBIDDEN_NAME.search(name) and not ALLOWED_NAME.search(path):
                out.append(path)
    return out


def code_text(code: types.CodeType) -> bytes:
    """Os textos de um módulo compilado: constantes (também das funções internas) e o nome do arquivo."""
    parts = [code.co_filename.encode("utf-8", "replace")]
    for const in code.co_consts:
        if isinstance(const, str):
            parts.append(const.encode("utf-8", "replace"))
        elif isinstance(const, bytes):
            parts.append(const)
        elif isinstance(const, types.CodeType):
            parts.append(code_text(const))
    return b"\n".join(parts)


def _embedded_modules(path: str) -> list[tuple[str, bytes]]:
    """Os módulos Python ficam comprimidos dentro do executável: abre para conferir também."""
    from PyInstaller.archive.readers import CArchiveReader

    out = []
    archive = CArchiveReader(path)
    for name in archive.toc:
        if name.endswith(".pyz"):
            modules = archive.open_embedded_archive(name)
            for module in modules.toc:
                code = modules.extract(module)
                if isinstance(code, types.CodeType):  # None = pacote sem código
                    out.append((f"{name}:{module}", code_text(code)))
    return out


def bad_contents(root: str, texts: list[str]) -> list[str]:
    needles = [(t, t.encode("utf-8").lower()) for t in texts]
    out = []
    for folder, _, files in os.walk(root):
        for name in files:
            path = os.path.join(folder, name)
            with open(path, "rb") as f:
                data = f.read().lower()
            out += [f"{path}: {t}" for t, n in needles if n in data]
            if name.lower().endswith(".exe"):
                modules = _embedded_modules(path)
                if not modules:
                    out.append(f"{path}: não consegui abrir os módulos para conferir")
                for label, text in modules:
                    out += [f"{label}: {t}" for t, n in needles if n in text.lower()]
    return out


def main() -> int:
    root = sys.argv[1]
    problems = bad_names(root) + bad_contents(root, personal_texts())
    for problem in problems:
        print("DADO PESSOAL NO PACOTE:", problem)
    if problems:
        return 1
    print("Pacote limpo: nenhum dado pessoal encontrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
