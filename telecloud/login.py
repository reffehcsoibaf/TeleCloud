"""Login do TeleCloud em caixas de diálogo nativas (acessíveis ao leitor de tela), um passo por vez:
chaves da API (se ainda não existem) -> telefone -> código recebido -> senha (se houver).

`Fluxo` guarda a lógica (sem tela, para poder testar); `abrir_janela` mostra os diálogos.
"""
import json
import logging
import re
from pathlib import Path

log = logging.getLogger("telecloud")
PRONTO = "pronto"
SITE = "https://my.telegram.org"


class ErroLogin(Exception):
    """Mensagem já pronta para mostrar ao usuário."""


class Fluxo:
    """Cada passo_* recebe o que o usuário digitou e devolve o nome do próximo passo.
    Erros de uso viram ErroLogin, com texto para mostrar; o passo continua o mesmo."""

    def __init__(self, dados: Path, fabrica_arm=None):
        self.dados = Path(dados)
        self.cfg_arq = self.dados / "config.json"
        if fabrica_arm is None:
            from .telegram import TelegramArmazenamento as fabrica_arm
        self._fabrica = fabrica_arm
        self.arm = None
        self.telefone = None

    def _cfg(self) -> dict:
        return json.loads(self.cfg_arq.read_text(encoding="utf-8-sig")) if self.cfg_arq.exists() else {}

    def tem_chaves(self) -> bool:
        c = self._cfg()
        return bool(c.get("api_id") and c.get("api_hash"))

    def passo_chaves(self, api_id: str, api_hash: str) -> str:
        api_id, api_hash = api_id.strip(), api_hash.strip().lower()
        if not api_id.isdigit():
            raise ErroLogin("O api_id tem só números. Confira o que você colou.")
        if not re.fullmatch(r"[0-9a-f]{32}", api_hash):
            raise ErroLogin("O api_hash tem 32 letras e números (de 0 a 9 e de a até f). Confira o que você colou.")
        cfg = self._cfg()
        cfg["api_id"], cfg["api_hash"] = int(api_id), api_hash
        self.dados.mkdir(parents=True, exist_ok=True)
        self.cfg_arq.write_text(json.dumps(cfg), encoding="utf-8")
        return "telefone"

    def passo_telefone(self, telefone: str) -> str:
        from telethon.errors import ApiIdInvalidError, FloodWaitError, PhoneNumberInvalidError
        telefone = telefone.strip().replace(" ", "").replace("-", "")
        if not telefone.startswith("+") or not telefone[1:].isdigit():
            raise ErroLogin("Digite o telefone com + e o código do país, por exemplo +5511999999999.")
        self.telefone = telefone
        if self.arm is None:
            self.arm = self._fabrica(self.dados)
        try:
            self.arm._rodar(self.arm.client.connect())
            if self.arm._rodar(self.arm.client.is_user_authorized()):
                return PRONTO
            self.arm._rodar(self.arm.client.send_code_request(telefone))
        except ApiIdInvalidError:
            self.cancelar()
            raise ErroLogin("O Telegram não aceitou as chaves (api_id e api_hash). Confira-as.")
        except PhoneNumberInvalidError:
            raise ErroLogin("O Telegram não reconheceu esse telefone.")
        except FloodWaitError as e:
            raise ErroLogin(f"Muitos pedidos de código. Espere {e.seconds} segundos.")
        return "codigo"

    def passo_codigo(self, codigo: str) -> str:
        from telethon.errors import (PhoneCodeExpiredError, PhoneCodeInvalidError,
                                     SessionPasswordNeededError)
        try:
            self.arm._rodar(self.arm.client.sign_in(self.telefone, codigo.strip()))
        except PhoneCodeInvalidError:
            raise ErroLogin("Código incorreto.")
        except PhoneCodeExpiredError:
            raise ErroLogin("O código expirou. Cancele e abra o TeleCloud de novo para pedir outro.")
        except SessionPasswordNeededError:
            return "senha"
        return PRONTO

    def passo_senha(self, senha: str) -> str:
        from telethon.errors import PasswordHashInvalidError
        try:
            self.arm._rodar(self.arm.client.sign_in(password=senha))
        except PasswordHashInvalidError:
            raise ErroLogin("Senha incorreta.")
        return PRONTO

    def finalizar(self):
        """Cria/acha o grupo de armazenamento e solta a conexão."""
        self.arm.conectar()
        self.arm.fechar()
        self.arm = None

    def cancelar(self):
        if self.arm is not None:
            try:
                self.arm.fechar()
            except Exception:
                pass
            self.arm = None


