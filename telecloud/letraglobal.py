"""Letra da unidade visível também para programas executados como administrador.

Com o UAC, um programa elevado usa outra sessão de logon e não enxerga as letras criadas na sessão do usuário. A
letra comum (criada pelo WinFsp) continua existindo; este módulo pede a um ajudante com privilégio de sistema
(TeleCloudAjudante.exe, iniciado pelo launcher do WinFsp) que crie o mesmo vínculo no espaço global. O ajudante
remove o vínculo quando este processo termina.

Registro (uma vez, com permissão de administrador): copia o ajudante para Arquivos de Programas (o SYSTEM não pode
executar nada de uma pasta que o usuário consiga alterar) e o cadastra no launcher, liberando só este usuário.
"""
import ctypes
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import sistema

log = logging.getLogger("telecloud")

SERVICO = "TeleCloudLetra"
CHAVE = r"SOFTWARE\WinFsp\Services\TeleCloudLetra"
NOME_EXE = "TeleCloudAjudante.exe"


def pasta_ajudante() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "TeleCloud"


def _launchctl() -> Path:
    base = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    return Path(base) / "WinFsp" / "bin" / "launchctl-x64.exe"


def _chave(acesso):
    import winreg
    return winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CHAVE, 0, acesso | winreg.KEY_WOW64_32KEY)


def registrado() -> bool:
    """True se o ajudante está copiado e cadastrado no launcher."""
    import winreg
    try:
        with _chave(winreg.KEY_READ) as k:
            exe, _ = winreg.QueryValueEx(k, "Executable")
        return Path(exe).exists()
    except OSError:
        return False


def _exe_embutido() -> Path | None:
    """O ajudante que vai dentro do .exe (ou, no desenvolvimento, o que construir.py gerou)."""
    if sistema.empacotado():
        p = Path(getattr(sys, "_MEIPASS", "")) / NOME_EXE
    else:
        p = Path(__file__).resolve().parent.parent / "build" / "ajudante" / NOME_EXE
    return p if p.exists() else None


def _sid_do_usuario() -> str:
    saida = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True,
                           creationflags=subprocess.CREATE_NO_WINDOW).stdout
    return saida.strip().split(",")[-1].strip().strip('"')


def pedir_registro() -> bool:
    """Pede (com a permissão de administrador do Windows) para registrar o ajudante. True se ficou registrado."""
    if not sistema.winfsp_instalado():
        return False
    sid = _sid_do_usuario()
    if not sid.startswith("S-1-"):
        return False
    argumentos = ["--registrar-ajudante", sid]
    if sistema.empacotado():
        sistema.executar_como_admin(sys.executable, argumentos)
    else:
        raiz = Path(__file__).resolve().parent.parent
        sistema.executar_como_admin(sys.executable, [str(raiz / "montar.py"), *argumentos])
    return registrado()


def registrar(sid: str) -> int:
    """Roda elevado (--registrar-ajudante SID). Devolve o código de saída."""
    import winreg
    if not sid.startswith("S-1-") or any(c not in "S-0123456789" for c in sid):
        return 2
    origem = _exe_embutido()
    if origem is None or not sistema.winfsp_instalado():
        return 3
    pasta = pasta_ajudante()
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / NOME_EXE
    shutil.copy2(origem, destino)
    chave = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, CHAVE, 0,
                               winreg.KEY_WRITE | winreg.KEY_WOW64_32KEY)
    with chave:
        winreg.SetValueEx(chave, "Executable", 0, winreg.REG_SZ, str(destino))
        winreg.SetValueEx(chave, "CommandLine", 0, winreg.REG_SZ, "%1 %2 %3")
        winreg.SetValueEx(chave, "JobControl", 0, winreg.REG_DWORD, 1)
        # só este usuário pode iniciar o ajudante (sem RunAs: roda como SYSTEM)
        winreg.SetValueEx(chave, "Security", 0, winreg.REG_SZ, f"D:P(A;;RPWPLC;;;{sid})")
    return 0


def remover_registro() -> int:
    """Roda elevado (--remover-ajudante): tira do launcher e apaga o arquivo."""
    import winreg
    try:
        winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, CHAVE, winreg.KEY_WOW64_32KEY, 0)
    except OSError:
        pass
    shutil.rmtree(pasta_ajudante(), ignore_errors=True)
    return 0


def pedir_remocao() -> bool:
    if not registrado():
        return True
    if sistema.empacotado():
        sistema.executar_como_admin(sys.executable, ["--remover-ajudante"])
    else:
        raiz = Path(__file__).resolve().parent.parent
        sistema.executar_como_admin(sys.executable, [str(raiz / "montar.py"), "--remover-ajudante"])
    return not registrado()


def _alvo_da_letra(letra: str) -> str | None:
    k = ctypes.WinDLL("kernel32")
    k.QueryDosDeviceW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    buf = ctypes.create_unicode_buffer(1024)
    return buf.value if k.QueryDosDeviceW(letra, buf, 1024) else None


def _launchctl_run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([str(_launchctl()), *args], capture_output=True, text=True, timeout=30,
                          creationflags=subprocess.CREATE_NO_WINDOW)


def publicar(letra: str) -> bool:
    """Torna `letra` (já montada pelo WinFsp nesta sessão) visível para todos. False se não deu (a letra comum
    continua funcionando)."""
    try:
        if not registrado():
            log.info("letra global: ajudante não registrado")
            return False
        alvo = _alvo_da_letra(letra)
        if not alvo or not alvo.startswith("\\Device\\Volume{"):
            log.warning("letra global: alvo inesperado para %s: %r", letra, alvo)
            return False
        _launchctl_run("stop", SERVICO, letra[0])
        r = _launchctl_run("start", SERVICO, letra[0], letra, alvo, str(os.getpid()))
        ok = r.returncode == 0 and "OK" in r.stdout
        log.info("letra global %s -> %s: %s %s", letra, alvo, "ok" if ok else "FALHOU", (r.stdout + r.stderr).strip())
        return ok
    except Exception:
        log.exception("letra global")
        return False


def despublicar(letra: str):
    """Pede ao ajudante que remova o vínculo (ele também o remove sozinho quando este processo termina)."""
    try:
        if registrado():
            _launchctl_run("stop", SERVICO, letra[0])
    except Exception:
        log.exception("letra global (parar)")
