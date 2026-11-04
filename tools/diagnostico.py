"""Diagnóstico do Daily Life: mostra o que carrega e o que o Windows bloqueou.

Uso: python tools/diagnostico.py
O resultado também é salvo em data/diagnostico.txt.
"""

import importlib
import os
import platform
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CHECKS = [
    ("flask", "Servidor das telas", True),
    ("webview", "Janela própria e widget (pywebview)", False),
    ("clr", "Ponte com o Windows usada pela janela (pythonnet)", False),
    ("pystray", "Ícone na bandeja", False),
    ("PIL", "Imagens do ícone (Pillow)", False),
    ("win11toast", "Avisos do Windows com botões", False),
    ("cryptography", "Avisos no celular (Web Push)", False),
    ("dateutil", "Repetições personalizadas do Google", True),
    ("googleapiclient", "Google Agenda", False),
    ("google_auth_oauthlib", "Login do Google", False),
]

BLOCK_HINTS = ("4551", "Application Control", "Controle de Aplicativo", "bloqueou", "blocked")


def smart_app_control_state():
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\CI\Policy") as k:
            value, _ = winreg.QueryValueEx(k, "VerifiedAndReputablePolicyState")
        return {0: "desligado", 1: "ligado", 2: "em avaliação"}.get(value, f"desconhecido ({value})")
    except Exception:
        return "não foi possível ler"


def main():
    lines = [
        "Daily Life · diagnóstico",
        f"Python {platform.python_version()} · {platform.platform()}",
        f"Pasta: {ROOT}",
    ]
    if os.name == "nt":
        lines.append(f"Controle de Aplicativos Inteligente: {smart_app_control_state()}")
    lines.append("")
    blocked = []
    for module, label, required in CHECKS:
        try:
            importlib.import_module(module)
            lines.append(f"  OK          {label}")
        except Exception as e:
            msg = str(e)
            is_block = any(h.lower() in msg.lower() for h in BLOCK_HINTS)
            tag = "BLOQUEADO" if is_block else "FALTANDO "
            lines.append(f"  {tag}   {label} [{module}]: {msg[:160]}")
            if is_block:
                blocked.append(label)
            elif required:
                blocked.append(label + " (obrigatório)")
    lines.append("")
    if any("BLOQUEADO" in ln for ln in lines):
        lines += [
            "O Controle de Aplicativos Inteligente do Windows bloqueou bibliotecas sem assinatura digital.",
            "O Daily Life continua funcionando: abre no Edge em modo aplicativo",
            "e os avisos saem pela bandeja.",
            "Para ter a janela própria e o widget, desligue em: Segurança do Windows >",
            "Controle de aplicativos e do navegador > Configurações do Controle de",
            "Aplicativos Inteligente > Desativado.",
        ]
    elif any("FALTANDO" in ln for ln in lines):
        lines.append("Faltam bibliotecas: pip install -r requirements.txt")
    else:
        lines.append("Tudo certo: todas as partes do Daily Life carregaram.")
    text = "\n".join(lines)
    print(text)
    try:
        os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
        with open(os.path.join(ROOT, "data", "diagnostico.txt"), "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
