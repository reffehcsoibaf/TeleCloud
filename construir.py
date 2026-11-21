"""Gera dist/TeleCloud.exe (um arquivo só, que também é o instalador). Uso: venv\\Scripts\\python construir.py"""
import subprocess
import sys
from pathlib import Path

from telecloud.bandeja import ICONES, _icone

raiz = Path(__file__).parent
ico = raiz / "build" / "telecloud.ico"
ico.parent.mkdir(exist_ok=True)
_icone(ICONES["ok"]).save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])

msi = sorted((raiz / "build").glob("winfsp-*.msi"))
if not msi:
    sys.exit("Falta o instalador do WinFsp em build/. Baixe: gh release download v2.1 -R winfsp/winfsp -p '*.msi' -D build")

# Ajudante que roda como SYSTEM (letra da unidade visível para programas elevados). Só usa a biblioteca padrão.
pasta_ajudante = raiz / "build" / "ajudante"
subprocess.run(
    [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--noconsole",
     "--name", "TeleCloudAjudante", "--exclude-module", "tkinter",
     "--distpath", str(pasta_ajudante), "--workpath", str(raiz / "build" / "pyi-ajudante"),
     "--specpath", str(raiz / "build"), str(raiz / "ajudante.py")],
    check=True)

subprocess.run(
    [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--noconsole",
     "--name", "TeleCloud", "--add-data", f"{msi[-1]};.",
     "--add-data", f"{pasta_ajudante / 'TeleCloudAjudante.exe'};.", "--icon", str(ico), "--hidden-import", "pystray._win32", "--hidden-import", "cryptg", "--exclude-module", "tkinter",
     "--distpath", str(raiz / "dist"), "--workpath", str(raiz / "build" / "pyi"),
     "--specpath", str(raiz / "build"), str(raiz / "montar.py")],
    check=True)
print("Pronto:", raiz / "dist" / "TeleCloud.exe")
