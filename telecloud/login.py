"""Login do TeleCloud numa janela: telefone, código do site, código do app e senha (se houver).

`Fluxo` guarda a lógica (sem tela, para poder testar); `abrir_janela` é a tela em tkinter.
"""
import json
import queue
import threading
from pathlib import Path

from .credenciais import ErroCredenciais, MyTelegram

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


def abrir_janela(dados: Path) -> bool:
    """Mostra a janela de login. Devolve True se entrou."""
    import tkinter as tk
    from tkinter import ttk

    fluxo = Fluxo(dados)
    resultado = {"ok": False}
    fila = queue.Queue()
    estado = {"passo": "telefone", "ocupado": False}

    raiz = tk.Tk()
    raiz.title("TeleCloud")
    raiz.resizable(False, False)
    quadro = ttk.Frame(raiz, padding=18)
    quadro.grid()
    titulo = ttk.Label(quadro, font=("Segoe UI", 13, "bold"))
    titulo.grid(sticky="w")
    instrucao = ttk.Label(quadro, wraplength=380, justify="left")
    instrucao.grid(sticky="w", pady=(6, 10))
    rotulo = ttk.Label(quadro)
    rotulo.grid(sticky="w")
    valor = tk.StringVar()
    campo = ttk.Entry(quadro, textvariable=valor, width=40)
    campo.grid(sticky="we", pady=(2, 6))
    msg = ttk.Label(quadro, foreground="#b00020", wraplength=380, justify="left")
    msg.grid(sticky="w")
    botoes = ttk.Frame(quadro)
    botoes.grid(sticky="e", pady=(10, 0))
    continuar = ttk.Button(botoes, text="Continuar")
    continuar.grid(row=0, column=0, padx=(0, 6))
    cancelar = ttk.Button(botoes, text="Cancelar", command=raiz.destroy)
    cancelar.grid(row=0, column=1)

    def mostrar(passo, erro=""):
        estado["passo"] = passo
        t, i, r, secreto = PASSOS[passo]
        raiz.title("TeleCloud - " + t)
        titulo.config(text=t)
        instrucao.config(text=i)
        rotulo.config(text=r)
        campo.config(show="*" if secreto else "")
        msg.config(text=erro)
        valor.set("")
        campo.focus_set()

    def ocupar(sim):
        estado["ocupado"] = sim
        continuar.config(state="disabled" if sim else "normal")
        campo.config(state="disabled" if sim else "normal")
        if sim:
            msg.config(text="Aguarde...", foreground="#444")
        else:
            msg.config(foreground="#b00020")

    def trabalho(passo, texto):
        try:
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
            fila.put((passo, prox, ""))
        except ErroCredenciais as e:
            fila.put((passo, passo, str(e)))
        except Exception as e:  # erro inesperado: mostra e deixa tentar de novo
            fila.put((passo, passo, f"{type(e).__name__}: {e}"))

    def enviar(_evento=None):
        if estado["ocupado"] or not valor.get().strip():
            return
        ocupar(True)
        threading.Thread(target=trabalho, args=(estado["passo"], valor.get()), daemon=True).start()

    def olhar_fila():
        try:
            while True:
                _, prox, erro = fila.get_nowait()
                ocupar(False)
                if prox == PRONTO:
                    resultado["ok"] = True
                    raiz.destroy()
                    return
                mostrar(prox, erro)
        except queue.Empty:
            pass
        raiz.after(100, olhar_fila)

    continuar.config(command=enviar)
    raiz.bind("<Return>", enviar)
    mostrar("telefone")
    raiz.update_idletasks()
    raiz.geometry("+%d+%d" % ((raiz.winfo_screenwidth() - raiz.winfo_reqwidth()) // 2,
                              (raiz.winfo_screenheight() - raiz.winfo_reqheight()) // 3))
    raiz.attributes("-topmost", True)
    raiz.after(100, olhar_fila)
    raiz.mainloop()
    if not resultado["ok"]:
        fluxo.cancelar()
    return resultado["ok"]
