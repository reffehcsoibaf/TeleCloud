"""Integração com o Windows: instância única, iniciar com o Windows, instalar/desinstalar, console e avisos."""
import ctypes
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

NOME = "TeleCloud"
CHAVE_INICIO = r"Software\Microsoft\Windows\CurrentVersion\Run"
CHAVE_DESINSTALAR = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\TeleCloud"
VERSAO = "2026.11.14.3"

MB_OK, MB_YESNO, MB_ICONINFO, MB_ICONERRO, MB_ICONPERGUNTA = 0x0, 0x4, 0x40, 0x10, 0x20
IDYES = 6


def empacotado() -> bool:
    return bool(getattr(sys, "frozen", False))


def pasta_dados() -> Path:
    """Dados do usuário: ao lado do código (desenvolvimento) ou em %APPDATA%\\TeleCloud (programa instalado)."""
    if os.environ.get("TELECLOUD_DADOS"):
        return Path(os.environ["TELECLOUD_DADOS"])
    if empacotado():
        return Path(os.environ.get("APPDATA", Path.home())) / NOME
    return Path(__file__).resolve().parent.parent / "dados"


def pasta_instalacao() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / NOME


def pasta_menu_iniciar() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / NOME


def aviso(texto: str, titulo=NOME, erro=False):
    ctypes.windll.user32.MessageBoxW(0, texto, titulo, MB_OK | (MB_ICONERRO if erro else MB_ICONINFO))


def perguntar(texto: str, titulo=NOME) -> bool:
    return ctypes.windll.user32.MessageBoxW(0, texto, titulo, MB_YESNO | MB_ICONPERGUNTA) == IDYES


# ---------- instância única ----------
_mutex = None


def ja_em_execucao() -> bool:
    """True se outro TeleCloud já está rodando (mantém um mutex nomeado enquanto este processo viver)."""
    global _mutex
    k = ctypes.windll.kernel32
    k.CreateMutexW.restype = ctypes.c_void_p
    _mutex = k.CreateMutexW(None, False, "Local\\TeleCloud-instancia-unica")
    return k.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def instancia_ativa() -> bool:
    """True se há um TeleCloud rodando (sem tomar o mutex)."""
    k = ctypes.windll.kernel32
    k.OpenMutexW.restype = ctypes.c_void_p
    h = k.OpenMutexW(0x00100000, False, "Local\\TeleCloud-instancia-unica")   # SYNCHRONIZE
    if h:
        k.CloseHandle(ctypes.c_void_p(h))
        return True
    return False


EVENTO_SAIR = "Local\\TeleCloud-pedido-de-saida"


def criar_evento_sair():
    """Evento que outra cópia do programa aciona para pedir que esta feche (atualização)."""
    k = ctypes.windll.kernel32
    k.CreateEventW.restype = ctypes.c_void_p
    return k.CreateEventW(None, True, False, EVENTO_SAIR)


def esperar_pedido_sair(evento) -> None:
    k = ctypes.windll.kernel32
    k.WaitForSingleObject(ctypes.c_void_p(evento), 0xFFFFFFFF)


EVENTO_DESCONECTAR = "Local\\TeleCloud-pedido-desconectar"


def acionar_evento(nome: str) -> bool:
    """Aciona um evento nomeado da cópia em execução. False se ela não o criou (versão antiga ou fechada)."""
    k = ctypes.windll.kernel32
    k.OpenEventW.restype = ctypes.c_void_p
    h = k.OpenEventW(0x0002, False, nome)    # EVENT_MODIFY_STATE
    if not h:
        return False
    k.SetEvent(ctypes.c_void_p(h))
    k.CloseHandle(ctypes.c_void_p(h))
    return True


def pedir_para_sair() -> bool:
    """Pede à cópia em execução que feche. False se ela não entende o pedido."""
    return acionar_evento(EVENTO_SAIR)


def criar_evento_desconectar():
    k = ctypes.windll.kernel32
    k.CreateEventW.restype = ctypes.c_void_p
    return k.CreateEventW(None, False, False, EVENTO_DESCONECTAR)   # rearma sozinho a cada pedido


def versao_em_numeros(texto: str) -> tuple:
    """'v2026.11.14.2' -> (2026, 11, 14, 2); '2026.11.9' -> (2026, 11, 9, 0). Para comparar versões."""
    partes = [int(p) for p in texto.strip().lstrip("vV").split(".") if p.isdigit()]
    return tuple((partes + [0, 0, 0, 0])[:4])


def esperar_encerrar(limite: float) -> bool:
    fim = time.time() + limite
    while instancia_ativa():
        if time.time() > fim:
            return False
        time.sleep(0.5)
    return True


def instalado_em_disco() -> bool:
    return (pasta_instalacao() / "TeleCloud.exe").exists()


# ---------- console (só para o login, que é feito por texto: funciona bem com leitor de tela) ----------
def garantir_console():
    if sys.stdin is not None and sys.stdin.isatty():
        return
    ctypes.windll.kernel32.AllocConsole()
    sys.stdin = open("CONIN$", "r", encoding="utf-8")
    sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    sys.stderr = sys.stdout
    ctypes.windll.kernel32.SetConsoleTitleW("TeleCloud - entrar")


def soltar_console():
    try:
        ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass


# ---------- iniciar com o Windows ----------
def comando_de_inicio() -> str:
    if empacotado():
        return f'"{sys.executable}"'
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    raiz = Path(__file__).resolve().parent.parent
    return f'"{pyw if pyw.exists() else py}" "{raiz / "montar.py"}"'


def inicio_ativo() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_INICIO) as k:
            winreg.QueryValueEx(k, NOME)
            return True
    except OSError:
        return False


