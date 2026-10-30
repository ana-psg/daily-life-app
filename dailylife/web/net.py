"""Pequenas funções de rede usadas pelo servidor: quem está pedindo, de onde e quando."""

import ipaddress
from datetime import datetime
from urllib.parse import urlsplit

from flask import request

from dailylife import config

LOCAL_NAMES = ("localhost", "127.0.0.1", "::1")


def _host_name(host: str | None) -> str:
    return (urlsplit("//" + (host or "")).hostname or "").lower()


# Cabeçalhos que só um intermediário (o `tailscale serve`) coloca; o navegador do PC nunca manda
PROXY_HEADERS = ("Tailscale-User-Login", "X-Forwarded-For", "X-Forwarded-Host")


def public_host() -> str:
    """Endereço que o aparelho digitou (o `tailscale serve` pode trocar o Host pelo destino local)."""
    return request.headers.get("X-Forwarded-Host") or request.host


def is_local_request() -> bool:
    """O pedido veio deste computador, digitado como localhost?

    Pedidos do celular chegam pelo `tailscale serve`, que também conecta de 127.0.0.1,
    mas com o endereço *.ts.net e cabeçalhos de intermediário: esses contam como de fora.
    """
    try:
        loopback = ipaddress.ip_address(request.remote_addr or "").is_loopback
    except ValueError:
        return False
    via_proxy = any(h in request.headers for h in PROXY_HEADERS)
    return loopback and not via_proxy and _host_name(public_host()) in LOCAL_NAMES


def host_allowed(host: str | None) -> bool:
    """Só aceita localhost, endereço IP ou o endereço do Tailscale (*.ts.net) no Host.

    Um site com domínio próprio apontando para 127.0.0.1 (DNS rebinding) chega com o
    domínio dele no Host e é recusado.
    """
    name = _host_name(host)
    if name == "localhost" or name.endswith(".ts.net"):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def body() -> dict:
    """Corpo JSON do pedido; qualquer coisa que não seja um objeto vira {}."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def server_now() -> str:
    """Hora de São Paulo com segundos: as telas usam para não depender do fuso do aparelho."""
    return datetime.now(config.TZ).strftime("%Y-%m-%dT%H:%M:%S")
