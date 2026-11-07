"""Ícone na bandeja do sistema. Tudo é menu nativo do Windows (acessível por teclado e leitor de tela):
o estado aparece como itens de texto, sem janelas próprias."""
import os
import threading
import time

import pystray
from PIL import Image, ImageDraw

from . import sistema


def _tamanho(n: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}".replace(".", ",")
        n /= 1024


def _icone(cor: str) -> Image.Image:
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((2, 2, 62, 62), fill=cor)
    d.rectangle((16, 18, 48, 26), fill="white")  # o "T"
    d.rectangle((28, 18, 36, 48), fill="white")
    return im


ICONES = {"ok": "#229ED9", "ocupado": "#E08A00", "erro": "#C62828"}


class Bandeja:
    def __init__(self, un, unidade_letra: str, pasta_dados, ao_sair):
        self.un = un
        self.letra = unidade_letra
        self.pasta_dados = pasta_dados
        self.ao_sair = ao_sair  # chamada em outra thread; deve encerrar tudo e depois chamar parar()
        self.saindo = False
        self._fim = False
        self._assinatura = None
        self.icone = pystray.Icon("TeleCloud", _icone(ICONES["ok"]), "TeleCloud", self._menu())
        un.ao_erro = lambda texto: self.avisar(texto)

    # ---------- texto do estado ----------
    def _resumo(self) -> tuple[str, str]:
        if self.saindo:
            return "Encerrando: aguardando os envios terminarem", "ocupado"
        s = self.un.situacao()
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

    def _itens_fila(self):
        s = self.un.situacao()
        itens = []
        if s["enviando"]:
            feito, total = s["progresso"]
            parte = f" - {_tamanho(feito)} de {_tamanho(total)}" if total else ""
            itens.append(pystray.MenuItem(f"Enviando: {s['enviando']}{parte}", None, enabled=False))
        for nome in s["esperando"][:15]:
            itens.append(pystray.MenuItem(f"Esperando: {nome}", None, enabled=False))
        if len(s["esperando"]) > 15:
            itens.append(pystray.MenuItem(f"... e mais {len(s['esperando']) - 15}", None, enabled=False))
        if s["apagando"]:
            itens.append(pystray.MenuItem(f"Removendo do Telegram: {s['apagando']} mensagem(ns)", None, enabled=False))
        if not itens:
            itens.append(pystray.MenuItem("Nenhum envio pendente", None, enabled=False))
        return itens

    def _menu(self):
        def estado(_):
            return self._resumo()[0]

        def cache(_):
            s = self.un.situacao()
            return f"Espaço usado no disco: {_tamanho(s['cache'])} de {_tamanho(s['cache_max'])}"

        def indice(_):
            t = self.un.situacao()["indice_salvo_em"]
            return ("Índice guardado no Telegram às " + time.strftime("%H:%M", time.localtime(t))
                    if t else "Índice ainda não guardado nesta sessão")

        return pystray.Menu(
            pystray.MenuItem(estado, None, enabled=False),
            pystray.MenuItem(f"Abrir a unidade {self.letra}", self._abrir_unidade, default=True),
            pystray.MenuItem("Fila de envios", pystray.Menu(lambda: self._itens_fila())),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(cache, None, enabled=False),
            pystray.MenuItem(indice, None, enabled=False),
            pystray.MenuItem("Guardar o índice no Telegram agora", self._guardar_indice),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Iniciar com o Windows", self._alternar_inicio,
                             checked=lambda _: sistema.inicio_ativo()),
            pystray.MenuItem("Abrir a pasta de dados e registro", self._abrir_dados),
            pystray.MenuItem("Sair", self._sair),
        )

    # ---------- ações ----------
    def _abrir_unidade(self, *_):
        os.startfile(self.letra + "\\")

    def _abrir_dados(self, *_):
        os.startfile(str(self.pasta_dados))

    def _guardar_indice(self, *_):
        def f():
            ok = self.un.salvar_indice_agora()
            self.avisar("Índice guardado no Telegram." if ok else "Não foi possível guardar o índice agora.")
        threading.Thread(target=f, daemon=True).start()

    def _alternar_inicio(self, *_):
        sistema.definir_inicio(not sistema.inicio_ativo())
        self.icone.update_menu()

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
        if forcar or (texto, nivel) != self._assinatura:
            self._assinatura = (texto, nivel)
            self.icone.icon = _icone(ICONES[nivel])
            self.icone.title = ("TeleCloud: " + texto)[:127]
            self.icone.update_menu()

    def _vigiar(self):
        while not self._fim:
            try:
                self._atualizar()
            except Exception:
                pass
            time.sleep(2)

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
