"""Regras de negócio do Daily Life. As rotas do Flask só chamam estas funções."""

from typing import Any


class ValidationError(ValueError):
    """Erro de dado inválido, mostrado para a usuária como mensagem."""


class NotFound(LookupError):
    """Registro não encontrado."""


def clean_text(value: Any, label: str = "Texto", max_len: int | None = None) -> str:
    """Texto sem espaços nas pontas; vazio para None e erro para qualquer outro tipo."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"{label}: valor inválido.")
    value = value.strip()
    return value[:max_len] if max_len else value


def as_int(value: Any, label: str = "Número") -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValidationError(f"{label}: valor inválido.") from None


def require_text(data: dict, key: str, label: str, max_len: int = 300) -> str:
    value = clean_text(data.get(key), label)
    if not value:
        raise ValidationError(f"{label} é obrigatório.")
    if len(value) > max_len:
        raise ValidationError(f"{label} pode ter no máximo {max_len} caracteres.")
    return value


def as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "sim", "on", "yes")
    return bool(value)