def definir_inicio(ativo: bool):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_INICIO, 0, winreg.KEY_SET_VALUE) as k:
        if ativo:
            winreg.SetValueEx(k, NOME, 0, winreg.REG_SZ, comando_de_inicio())
        else:
            try:
                winreg.DeleteValue(k, NOME)
            except OSError:
                pass


# ---------- instalar / desinstalar (o próprio .exe faz isso; não precisa de instalador à parte) ----------
TECLA_ATALHO = "CTRL+ALT+T"   # tecla de atalho do ícone da Área de Trabalho: abre o painel de qualquer lugar


def pasta_area_de_trabalho() -> Path:
    """A Área de Trabalho do usuário (pode estar dentro do OneDrive)."""
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                       capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    texto = r.stdout.strip()
    return Path(texto) if texto else Path.home() / "Desktop"


def _atalho(caminho: Path, alvo: Path, tecla: str = ""):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{caminho}');"
          f"$s.TargetPath='{alvo}';$s.WorkingDirectory='{alvo.parent}';"
          + (f"$s.Hotkey='{tecla}';" if tecla else "") + "$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def esta_instalado() -> bool:
    return empacotado() and Path(sys.executable).resolve().parent == pasta_instalacao().resolve()


def instalar(iniciar_com_windows: bool) -> Path:
    import winreg
    dest = pasta_instalacao()
    dest.mkdir(parents=True, exist_ok=True)
    exe = dest / "TeleCloud.exe"
    for tentativa in range(20):    # o Windows demora um instante para soltar o .exe de uma cópia que acabou de fechar
        try:
            shutil.copy2(sys.executable, exe)
            break
        except PermissionError:
            if tentativa == 19:
                raise
            time.sleep(0.5)
    _atalho(pasta_menu_iniciar() / "TeleCloud.lnk", exe)
    try:
        _atalho(pasta_area_de_trabalho() / "TeleCloud.lnk", exe, TECLA_ATALHO)
    except Exception:
        pass   # o ícone da Área de Trabalho é um conforto; a instalação não falha por causa dele
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CHAVE_DESINSTALAR) as k:
        for nome, valor in {
            "DisplayName": "TeleCloud", "DisplayVersion": VERSAO, "Publisher": "TeleCloud",
            "InstallLocation": str(dest), "DisplayIcon": str(exe),
            "UninstallString": f'"{exe}" --desinstalar',
        }.items():
            winreg.SetValueEx(k, nome, 0, winreg.REG_SZ, valor)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
    if iniciar_com_windows:
        # o comando de início aponta para a cópia instalada, não para o arquivo baixado
        import winreg as w
        with w.OpenKey(w.HKEY_CURRENT_USER, CHAVE_INICIO, 0, w.KEY_SET_VALUE) as k:
            w.SetValueEx(k, NOME, 0, w.REG_SZ, f'"{exe}"')
    return exe


def desinstalar(apagar_dados: bool):
    """Remove tudo o que a instalação criou fora da pasta de dados; a pasta do programa sai logo após o fim."""
    import winreg
    definir_inicio(False)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, CHAVE_DESINSTALAR)
    except OSError:
        pass
    shutil.rmtree(pasta_menu_iniciar(), ignore_errors=True)
    try:
        (pasta_area_de_trabalho() / "TeleCloud.lnk").unlink(missing_ok=True)
    except OSError:
        pass
    if apagar_dados:
        shutil.rmtree(pasta_dados(), ignore_errors=True)
    # o .exe em uso não se apaga a si mesmo: um cmd espera este processo terminar e remove a pasta
    dest = pasta_instalacao()
    subprocess.Popen(
        f'cmd /c ping -n 4 127.0.0.1 >nul & rmdir /s /q "{dest}"',
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)


# ---------- WinFsp (driver da unidade) ----------
def dll_winfsp() -> Path:
    base = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    return Path(base) / "WinFsp" / "bin" / "winfsp-x64.dll"


def winfsp_instalado() -> bool:
    return dll_winfsp().exists()


def instalador_winfsp():
    """Caminho do .msi que vai dentro do .exe (None se não estiver empacotado)."""
    pasta = Path(getattr(sys, "_MEIPASS", ""))
    achados = sorted(pasta.glob("winfsp-*.msi")) if getattr(sys, "frozen", False) else []
    return achados[-1] if achados else None


def instalar_winfsp() -> bool:
    """Roda o instalador embutido, pedindo permissão de administrador. Devolve True se o driver ficou instalado."""
    msi = instalador_winfsp()
    if msi is None:
        return False

    class INFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("fMask", ctypes.c_ulong), ("hwnd", ctypes.c_void_p),
                    ("lpVerb", ctypes.c_wchar_p), ("lpFile", ctypes.c_wchar_p),
                    ("lpParameters", ctypes.c_wchar_p), ("lpDirectory", ctypes.c_wchar_p),
                    ("nShow", ctypes.c_int), ("hInstApp", ctypes.c_void_p), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", ctypes.c_wchar_p), ("hkeyClass", ctypes.c_void_p), ("dwHotKey", ctypes.c_ulong),
                    ("hIcon", ctypes.c_void_p), ("hProcess", ctypes.c_void_p)]

    info = INFO()
    info.cbSize = ctypes.sizeof(INFO)
    info.fMask = 0x40                      # SEE_MASK_NOCLOSEPROCESS: para esperar o fim
    info.lpVerb = "runas"                  # pede a permissão de administrador (UAC)
    info.lpFile = "msiexec.exe"
    info.lpParameters = f'/i "{msi}" /passive /norestart'
    info.nShow = 1
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return False                       # o usuário recusou a permissão
    ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
    ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return winfsp_instalado()
