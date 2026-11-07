"""Login do TeleCloud numa janela: telefone, código do site, código do app e senha (se houver).

`Fluxo` guarda a lógica (sem tela, para poder testar); `abrir_janela` é a tela em tkinter.
"""
import json
import logging
from pathlib import Path

from .credenciais import ErroCredenciais, MyTelegram

log = logging.getLogger("telecloud")
PRONTO = "pronto"


class Fluxo:
    """Cada passo_* recebe o que o usuário digitou e devolve o nome do próximo passo.
    Erros de uso viram ErroCredenciais, com texto para mostrar; o passo continua o mesmo."""

    def __init__(self, dados: Path, site=None, fabrica_arm=None):
        self.dados = Path(dados)
        self.cfg_arq = self.dados / "config.json"
        self.site = site or MyTelegram()
        if fabrica_arm is None:
            from .telegram import TelegramArmazenamento as fabrica_arm
        self._fabrica = fabrica_arm
        self.arm = None
        self.telefone = None

    def _cfg(self) -> dict:
        return json.loads(self.cfg_arq.read_text(encoding="utf-8-sig")) if self.cfg_arq.exists() else {}

    def _tem_chaves(self) -> bool:
        c = self._cfg()
        return bool(c.get("api_id") and c.get("api_hash"))

    def passo_telefone(self, telefone: str) -> str:
        telefone = telefone.strip().replace(" ", "")
        if not telefone.startswith("+") or not telefone[1:].isdigit():
            raise ErroCredenciais("Digite o telefone com + e o código do país, por exemplo +5511999999999.")
        self.telefone = telefone
        if self._tem_chaves():
            return self._pedir_codigo_do_app()
        self.site.enviar_codigo(telefone)
        return "codigo_site"

    def passo_codigo_site(self, codigo: str) -> str:
        self.site.entrar(codigo.strip())
        api_id, api_hash = self.site.obter_ou_criar()
        cfg = self._cfg()
        cfg["api_id"], cfg["api_hash"] = api_id, api_hash
        self.dados.mkdir(parents=True, exist_ok=True)
        self.cfg_arq.write_text(json.dumps(cfg), encoding="utf-8")
        return self._pedir_codigo_do_app()

    def _pedir_codigo_do_app(self) -> str:
        from telethon.errors import FloodWaitError, PhoneNumberInvalidError
        if self.arm is None:
            self.arm = self._fabrica(self.dados)
        try:
            self.arm._rodar(self.arm.client.connect())
            if self.arm._rodar(self.arm.client.is_user_authorized()):
                return PRONTO
            self.arm._rodar(self.arm.client.send_code_request(self.telefone))
        except PhoneNumberInvalidError:
            raise ErroCredenciais("O Telegram não reconheceu esse telefone.")
        except FloodWaitError as e:
            raise ErroCredenciais(f"Muitos pedidos de código. Espere {e.seconds} segundos.")
        return "codigo_app"

    def passo_codigo_app(self, codigo: str) -> str:
        from telethon.errors import (PhoneCodeExpiredError, PhoneCodeInvalidError,
                                     SessionPasswordNeededError)
        try:
            self.arm._rodar(self.arm.client.sign_in(self.telefone, codigo.strip()))
        except PhoneCodeInvalidError:
            raise ErroCredenciais("Código incorreto.")
        except PhoneCodeExpiredError:
            raise ErroCredenciais("O código expirou. Feche e abra o TeleCloud para pedir outro.")
        except SessionPasswordNeededError:
            return "senha"
        return PRONTO

    def passo_senha(self, senha: str) -> str:
        from telethon.errors import PasswordHashInvalidError
        try:
            self.arm._rodar(self.arm.client.sign_in(password=senha))
        except PasswordHashInvalidError:
            raise ErroCredenciais("Senha incorreta.")
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


