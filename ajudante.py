"""TeleCloudAjudante: publica a letra da unidade no espaço GLOBAL do Windows, para que ela apareça também nos
programas executados como administrador (o UAC dá a eles outra sessão de logon, que não vê as letras do usuário).

Roda como SYSTEM, iniciado pelo launcher do WinFsp (só o usuário autorizado no registro pode iniciá-lo):
    TeleCloudAjudante.exe LETRA: \\Device\\Volume{GUID} PID
Cria o vínculo LETRA: -> volume e o mantém enquanto o processo PID (o TeleCloud) existir; depois o remove.

Como roda com privilégio, desconfia de tudo o que recebe: só aceita letras de D: a Z: que ainda não existam
no espaço global e só alvos no formato \\Device\\Volume{GUID}. Não importa nenhum módulo do TeleCloud.
"""
import ctypes
import datetime
import os
import re
import sys

RAW_TARGET, REMOVE, EXACT = 0x1, 0x2, 0x4
SYNCHRONIZE = 0x00100000
INFINITO = 0xFFFFFFFF
RE_LETRA = re.compile(r"^[D-Z]:$")
RE_ALVO = re.compile(r"^\\Device\\Volume\{[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.DefineDosDeviceW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p]
k.QueryDosDeviceW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
k.OpenProcess.restype = ctypes.c_void_p
k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]


def registrar(texto: str):
    try:
        pasta = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "TeleCloud")
        os.makedirs(pasta, exist_ok=True)
        arq = os.path.join(pasta, "ajudante.log")
        if os.path.exists(arq) and os.path.getsize(arq) > 200_000:
            os.replace(arq, arq + ".antigo")
        with open(arq, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {texto}\n")
    except OSError:
        pass


def principal(argv) -> int:
    if len(argv) != 3:
        registrar(f"argumentos inválidos: {argv!r}")
        return 2
    letra, alvo, pid_texto = argv[0].upper(), argv[1], argv[2]
    if not RE_LETRA.match(letra) or not RE_ALVO.match(alvo) or not pid_texto.isdigit():
        registrar(f"recusado (formato): {argv!r}")
        return 2
    pid = int(pid_texto)
    existente = ctypes.create_unicode_buffer(1024)
    if k.QueryDosDeviceW(letra, existente, 1024):   # como SYSTEM, enxerga o espaço global
        registrar(f"recusado: {letra} já existe ({existente.value})")
        return 3
    if not k.DefineDosDeviceW(RAW_TARGET, letra, alvo):
        registrar(f"falhou ao criar {letra} -> {alvo}: erro {ctypes.get_last_error()}")
        return 4
    registrar(f"{letra} -> {alvo} (TeleCloud pid {pid})")
    h = k.OpenProcess(SYNCHRONIZE, False, pid)
    if h:
        k.WaitForSingleObject(h, INFINITO)          # espera o TeleCloud fechar (ou cair)
    k.DefineDosDeviceW(RAW_TARGET | REMOVE | EXACT, letra, alvo)
    registrar(f"{letra} removida")
    return 0


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
