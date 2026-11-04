"""Proteção dos testes: recusa rodar se o banco apontar para os dados reais."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_app  # noqa: F401  (aponta o app para uma pasta temporária)

from dailylife import config


def _is_inside(path: str, folder: str) -> bool:
    path, folder = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return path == folder or path.startswith(folder + os.sep)


if _is_inside(config.DB_PATH, os.path.join(ROOT, "data")) or _is_inside(
    config.DATA_DIR, os.path.join(ROOT, "data")
):
    pytest.exit("Os testes apontam para os dados reais em data/. Nada foi executado.", returncode=2)
