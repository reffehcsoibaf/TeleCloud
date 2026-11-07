"""Armazenamento no Telegram: um supergrupo com tópicos; cada pasta de primeiro nível é um tópico."""
import asyncio
import io
import json
import threading
from pathlib import Path

from telethon import TelegramClient, functions
from telethon.tl.types import InputPeerChannel

from .armazenamento import Armazenamento

NOME_GRUPO = "TeleCloud"


class TelegramArmazenamento(Armazenamento):
    def __init__(self, pasta_dados: Path):
        self.pasta = Path(pasta_dados)
        cfg = json.loads((self.pasta / "config.json").read_text(encoding="utf-8-sig"))
        self.cfg_caminho = self.pasta / "config.json"
        self.cfg = cfg
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.client = TelegramClient(
            str(self.pasta / "sessao"), cfg["api_id"], cfg["api_hash"], loop=self.loop
        )
        self.grupo = None

    def _rodar(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

    # --- conexão ---
    def entrar(self, telefone=None, codigo=None, senha=None):
        """Chamada interativa (ver entrar.py). Devolve quando autorizado."""
        async def f():
            await self.client.connect()
            if await self.client.is_user_authorized():
                return
            await self.client.send_code_request(telefone)
            await self.client.sign_in(telefone, codigo() if callable(codigo) else codigo)
        try:
            self._rodar(f())
        except Exception as e:
            if "password" in str(e).lower() and senha:
                self._rodar(self.client.sign_in(password=senha() if callable(senha) else senha))
            else:
                raise

    def conectar(self):
        self._rodar(self.client.connect())
        if not self._rodar(self.client.is_user_authorized()):
            raise RuntimeError("Sem login. Rode: python entrar.py")
        self._rodar(self._garantir_grupo())

    async def _garantir_grupo(self):
        id_salvo = self.cfg.get("grupo_id")
        if id_salvo:
            self.grupo = await self.client.get_entity(id_salvo)
            return
        r = await self.client(functions.channels.CreateChannelRequest(
            title=NOME_GRUPO, about="Armazenamento do TeleCloud", megagroup=True, forum=True))
        self.grupo = r.chats[0]
        self.cfg["grupo_id"] = self.grupo.id
        self.cfg["topicos"] = {}
        self.cfg_caminho.write_text(json.dumps(self.cfg), encoding="utf-8")

    # --- tópicos ---
    async def _topico(self, nome):
        topicos = self.cfg.setdefault("topicos", {})
        if nome not in topicos:
            r = await self.client(functions.channels.CreateForumTopicRequest(
                channel=self.grupo, title=nome[:128]))
            topicos[nome] = r.updates[0].id
            self.cfg_caminho.write_text(json.dumps(self.cfg), encoding="utf-8")
        return topicos[nome]

    def garantir_pasta(self, caminho):
        self._rodar(self._topico(caminho))

    # --- blocos ---
    def enviar(self, pasta, nome, dados, legenda=""):
        async def f():
            topico = await self._topico(pasta)
            arq = io.BytesIO(dados)
            arq.name = nome
            m = await self.client.send_file(
                self.grupo, arq, caption=legenda or None, reply_to=topico,
                force_document=True, file_name=nome)
            return str(m.id)
        return self._rodar(f())

    def baixar(self, ref):
        async def f():
            m = await self.client.get_messages(self.grupo, ids=int(ref))
            if m is None:
                raise FileNotFoundError(ref)
            return await self.client.download_media(m, file=bytes)
        return self._rodar(f())

    def apagar(self, refs):
        if refs:
            self._rodar(self.client.delete_messages(self.grupo, [int(r) for r in refs]))

    def fechar(self):
        self._rodar(self.client.disconnect())
        self.loop.call_soon_threadsafe(self.loop.stop)
