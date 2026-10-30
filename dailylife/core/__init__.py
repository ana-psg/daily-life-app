"""Regras de negócio do Daily Life. As rotas do Flask só chamam estas funções."""

from typing import Any


class ValidationError(ValueError):
    """Erro de dado inválido, mostrado para a usuária como mensagem."""


class NotFound(LookupError):
    """Registro não encontrado."""


def require_text(data: dict, key: str, label: str, max_len: int = 300) -> str:
    value = (data.get(key) or "").strip()
    if not value:
        raise ValidationError(f"{label} é obrigatório.")
    if len(value) > max_len:
        raise ValidationError(f"{label} pode ter no máximo {max_len} caracteres.")
    return value


def as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "sim", "on", "yes")
    return bool(value)
