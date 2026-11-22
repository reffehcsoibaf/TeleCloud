"""Ícone na bandeja do sistema. Tudo é menu nativo do Windows (acessível por teclado e leitor de tela):
o estado aparece como itens de texto, sem janelas próprias."""
import json
import logging
import os
import threading
import time
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from . import sistema


_tamanho = sistema.formatar_tamanho


def _icone(cor: str) -> Image.Image:
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((2, 2, 62, 62), fill=cor)
    d.rectangle((16, 18, 48, 26), fill="white")  # o "T"
    d.rectangle((28, 18, 36, 48), fill="white")
    return im


ICONES = {"ok": "#229ED9", "ocupado": "#E08A00", "erro": "#C62828"}


class Bandeja:
    def __init__(self, un, unidade_letra: str, pasta_dados, ao_sair, ao_configurar=None, ao_desconectar=None):
        self.un = un
        self.ao_desconectar = ao_desconectar   # chamada em outra thread; confirma, limpa e fecha o programa
        self.ao_configurar = ao_configurar   # chamada quando a janela de configurações fecha
        self._gravado_em = 0.0
        self.letra = unidade_letra
        self.pasta_dados = pasta_dados
        self.ao_sair = ao_sair  # chamada em outra thread; deve encerrar tudo e depois chamar parar()
        self.saindo = False
        self._fim = False
        self._assinatura = None
        self._mtime_config = None
        self.icone = pystray.Icon("TeleCloud", _icone(ICONES["ok"]), "TeleCloud", self._menu())
        un.ao_erro = lambda texto: self.avisar(texto)

    # ---------- texto do estado ----------
    def _resumo(self) -> tuple[str, str]:
        if self.saindo:
            return "Encerrando o TeleCloud", "ocupado"
        s = self.un.situacao()
        if s["pausa_ate"] > time.time():
            hora = time.strftime("%H:%M", time.localtime(s["pausa_ate"]))
            return f"O Telegram pediu uma pausa; os envios continuam às {hora}", "ocupado"
        if s["erro"]:
            return "Problema ao falar com o Telegram; tentando de novo", "erro"
        if s["enviando"]:
            feito, total = s["progresso"]
            pct = f" ({feito * 100 // total}%)" if total else ""
            mais = len(s["esperando"])
            extra = f", mais {mais} na fila" if mais else ""
            return f"Enviando {os.path.basename(s['enviando'])}{pct}{extra}", "ocupado"
        if s["esperando"]:
            return f"{len(s['esperando'])} arquivo(s) esperando para enviar", "ocupado"
        if s["apagando"]:
            return "Removendo arquivos apagados do Telegram", "ocupado"
        return "Tudo enviado", "ok"

    def _menu(self):
        # Só o essencial; estado, fila, cache e o resto ficam no painel de controle.
        return pystray.Menu(
            pystray.MenuItem(f"Abrir a unidade {self.letra}", self._abrir_unidade, default=True),
            pystray.MenuItem("Abrir o painel de controle", self._abrir_painel),
            pystray.MenuItem("Sair", self._sair),
        )

    # ---------- ações ----------
    def _abrir_unidade(self, *_):
        os.startfile(self.letra + "\\")

    def _comando(self, *extra) -> list:
        """Comando para abrir uma janela do TeleCloud num processo à parte (wx e bandeja não convivem no mesmo)."""
        import sys
        cmd = [sys.executable] if sistema.empacotado() else [sys.executable, os.path.abspath(sys.argv[0])]
        return cmd + list(extra) + ["--dados", str(self.pasta_dados)]

    def _abrir_painel(self, *_):
        import subprocess
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        subprocess.Popen(self._comando("--painel"), env=env, close_fds=True)

    def _buscar_novidades(self, *_):
        def f():
            try:
                n = self.un.sincronizar_indice()
            except Exception:
                self.avisar("Não foi possível consultar o Telegram agora.")
                return
            self.avisar(f"{n} item(ns) novo(s) trazido(s) do Telegram." if n else "Nada de novo no Telegram.")
        threading.Thread(target=f, daemon=True).start()

    def _guardar_indice(self, *_):
        def f():
            ok = self.un.salvar_indice_agora()
            self.avisar("Índice guardado no Telegram." if ok else "Não foi possível guardar o índice agora.")
        threading.Thread(target=f, daemon=True).start()

    def _sair(self, *_):
        if self.saindo:
            return
        self.saindo = True
        self._atualizar(forcar=True)
        threading.Thread(target=self.ao_sair, daemon=True).start()

    def avisar(self, texto: str):
        try:
            self.icone.notify(texto, "TeleCloud")
        except Exception:
            pass

    # ---------- ciclo ----------
    def _atualizar(self, forcar=False):
        texto, nivel = self._resumo()
        s = self.un.situacao()
        # a fila entra na assinatura: o menu é montado de uma vez e só muda quando chamamos update_menu
        assinatura = (texto, nivel, s["enviando"], tuple(s["esperando"]), s["apagando"])
        mudou = forcar or assinatura != self._assinatura
        if mudou:
            self._assinatura = assinatura
            self.icone.icon = _icone(ICONES[nivel])
            self.icone.title = ("TeleCloud: " + texto)[:127]
        # o uso do cache muda sem mudar o resto: regrava de tempos em tempos para o painel acompanhar
        if mudou or time.time() - self._gravado_em >= 3:
            self._gravar_estado(texto, nivel, s)

    def _gravar_estado(self, texto, nivel, s):
        """O painel de controle (outro processo) lê este arquivo para mostrar o estado."""
        self._gravado_em = time.time()
        try:
            (Path(self.pasta_dados) / "estado.json").write_text(json.dumps({
                "texto": texto, "nivel": nivel, "unidade": self.letra, "versao": sistema.VERSAO,
                "pendentes": len(s["esperando"]) + (1 if s["enviando"] else 0), "pausa_ate": s["pausa_ate"],
                "enviando": s["enviando"], "progresso": list(s["progresso"]), "esperando": s["esperando"],
                "apagando": s["apagando"], "indice_salvo_em": s["indice_salvo_em"],
                "cache": s["cache"], "cache_max": s["cache_max"], "em": time.time()}), encoding="utf-8")
        except OSError:
            pass

    def _config_mudou(self) -> bool:
        """True quando o config.json foi regravado (pela janela de configurações aberta pelo painel)."""
        try:
            m = (Path(self.pasta_dados) / "config.json").stat().st_mtime
        except OSError:
            return False
        antes, self._mtime_config = self._mtime_config, m
        return antes is not None and m != antes

    def _vigiar(self):
        while not self._fim:
            try:
                self._atualizar()
                if self._config_mudou() and self.ao_configurar:
                    self.ao_configurar()
            except Exception:
                logging.getLogger("telecloud").exception("bandeja: falha ao atualizar o estado")
            time.sleep(1)

    def executar(self, ao_pronto=None):
        """Bloqueia até parar() ser chamado."""
        def preparar(icone):
            icone.visible = True
            threading.Thread(target=self._vigiar, daemon=True).start()
            if ao_pronto:
                ao_pronto()
        self.icone.run(setup=preparar)

    def parar(self):
        self._fim = True
        self.icone.stop()
