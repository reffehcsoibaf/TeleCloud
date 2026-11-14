"""Janela de configurações (controles nativos, acessível ao leitor de tela).

Roda num processo à parte (`TeleCloud --configuracoes`), porque a janela wx e o ícone da bandeja não convivem
bem no mesmo processo. Grava no config.json; o programa em execução relê o arquivo quando a janela fecha.
"""
import json
import logging
from pathlib import Path

from . import sistema

log = logging.getLogger("telecloud")
PADRAO_CACHE_MB = 5120
MIN_CACHE_MB = 512
MAX_PAUSA_S = 60


class ErroConfig(Exception):
    """Mensagem já pronta para mostrar ao usuário."""


def ler(dados: Path) -> dict:
    arq = Path(dados) / "config.json"
    return json.loads(arq.read_text(encoding="utf-8-sig")) if arq.exists() else {}


def cache_max_bytes(dados: Path) -> int:
    return int(float(ler(dados).get("cache_max_mb", PADRAO_CACHE_MB)) * 1024 * 1024)


def pausa_envios_s(dados: Path) -> float:
    try:
        return max(0.0, min(float(ler(dados).get("pausa_envios_s", 0)), MAX_PAUSA_S))
    except (TypeError, ValueError):
        return 0.0


def interpretar_pausa(texto: str) -> float:
    """'0', '1,5' ou '1.5' (segundos) -> segundos. Vazio vale 0 (sem pausa)."""
    texto = texto.strip().replace(",", ".")
    if not texto:
        return 0.0
    try:
        s = float(texto)
    except ValueError:
        raise ErroConfig("Digite a pausa como número de segundos, por exemplo 0 (sem pausa) ou 1,5.")
    if s < 0 or s > MAX_PAUSA_S:
        raise ErroConfig(f"A pausa deve ficar entre 0 e {MAX_PAUSA_S} segundos.")
    return s


def interpretar_gb(texto: str) -> float:
    """'2', '2,5' ou '2.5' (em GB) -> GB. Levanta ErroConfig se não servir."""
    try:
        gb = float(texto.strip().replace(",", "."))
    except ValueError:
        raise ErroConfig("Digite o limite como número de gigabytes, por exemplo 5 ou 2,5.")
    if gb * 1024 < MIN_CACHE_MB:
        raise ErroConfig("O limite mínimo é 0,5 GB.")
    if gb > 10000:
        raise ErroConfig("Esse limite é grande demais. Use no máximo 10000 GB.")
    return gb


def gravar_cache_gb(dados: Path, gb: float):
    cfg = ler(dados)
    cfg["cache_max_mb"] = round(gb * 1024)
    Path(dados).mkdir(parents=True, exist_ok=True)
    (Path(dados) / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


def gravar_pausa(dados: Path, segundos: float):
    cfg = ler(dados)
    cfg["pausa_envios_s"] = segundos
    Path(dados).mkdir(parents=True, exist_ok=True)
    (Path(dados) / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


def esquecer_conta(dados: Path):
    """Apaga o que pertence à conta atual: índice local, cache, pausa e o grupo guardado. Mantém as chaves da API
    (api_id e api_hash), que não dependem da conta. O que está no Telegram não é tocado."""
    import shutil
    dados = Path(dados)
    cfg = ler(dados)
    for k in ("grupo_id", "topicos"):
        cfg.pop(k, None)
    (dados / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    for nome in ("indice.db", "indice.db-wal", "indice.db-shm", "pausa_telegram.json"):
        (dados / nome).unlink(missing_ok=True)
    shutil.rmtree(dados / "cache", ignore_errors=True)


def _gb_texto(mb: float) -> str:
    gb = mb / 1024
    return (f"{gb:.2f}".rstrip("0").rstrip(".")).replace(".", ",")


def abrir_janela(dados: Path) -> bool:
    """Mostra as configurações. Devolve True se o usuário salvou."""
    import wx
    from .login import _para_frente

    app = wx.App(False)
    atual_mb = ler(dados).get("cache_max_mb", PADRAO_CACHE_MB)
    erro = ""
    texto_campo = _gb_texto(float(atual_mb))
    texto_pausa = str(pausa_envios_s(dados)).replace(".", ",").removesuffix(",0")
    inicio = sistema.inicio_ativo()
    salvou = False
    while True:
        dlg = wx.Dialog(None, title="TeleCloud - Configurações",
                        style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP)
        caixa = wx.BoxSizer(wx.VERTICAL)
        intro = ((f"Erro: {erro}\n\n" if erro else "") +
                 "O TeleCloud guarda no disco uma cópia dos arquivos que você abre ou grava. "
                 "Quando passa do limite, apaga os acessados há mais tempo. Eles continuam na unidade e "
                 "são baixados de novo quando você abrir.")
        t = wx.StaticText(dlg, label=intro)
        t.Wrap(420)
        caixa.Add(t, 0, wx.ALL, 12)
        caixa.Add(wx.StaticText(dlg, label="Limite do cache em disco, em GB:"), 0, wx.LEFT | wx.RIGHT, 12)
        campo = wx.TextCtrl(dlg, value=texto_campo, size=(420, -1), name="Limite do cache em GB")
        caixa.Add(campo, 0, wx.ALL | wx.EXPAND, 12)
        t2 = wx.StaticText(dlg, label=(
            "Se você envia milhares de arquivos pequenos, o Telegram pode impor pausas de dezenas de minutos. "
            "Uma pausa entre os envios evita isso. Use 0 para enviar sem pausa; 1,5 é um bom valor para pastas "
            "com muitos arquivos."))
        t2.Wrap(420)
        caixa.Add(t2, 0, wx.LEFT | wx.RIGHT, 12)
        caixa.Add(wx.StaticText(dlg, label="Pausa entre envios de arquivos pequenos, em segundos:"),
                  0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        campo_pausa = wx.TextCtrl(dlg, value=texto_pausa, size=(420, -1), name="Pausa entre envios em segundos")
        caixa.Add(campo_pausa, 0, wx.ALL | wx.EXPAND, 12)
        marca = wx.CheckBox(dlg, label="Iniciar o TeleCloud com o Windows")
        marca.SetValue(inicio)
        caixa.Add(marca, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        linha = wx.BoxSizer(wx.HORIZONTAL)
        ok = wx.Button(dlg, wx.ID_OK, "Salvar")
        cancelar = wx.Button(dlg, wx.ID_CANCEL, "Cancelar")
        linha.Add(ok, 0, wx.RIGHT, 8)
        linha.Add(cancelar, 0)
        caixa.Add(linha, 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        dlg.SetSizerAndFit(caixa)
        dlg.SetAffirmativeId(wx.ID_OK)
        dlg.SetEscapeId(wx.ID_CANCEL)
        ok.SetDefault()
        dlg.CentreOnScreen()
        campo.SetFocus()
        campo.SelectAll()
        wx.CallAfter(_para_frente, dlg)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                break
            texto_campo, texto_pausa, inicio = campo.GetValue(), campo_pausa.GetValue(), marca.GetValue()
        finally:
            dlg.Destroy()
        try:
            gb = interpretar_gb(texto_campo)
            pausa = interpretar_pausa(texto_pausa)
            gravar_cache_gb(dados, gb)
            gravar_pausa(dados, pausa)
            if inicio != sistema.inicio_ativo():
                sistema.definir_inicio(inicio)
        except ErroConfig as e:
            erro = str(e)
            continue
        except Exception as e:
            log.exception("configurações")
            erro = f"{type(e).__name__}: {e}"
            continue
        salvou = True
        break
    app.Destroy()
    return salvou
