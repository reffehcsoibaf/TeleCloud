"""Armazenamento no Telegram: um supergrupo com tópicos; cada pasta de primeiro nível é um tópico."""
import asyncio
import io
import json
import threading
from pathlib import Path

from telethon import TelegramClient, functions
from telethon.tl.types import PeerChannel

from .armazenamento import Armazenamento

NOME_GRUPO = "TeleCloud"
MARCA_INDICE = "#telecloud_indice"


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
            self.grupo = await self.client.get_entity(PeerChannel(id_salvo))
            return
        existente = await self._achar_grupo_existente()
        if existente:
            self.grupo = existente
            self.cfg["grupo_id"] = existente.id
            self.cfg["topicos"] = await self._topicos_do_grupo()
            self.cfg_caminho.write_text(json.dumps(self.cfg), encoding="utf-8")
            return
        r = await self.client(functions.channels.CreateChannelRequest(
            title=NOME_GRUPO, about="Armazenamento do TeleCloud", megagroup=True, forum=True))
        self.grupo = r.chats[0]
        self.cfg["grupo_id"] = self.grupo.id
        self.cfg["topicos"] = {}
        self.cfg_caminho.write_text(json.dumps(self.cfg), encoding="utf-8")

    async def _achar_grupo_existente(self):
        """Num computador novo não há config.json: reaproveita o grupo que já existe na conta."""
        async for d in self.client.iter_dialogs():
            e = d.entity
            if getattr(e, "megagroup", False) and getattr(e, "forum", False) and e.title == NOME_GRUPO                     and getattr(e, "creator", False):
                return e
        return None

    async def _topicos_do_grupo(self):
        r = await self.client(functions.messages.GetForumTopicsRequest(
            peer=self.grupo, offset_date=None, offset_id=0, offset_topic=0, limit=100))
        return {t.title: t.id for t in r.topics if hasattr(t, "title")}

    # --- tópicos ---
    async def _topico(self, nome):
        topicos = self.cfg.setdefault("topicos", {})
        if nome not in topicos:
            r = await self.client(functions.messages.CreateForumTopicRequest(
                peer=self.grupo, title=nome[:128]))
            # o id do tópico é o id da mensagem de serviço criada
            topicos[nome] = next(
                u.message.id for u in r.updates
                if hasattr(u, "message") and getattr(u.message, "id", None))
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

    # --- cópia do índice: um documento com a marca, no tópico geral ---
    def salvar_indice(self, copia):
        async def f():
            arq = io.BytesIO(copia)
            arq.name = "indice.db.z"
            nova = await self.client.send_file(
                self.grupo, arq, caption=MARCA_INDICE, force_document=True, file_name="indice.db.z")
            velhas = [m.id async for m in self.client.iter_messages(
                self.grupo, search=MARCA_INDICE, limit=50)
                if m.id != nova.id and (m.message or "").strip() == MARCA_INDICE]
            if velhas:
                await self.client.delete_messages(self.grupo, velhas)
        self._rodar(f())

    def carregar_indice(self):
        async def f():
            async for m in self.client.iter_messages(self.grupo, search=MARCA_INDICE, limit=20):
                if (m.message or "").strip() == MARCA_INDICE and m.document:
                    return await self.client.download_media(m, file=bytes)
            return None
        return self._rodar(f())

    def desconectar_conta(self):
        """Encerra a sessão no Telegram (some da lista de dispositivos) e apaga o arquivo de sessão local.
        Se não houver rede, ao menos apaga a sessão local."""
        try:
            self._rodar(self.client.log_out())
        except Exception:
            try:
                self.fechar()
            except Exception:
                pass
        else:
            self.loop.call_soon_threadsafe(self.loop.stop)
        for f in self.pasta.glob("sessao.session*"):
            try:
                f.unlink()
            except OSError:
                pass

    def fechar(self):
        async def f():
            await self.client.disconnect()
        self._rodar(f())
        self.loop.call_soon_threadsafe(self.loop.stop)
