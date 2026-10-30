"""Acesso pelo celular fora de casa, pelo Tailscale.

O Tailscale cria uma rede privada só entre os aparelhos da pessoa. O comando
`tailscale serve` publica o app nessa rede com HTTPS, num endereço como
https://notebook.tail1234.ts.net, repassando os pedidos para 127.0.0.1:PORTA.
Assim o servidor nunca escuta na rede de casa nem em Wi-Fi nenhum.
"""

import json
import logging
import os
import re
import shutil
import subprocess

from dailylife import config

log = logging.getLogger("dailylife.tailscale")

TIMEOUT = 20
LINK_RE = re.compile(r"https://login\.tailscale\.com/\S+")


def find_cli() -> str | None:
    """Caminho do tailscale.exe (Windows) ou do comando tailscale."""
    found = shutil.which("tailscale")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            path = os.path.join(base, "Tailscale", "tailscale.exe")
            if os.path.exists(path):
                return path
    return None


def _run(*args: str, timeout: int = TIMEOUT) -> tuple[int, str]:
    cli = find_cli()
    if not cli:
        return 127, "Tailscale não instalado."
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # sem janela de terminal no Windows
    try:
        proc = subprocess.run(
            [cli, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=flags,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as e:
        # `serve` espera a usuária liberar o HTTPS no site: a saída parcial traz o link
        out = e.stdout or b""
        out = out.decode(errors="replace") if isinstance(out, bytes) else out
        return 124, out
    except OSError as e:
        return 126, str(e)


def _serving(serve_status: dict) -> bool:
    """O `tailscale serve` já está repassando para a porta do app?"""
    target = f"127.0.0.1:{config.PORT}"
    for site in (serve_status.get("Web") or {}).values():
        for handler in (site.get("Handlers") or {}).values():
            if target in str(handler.get("Proxy", "")) or f"localhost:{config.PORT}" in str(
                handler.get("Proxy", "")
            ):
                return True
    return False


def status() -> dict:
    """Situação do Tailscale neste PC, para a tela de Configurações."""
    out = {"instalado": bool(find_cli()), "conectado": False, "nome": "", "ip": "", "publicado": False}
    if not out["instalado"]:
        return out
    code, text = _run("status", "--json", timeout=8)
    if code != 0:
        return out
    try:
        st = json.loads(text)
    except ValueError:
        return out
    me = st.get("Self") or {}
    out["conectado"] = st.get("BackendState") == "Running"
    out["nome"] = (me.get("DNSName") or "").rstrip(".")
    out["ip"] = next((ip for ip in me.get("TailscaleIPs") or [] if "." in ip), "")
    code, text = _run("serve", "status", "--json", timeout=8)
    if code == 0:
        try:
            out["publicado"] = _serving(json.loads(text or "{}"))
        except ValueError:
            pass
    return out


def address(st: dict) -> str:
    return f"https://{st['nome']}" if st.get("nome") else ""


def publish() -> dict:
    """Liga o endereço HTTPS do app na rede do Tailscale (fica ligado até desligar)."""
    code, text = _run("serve", "--bg", str(config.PORT), timeout=12)
    link = LINK_RE.search(text)
    if link:  # HTTPS ainda não liberado na conta: o Tailscale pede para abrir este link uma vez
        return {
            "ok": False,
            "link": link.group(0).rstrip(".,"),
            "mensagem": "Libere o HTTPS na sua conta do Tailscale.",
        }
    if code != 0:
        log.warning("tailscale serve falhou (%s): %s", code, text)
        return {"ok": False, "mensagem": text.strip()[:300] or "Não deu para ligar o endereço."}
    return {"ok": True}


def unpublish() -> dict:
    code, text = _run("serve", "--https=443", "off")
    if code != 0:
        code, text = _run("serve", "reset")
    return {"ok": code == 0, "mensagem": "" if code == 0 else text.strip()[:300]}