# Texto de cada passo: (título, instrução, [(rótulo do campo, secreto?)])
PASSOS = {
    "intro": ("Chaves de acesso",
              "Para entrar, o TeleCloud precisa de duas chaves da sua conta do Telegram: api_id e api_hash. "
              "Você as cria uma vez só, grátis.\n\n"
              "1. Ative o botão Abrir my.telegram.org. O site abre no navegador.\n"
              "2. Entre com o seu telefone e o código que o Telegram enviar.\n"
              "3. Escolha API development tools e crie um aplicativo. O nome pode ser TeleCloud.\n"
              "4. Copie o api_id e o api_hash.\n"
              "5. Volte aqui e ative Já tenho as chaves.", []),
    "chaves": ("Colar as chaves", "Cole as chaves que o site mostrou.",
               [("api_id", False), ("api_hash", False)]),
    "telefone": ("Entrar no Telegram",
                 "Digite o telefone da sua conta, com + e o código do país.", [("Telefone", False)]),
    "codigo": ("Código recebido",
               "O Telegram enviou um código para o app da sua conta. Digite-o.", [("Código", False)]),
    "senha": ("Verificação em duas etapas", "Digite a senha da sua conta do Telegram.", [("Senha", True)]),
}


def _para_frente(dlg):
    """Traz o diálogo para o primeiro plano: sem isso o Windows o abre atrás e o leitor de tela não o anuncia."""
    import ctypes
    try:
        dlg.Raise()
        u = ctypes.windll.user32
        u.keybd_event(0x12, 0, 0, 0)      # um toque em Alt libera o SetForegroundWindow
        u.keybd_event(0x12, 0, 2, 0)
        u.SetForegroundWindow(dlg.GetHandle())
    except Exception:
        log.exception("não consegui trazer a janela para a frente")


def _pedir(wx, passo: str, erro: str = ""):
    """Um diálogo por passo, só com controles nativos. Devolve a lista de textos digitados ([] no passo
    de botões) ou None se cancelou. O erro do passo anterior vem no começo do texto, que o leitor de tela lê."""
    titulo, instrucao, campos = PASSOS[passo]
    dlg = wx.Dialog(None, title="TeleCloud - " + titulo,
                    style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP)
    caixa = wx.BoxSizer(wx.VERTICAL)
    texto = wx.StaticText(dlg, label=(f"Erro: {erro}\n\n" if erro else "") + instrucao)
    texto.Wrap(420)
    caixa.Add(texto, 0, wx.ALL, 12)
    entradas = []
    for rotulo, secreto in campos:
        nome = wx.StaticText(dlg, label=rotulo + ":")   # logo antes do campo: o NVDA usa como nome dele
        caixa.Add(nome, 0, wx.LEFT | wx.RIGHT, 12)
        campo = wx.TextCtrl(dlg, style=wx.TE_PASSWORD if secreto else 0, size=(420, -1), name=rotulo)
        caixa.Add(campo, 0, wx.ALL | wx.EXPAND, 12)
        entradas.append(campo)
    linha = wx.BoxSizer(wx.HORIZONTAL)
    if passo == "intro":
        import webbrowser
        abrir = wx.Button(dlg, label="Abrir my.telegram.org")
        abrir.Bind(wx.EVT_BUTTON, lambda _e: webbrowser.open(SITE))
        linha.Add(abrir, 0, wx.RIGHT, 8)
        ok = wx.Button(dlg, wx.ID_OK, "Já tenho as chaves")
    else:
        ok = wx.Button(dlg, wx.ID_OK, "Continuar")
    cancelar = wx.Button(dlg, wx.ID_CANCEL, "Cancelar")
    linha.Add(ok, 0, wx.RIGHT, 8)
    linha.Add(cancelar, 0)
    caixa.Add(linha, 0, wx.ALL | wx.ALIGN_RIGHT, 12)
    dlg.SetSizerAndFit(caixa)
    dlg.SetAffirmativeId(wx.ID_OK)
    dlg.SetEscapeId(wx.ID_CANCEL)
    ok.SetDefault()
    dlg.CentreOnScreen()
    (entradas[0] if entradas else ok).SetFocus()
    wx.CallAfter(_para_frente, dlg)
    try:
        if dlg.ShowModal() != wx.ID_OK:
            return None
        return [c.GetValue() for c in entradas]
    finally:
        dlg.Destroy()


def abrir_janela(dados: Path) -> bool:
    """Mostra o login, um passo por vez. Devolve True se entrou."""
    import wx

    app = wx.App(False)
    fluxo = Fluxo(dados)
    passo = "telefone" if fluxo.tem_chaves() else "intro"
    erro = ""
    ok = False
    while True:
        valores = _pedir(wx, passo, erro)
        if valores is None:
            break
        erro = ""
        if passo == "intro":
            passo = "chaves"
            continue
        if any(not v.strip() for v in valores):
            erro = "Preencha o campo."
            continue
        try:
            with wx.BusyCursor():
                prox = getattr(fluxo, "passo_" + passo)(*valores)
                if prox == PRONTO:
                    fluxo.finalizar()
        except ErroLogin as e:
            log.warning("login, passo %s: %s", passo, e)
            erro = str(e)
            if "chaves" in erro and passo == "telefone":
                passo = "chaves"
            continue
        except Exception as e:  # erro inesperado: mostra e deixa tentar de novo
            log.exception("login, passo %s", passo)
            erro = f"{type(e).__name__}: {e}"
            continue
        if prox == PRONTO:
            ok = True
            break
        passo = prox
    if not ok:
        fluxo.cancelar()
    app.Destroy()
    return ok
