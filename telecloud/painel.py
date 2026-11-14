"""Painel de controle: uma janela comum (sem modais) com o estado e os botões principais.

Abre quando o usuário aciona o ícone da Área de Trabalho (ou a tecla de atalho dele) com o TeleCloud já aberto, ou
pelo menu da bandeja. Roda num processo à parte e conversa com o programa em execução por eventos do Windows e
pelo arquivo estado.json, porque o menu da bandeja nem sempre é fácil de acionar com leitor de tela.
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from . import sistema

log = logging.getLogger("telecloud")
REPO = "reffehcsoibaf/TeleCloud"
URL_ULTIMA = f"https://api.github.com/repos/{REPO}/releases/latest"


def mais_nova(tag: str, atual: str) -> bool:
    return sistema.versao_em_numeros(tag) > sistema.versao_em_numeros(atual)


def consultar_ultima() -> tuple[str, str]:
    """(versão, endereço do TeleCloud.exe) da última release do GitHub. Levanta exceção se não conseguir."""
    req = urllib.request.Request(URL_ULTIMA, headers={"User-Agent": "TeleCloud", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        dados = json.load(r)
    for a in dados.get("assets", []):
        if a.get("name", "").lower() == "telecloud.exe":
            return dados["tag_name"].lstrip("vV"), a["browser_download_url"]
    raise RuntimeError("A última versão não tem o TeleCloud.exe.")


def baixar(url: str, progresso=None) -> Path:
    """Baixa o .exe para uma pasta temporária nova e vazia."""
    pasta = Path(tempfile.mkdtemp(prefix="TeleCloud-atualizacao-"))
    destino = pasta / "TeleCloud.exe"
    req = urllib.request.Request(url, headers={"User-Agent": "TeleCloud"})
    with urllib.request.urlopen(req, timeout=30) as r, open(destino, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        feito = 0
        while True:
            bloco = r.read(256 * 1024)
            if not bloco:
                break
            f.write(bloco)
            feito += len(bloco)
            if progresso and total:
                progresso(feito, total)
    return destino


def ler_estado(dados: Path) -> str:
    """Texto de estado para a janela, a partir do estado.json do programa em execução."""
    if not sistema.instancia_ativa():
        return "O TeleCloud não está aberto."
    try:
        e = json.loads((Path(dados) / "estado.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "O TeleCloud está aberto."
    linhas = [e.get("texto", ""), f"Versão {e.get('versao', sistema.VERSAO)}. Unidade {e.get('unidade', '')}"]
    return "\n".join(l for l in linhas if l)


def abrir_painel(dados: Path):
    import wx
    from .login import _para_frente

    dados = Path(dados)
    app = wx.App(False)
    quadro = wx.Frame(None, title="TeleCloud - Painel de controle")
    fundo = wx.Panel(quadro)
    caixa = wx.BoxSizer(wx.VERTICAL)

    caixa.Add(wx.StaticText(fundo, label="Estado:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
    estado = wx.TextCtrl(fundo, value=ler_estado(dados), size=(460, 70), name="Estado do TeleCloud",
                         style=wx.TE_MULTILINE | wx.TE_READONLY)
    caixa.Add(estado, 0, wx.ALL | wx.EXPAND, 12)

    botoes = {}

    def botao(chave, rotulo, acao):
        b = wx.Button(fundo, label=rotulo)
        b.Bind(wx.EVT_BUTTON, lambda _e: acao())
        caixa.Add(b, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        botoes[chave] = b
        return b

    ultimo_aviso = [0.0]

    def avisar(texto):
        ultimo_aviso[0] = time.time()
        wx.CallAfter(estado.SetValue, texto)

    def abrir_unidade():
        try:
            e = json.loads((dados / "estado.json").read_text(encoding="utf-8"))
            os.startfile(e.get("unidade", "T:") + "\\")
        except Exception:
            avisar("Não consegui abrir a unidade. O TeleCloud está aberto?")

    def configuracoes():
        cmd = [sys.executable] if sistema.empacotado() else [sys.executable, os.path.abspath(sys.argv[0])]
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        subprocess.Popen(cmd + ["--configuracoes", "--dados", str(dados)], env=env, close_fds=True)

    nova = {"url": None, "versao": None}

    def verificar():
        botoes["verificar"].Disable()
        avisar("Verificando se há versão nova...")

        def tarefa():
            try:
                versao, url = consultar_ultima()
            except Exception as ex:
                avisar(f"Não consegui verificar agora: {ex}")
                wx.CallAfter(botoes["verificar"].Enable)
                return
            if mais_nova(versao, sistema.VERSAO):
                nova["url"], nova["versao"] = url, versao
                avisar(f"Há uma versão nova: {versao}. Você tem a {sistema.VERSAO}. "
                       "Use o botão Baixar e instalar a versão nova.")
                wx.CallAfter(botoes["instalar"].Show)
                wx.CallAfter(fundo.Layout)
                wx.CallAfter(botoes["instalar"].SetFocus)
            else:
                avisar(f"Você já está na versão mais recente ({sistema.VERSAO}).")
            wx.CallAfter(botoes["verificar"].Enable)
        threading.Thread(target=tarefa, daemon=True).start()

    def instalar():
        botoes["instalar"].Disable()

        def tarefa():
            try:
                exe = baixar(nova["url"], lambda f, t: avisar(f"Baixando a versão {nova['versao']}: {f * 100 // t}%"))
            except Exception as ex:
                avisar(f"Não consegui baixar: {ex}")
                wx.CallAfter(botoes["instalar"].Enable)
                return
            avisar("Atualizando. O TeleCloud vai fechar e abrir de novo.")
            subprocess.Popen([str(exe)], close_fds=True)   # o .exe novo troca a cópia instalada sozinho
            wx.CallAfter(quadro.Close)
        threading.Thread(target=tarefa, daemon=True).start()

    def desconectar():
        if sistema.acionar_evento(sistema.EVENTO_DESCONECTAR):
            avisar("Pedido enviado. Responda à pergunta que o TeleCloud vai mostrar.")
        else:
            avisar("O TeleCloud não está aberto, ou é de uma versão que não aceita este pedido.")

    def sair():
        if sistema.pedir_para_sair():
            avisar("Pedido enviado. O TeleCloud está fechando.")
            wx.CallLater(2500, quadro.Close)
        else:
            avisar("O TeleCloud não está aberto, ou é de uma versão que não aceita este pedido.")

    botao("unidade", "&Abrir a unidade", abrir_unidade)
    botao("config", "&Configurações", configuracoes)
    botao("verificar", "&Verificar atualizações", verificar)
    botao("instalar", "&Baixar e instalar a versão nova", instalar).Hide()
    botao("desconectar", "&Desconectar a conta do Telegram", desconectar)
    botao("sair", "&Sair do TeleCloud", sair)
    botao("fechar", "Fe&char esta janela", quadro.Close)

    fundo.SetSizerAndFit(caixa)
    quadro.SetClientSize(fundo.GetSize())

    def tecla(ev):
        if ev.GetKeyCode() == wx.WXK_ESCAPE:
            quadro.Close()
        else:
            ev.Skip()
    quadro.Bind(wx.EVT_CHAR_HOOK, tecla)

    relogio = wx.Timer(quadro)

    def atualizar_estado(_e):
        if time.time() - ultimo_aviso[0] < 30:
            return   # deixa a resposta da última ação à vista antes de voltar a mostrar o estado
        novo = ler_estado(dados)
        if novo != estado.GetValue():
            estado.SetValue(novo)
    quadro.Bind(wx.EVT_TIMER, atualizar_estado, relogio)
    relogio.Start(3000)

    quadro.CentreOnScreen()
    quadro.Show()
    botoes["unidade"].SetFocus()
    wx.CallAfter(_para_frente, quadro)
    app.MainLoop()
    app.Destroy()