# Texto de cada passo: (título, instrução, rótulo do campo, secreto?)
PASSOS = {
    "telefone": ("Entrar no Telegram",
                 "Digite o telefone da sua conta, com + e o código do país.", "Telefone:", False),
    "codigo_site": ("Código 1 de 2",
                    "O Telegram enviou um código para o app da sua conta. Digite-o aqui para o TeleCloud "
                    "cadastrar (ou buscar) as chaves de acesso dele em my.telegram.org.", "Código:", False),
    "codigo_app": ("Código 2 de 2",
                   "O Telegram enviou outro código, agora para entrar com o TeleCloud. Digite-o.",
                   "Código:", False),
    "senha": ("Verificação em duas etapas", "Digite a senha da sua conta do Telegram.", "Senha:", True),
}


def _pedir(wx, passo: str, erro: str = ""):
    """Uma caixa de diálogo por passo, só com controles nativos (o leitor de tela lê o título, o texto
    e o rótulo ao abrir). Devolve o texto digitado ou None se cancelou."""
    titulo, instrucao, rotulo, secreto = PASSOS[passo]
    dlg = wx.Dialog(None, title="TeleCloud - " + titulo)
    caixa = wx.BoxSizer(wx.VERTICAL)
    texto = wx.StaticText(dlg, label=instrucao)
    texto.Wrap(380)
    caixa.Add(texto, 0, wx.ALL, 12)
    nome = wx.StaticText(dlg, label=rotulo)   # vem logo antes do campo: o NVDA usa como nome dele
    caixa.Add(nome, 0, wx.LEFT | wx.RIGHT, 12)
    campo = wx.TextCtrl(dlg, style=wx.TE_PASSWORD if secreto else 0, size=(380, -1), name=rotulo.rstrip(":"))
    caixa.Add(campo, 0, wx.ALL | wx.EXPAND, 12)
    botoes = dlg.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
    dlg.FindWindowById(wx.ID_OK).SetLabel("Continuar")
    dlg.FindWindowById(wx.ID_CANCEL).SetLabel("Cancelar")
    caixa.Add(botoes, 0, wx.ALL | wx.ALIGN_RIGHT, 12)
    dlg.SetSizerAndFit(caixa)
    dlg.SetAffirmativeId(wx.ID_OK)
    dlg.SetEscapeId(wx.ID_CANCEL)
    dlg.FindWindowById(wx.ID_OK).SetDefault()
    dlg.CentreOnScreen()
    campo.SetFocus()
    try:
        if dlg.ShowModal() != wx.ID_OK:
            return None
        return campo.GetValue()
    finally:
        dlg.Destroy()


def abrir_janela(dados: Path) -> bool:
    """Mostra o login, um passo por vez. Devolve True se entrou."""
    import wx

    app = wx.App(False)
    fluxo = Fluxo(dados)
    passo = "telefone"
    erro = ""
    ok = False
    while True:
        if erro:
            wx.MessageBox(erro, "TeleCloud", wx.OK | wx.ICON_ERROR)
        texto = _pedir(wx, passo, erro)
        if texto is None:
            break
        if not texto.strip():
            erro = "Digite o valor pedido."
            continue
        try:
            with wx.BusyCursor():
                if passo == "telefone":
                    prox = fluxo.passo_telefone(texto)
                elif passo == "codigo_site":
                    prox = fluxo.passo_codigo_site(texto)
                elif passo == "codigo_app":
                    prox = fluxo.passo_codigo_app(texto)
                else:
                    prox = fluxo.passo_senha(texto)
                if prox == PRONTO:
                    fluxo.finalizar()
        except ErroCredenciais as e:
            log.warning("login, passo %s: %s", passo, e)
            erro = str(e)
            continue
        except Exception as e:  # erro inesperado
            log.exception("login, passo %s", passo): mostra e deixa tentar de novo
            erro = f"{type(e).__name__}: {e}"
            continue
        erro = ""
        if prox == PRONTO:
            ok = True
            break
        passo = prox
    if not ok:
        fluxo.cancelar()
    app.Destroy()
    return ok
