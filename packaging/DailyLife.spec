# Receita do executável. Pasta (onedir) e sem UPX: os dois reduzem alarmes falsos de antivírus.
# Gerar: python -m PyInstaller packaging/DailyLife.spec --noconfirm --distpath dist --workpath build
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    # Só telas e estilos: nenhum dado pessoal (data/, token, credenciais) entra no pacote
    datas=[
        (os.path.join(ROOT, "dailylife", "templates"), "dailylife/templates"),
        (os.path.join(ROOT, "dailylife", "static"), "dailylife/static"),
        *collect_data_files("tzdata"),
        *collect_data_files("googleapiclient"),
    ],
    hiddenimports=["win11toast", "pystray._win32", *collect_submodules("winrt")],
    excludes=["tkinter", "pytest", "playwright", "ruff"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DailyLife",
    console=False,
    upx=False,
    icon=os.path.join(ROOT, "icon.ico"),
    version=os.path.join(SPECPATH, "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="DailyLife", upx=False)
