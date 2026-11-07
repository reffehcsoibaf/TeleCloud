"""Operações do sistema de arquivos: traduz o WinFsp para a Nuvem, com cache local e envio em segundo plano."""
import ctypes
import logging
import os
import queue
import threading
import time
from ctypes import byref, c_void_p, memmove, sizeof
from pathlib import Path

from . import winfsp as w
from .nuvem import Nuvem
from .indice import RAIZ

log = logging.getLogger("telecloud")

SEGUNDO_1601 = 11644473600


def ft(t: float) -> int:
    return int((t + SEGUNDO_1601) * 10_000_000)


def seguro(f):
    """Nenhuma exceção pode atravessar o callback para o WinFsp."""
    import functools

    @functools.wraps(f)
    def g(self, *a):
        try:
            r = f(self, *a)
            if r not in (0, None):
                log.info("%s -> 0x%08X %s", f.__name__, r, [x for x in a[1:] if isinstance(x, (str, int))][:4])
            return r
        except Exception:
            log.exception("erro em %s", f.__name__)
            return None if f.__name__ in ("Cleanup", "Close") else w.STATUS_UNSUCCESSFUL

    return g


class Estado:
    """Estado compartilhado de um arquivo (cache local + o que falta enviar)."""

    def __init__(self, no_id, cache: Path):
        self.no_id = no_id
        self.cache = cache
        self.lock = threading.RLock()
        self.fh = None
        self.partes_ok: set[int] = set()
        self.completo = False
        self.tamanho = 0
        self.refs = 0
        self.versao = 0
        self.sujo = False
        self.na_fila = False
        self.acesso = time.time()

    def abrir(self):
        if self.fh is None:
            if not self.cache.exists():
                self.cache.touch()
            self.fh = open(self.cache, "r+b")
        return self.fh

    def fechar_fh(self):
        if self.fh:
            self.fh.close()
            self.fh = None


class Alca:
    def __init__(self, no_id, pasta, estado):
        self.no_id, self.pasta, self.estado = no_id, pasta, estado


class Unidade:
    def __init__(self, nuvem: Nuvem, pasta_cache: Path, rotulo="TeleCloud",
                 cache_max=5 * 1024**3, silencio_indice=20.0):
        self.nuvem = nuvem
        self.cache_max = cache_max
        self.silencio_indice = silencio_indice  # segundos sem alterações antes de guardar o índice
        self.ao_erro = None  # opcional: função(texto) chamada quando a fila falha
        self.atual = None  # arquivo sendo enviado agora
        self.progresso = (0, 0)
        self.erro = None
        self.indice_salvo_em = None
        self._falhas = 0
        self._enviando_id = None
        self.ix = nuvem.indice
        self.cache_dir = Path(pasta_cache)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.rotulo = rotulo
        self.trava = threading.RLock()
        self.estados: dict[int, Estado] = {}
        self.alcas: dict[int, Alca] = {}
        self._prox = 0
        self.fila: queue.Queue = queue.Queue()
        self.dll = w._carregar()
        self._parar = False
        self._visto = self.ix.mudancas
        self._mudou_em = time.time()
        self._ultimo_visto_mudanca = self.ix.mudancas
        self._tentou_indice = 0.0
        self._ultima_limpeza = 0.0

        pend = set(self.ix.pendentes_de_envio())
        # cache de arquivos já enviados não é confiável após reiniciar (partes em memória): limpa
        for f in self.cache_dir.glob("*.bin"):
            try:
                if int(f.stem) not in pend:
                    f.unlink()
            except (ValueError, OSError):
                pass
        for i in pend:
            e = self._estado(i)
            e.completo = True
            e.sujo = True
            self.fila.put(("env", i))
        sobras = self.ix.apagar_pendentes()
        if sobras:
            self.fila.put(("apg", sobras))
        self.worker = threading.Thread(target=self._trabalhar, daemon=True, name="envios")
        self.worker.start()

    # ---------- infraestrutura ----------
    def _estado(self, no_id) -> Estado:
        with self.trava:
            e = self.estados.get(no_id)
            if not e:
                e = Estado(no_id, self.cache_dir / f"{no_id}.bin")
                no = self.ix.obter(no_id)
                e.tamanho = no.tamanho if no else 0
                if e.cache.exists() and no and not self.ix.partes(no_id) and no.tamanho:
                    e.completo = True
                elif no and no.tamanho == 0:
                    e.completo = True
                self.estados[no_id] = e
            return e

    def _nova_alca(self, a: Alca) -> int:
        with self.trava:
            self._prox += 1
            self.alcas[self._prox] = a
            return self._prox

    def _info(self, no, fi):
        e = self.estados.get(no.id)
        tam = e.tamanho if (e and not no.pasta) else no.tamanho
        t = ft(no.modificado)
        fi.FileAttributes = w.FILE_ATTRIBUTE_DIRECTORY if no.pasta else w.FILE_ATTRIBUTE_NORMAL
        fi.ReparseTag = 0
        fi.FileSize = 0 if no.pasta else tam
        fi.AllocationSize = 0 if no.pasta else (tam + 4095) // 4096 * 4096
        fi.CreationTime = fi.LastAccessTime = fi.LastWriteTime = fi.ChangeTime = t
        fi.IndexNumber = no.id
        fi.HardLinks = 0
        fi.EaSize = 0

    def _garantir(self, e: Estado, inicio: int, fim: int):
        """Baixa para o cache as partes que cobrem [inicio, fim)."""
        if e.completo:
            return
        with e.lock:
            fh = e.abrir()
            pos = 0
            partes = self.ix.partes(e.no_id)
            for p in partes:
                if pos < fim and pos + p.tamanho > inicio and p.seq not in e.partes_ok:
                    dados = self.nuvem.baixar_parte(p)
                    fh.seek(pos)
                    fh.write(dados)
                    fh.flush()
                    e.partes_ok.add(p.seq)
                pos += p.tamanho
            if len(e.partes_ok) >= len(partes):
                e.completo = True

    def _agendar_envio(self, e: Estado, mudou=True):
        with e.lock:
            if mudou:
                e.versao += 1
            e.sujo = True
            ja = e.na_fila
            e.na_fila = True
        self.ix.definir_tamanho(e.no_id, e.tamanho)
        if not ja:
            self.fila.put(("env", e.no_id))

    def _trabalhar(self):
        while not self._parar:
            try:
                tipo, x = self.fila.get(timeout=0.5)
            except queue.Empty:
                self._tarefas_ociosas()
                continue
            try:
                if tipo == "env":
                    self._enviar(x)
                elif tipo == "apg":
                    self.nuvem.arm.apagar(x)
                    self.ix.apagados(x)
                self._falhas = 0
                self.erro = None
            except Exception as ex:
                self._falhas += 1
                espera = getattr(ex, "seconds", None) or min(300, 15 * 2 ** (self._falhas - 1))
                self.erro = f"{type(ex).__name__}: {ex}"
                log.exception("falha na fila (%s); tentando de novo em %s s", tipo, espera)
                if self.ao_erro and self._falhas in (1, 5):
                    try:
                        self.ao_erro(f"Falha ao falar com o Telegram. Nova tentativa em {int(espera)} segundos.")
                    except Exception:
                        pass
                for _ in range(int(espera * 2)):
                    if self._parar:
                        break
                    time.sleep(0.5)
                self.fila.put((tipo, x))

    def _tarefas_ociosas(self):
        agora = time.time()
        if self.ix.mudancas != self._visto and not self._mudou_em_recente(agora):
            if agora - self._tentou_indice > 60:
                self.salvar_indice_agora()
        if agora - self._ultima_limpeza > 30:
            self._ultima_limpeza = agora
            try:
                self.limpar_cache()
            except Exception:
                log.exception("falha ao limpar o cache")

    def _mudou_em_recente(self, agora):
        m = self.ix.mudancas
        if m != self._ultimo_visto_mudanca:
            self._ultimo_visto_mudanca = m
            self._mudou_em = agora
        return agora - self._mudou_em < self.silencio_indice

    def salvar_indice_agora(self) -> bool:
        """Guarda uma cópia do índice no armazenamento remoto (para recuperar em outro computador)."""
        self._tentou_indice = time.time()
        alvo = self.ix.mudancas
        try:
            self.nuvem.arm.salvar_indice(self.ix.exportar())
        except Exception:
            log.exception("não consegui guardar o índice")
            return False
        self._visto = alvo
        self.indice_salvo_em = time.time()
        log.info("índice guardado no armazenamento remoto")
        return True

    # ---------- cache ----------
    def tamanho_cache(self) -> int:
        total = 0
        for f in self.cache_dir.glob("*.bin"):
            try:
                total += f.stat().st_size
            except OSError:
                pass
        return total

    def limpar_cache(self):
        """Apaga do disco os arquivos mais antigos já guardados no Telegram, até caber no limite."""
        total = self.tamanho_cache()
        if total <= self.cache_max:
            return
        with self.trava:
            candidatos = [e for e in self.estados.values()
                          if e.refs <= 0 and not e.sujo and not e.na_fila
                          and e.no_id != self._enviando_id and self.ix.partes(e.no_id)]
            candidatos.sort(key=lambda e: e.acesso)
            for e in candidatos:
                if total <= self.cache_max:
                    break
                try:
                    tam = e.cache.stat().st_size
                except OSError:
                    tam = 0
                with e.lock:
                    e.fechar_fh()
                    try:
                        e.cache.unlink(missing_ok=True)
                    except OSError:
                        continue
                self.estados.pop(e.no_id, None)
                total -= tam
                log.info("cache: liberado %s", self.ix.caminho_de(e.no_id))

    def _enviar(self, no_id):
        e = self.estados.get(no_id)
        if not e or not self.ix.obter(no_id):
            return
        with e.lock:
            e.na_fila = False
            v = e.versao
            if e.fh:
                e.fh.flush()
        self._enviando_id = no_id
        self.atual = self.ix.caminho_de(no_id)
        self.progresso = (0, 0)
        try:
            self.nuvem.enviar_no(no_id, str(e.cache),
                                 lambda feito, total: setattr(self, "progresso", (feito, total)))
        finally:
            self._enviando_id = None
            self.atual = None
        with e.lock:
            if e.versao != v:
                e.na_fila = True
                self.fila.put(("env", no_id))
            else:
                e.sujo = False
                e.completo = True
                e.partes_ok = {p.seq for p in self.ix.partes(no_id)}
        log.info("enviado: %s", self.ix.caminho_de(no_id))

    def situacao(self) -> dict:
        """Resumo para a bandeja: o que está sendo enviado, o que espera e o uso do cache."""
        esperando = sorted(self.ix.caminho_de(e.no_id) for e in list(self.estados.values())
                           if e.sujo and e.no_id != self._enviando_id)
        return {
            "enviando": self.atual, "progresso": self.progresso, "esperando": esperando,
            "apagando": len(self.ix.apagar_pendentes()), "cache": self.tamanho_cache(),
            "cache_max": self.cache_max, "erro": self.erro, "indice_salvo_em": self.indice_salvo_em,
        }

    def _apagar_remoto(self, refs):
        if refs:
            self.ix.marcar_apagar(refs)
            self.fila.put(("apg", refs))

    def aguardar_fila(self, limite=600):
        t = time.time()
        while time.time() - t < limite:
            if (self.fila.empty() and not any(e.sujo for e in self.estados.values())
                    and not self.ix.apagar_pendentes()):
                return True
            time.sleep(0.2)
        return False

    def parar(self):
        self._parar = True
        for e in self.estados.values():
            e.fechar_fh()

    # ---------- callbacks do WinFsp ----------
    @seguro
    def GetVolumeInfo(self, fs, vi):
        v = vi[0]
        v.TotalSize = 1 << 40
        v.FreeSize = 1 << 40
        v.VolumeLabel = self.rotulo
        v.VolumeLabelLength = len(self.rotulo) * 2
        return w.STATUS_SUCCESS

    @seguro
    def GetSecurityByName(self, fs, nome, p_attr, sd, p_sd):
        no = self.ix.resolver(nome)
        if not no:
            pai = nome.rsplit("\\", 1)[0]
            return w.STATUS_OBJECT_NAME_NOT_FOUND if self.ix.resolver(pai) else w.STATUS_OBJECT_PATH_NOT_FOUND
        if p_attr:
            p_attr[0] = w.FILE_ATTRIBUTE_DIRECTORY if no.pasta else w.FILE_ATTRIBUTE_NORMAL
        if p_sd:
            p_sd[0] = 0
        return w.STATUS_SUCCESS

    @seguro
    def Create(self, fs, nome, opcoes, acesso, attr, sd, alocacao, p_ctx, fi):
        if self.ix.resolver(nome):
            return w.STATUS_OBJECT_NAME_COLLISION
        pai_c, _, base = nome.rpartition("\\")
        pai = self.ix.resolver(pai_c)
        if not pai or not pai.pasta:
            return w.STATUS_OBJECT_PATH_NOT_FOUND
        eh_pasta = bool(opcoes & w.FILE_DIRECTORY_FILE)
        if eh_pasta and pai.id == RAIZ:
            self.nuvem.arm.garantir_pasta(base)
        no = self.ix.criar(pai.id, base, eh_pasta)
        est = None
        if not eh_pasta:
            with self.trava:
                est = self._estado(no.id)
                est.refs += 1
            est.completo = True
            est.cache.write_bytes(b"")
        p_ctx[0] = self._nova_alca(Alca(no.id, eh_pasta, est))
        self._info(no, fi[0])
        return w.STATUS_SUCCESS

    @seguro
    def Open(self, fs, nome, opcoes, acesso, p_ctx, fi):
        no = self.ix.resolver(nome)
        if not no:
            return w.STATUS_OBJECT_NAME_NOT_FOUND
        est = None
        if not no.pasta:
            with self.trava:
                est = self._estado(no.id)
                est.refs += 1
                est.acesso = time.time()
        p_ctx[0] = self._nova_alca(Alca(no.id, no.pasta, est))
        self._info(no, fi[0])
        return w.STATUS_SUCCESS

    @seguro
    def Overwrite(self, fs, ctx, attr, substituir, alocacao, fi):
        a = self.alcas[ctx]
        e = a.estado
        with e.lock:
            e.abrir().truncate(0)
            e.tamanho = 0
            e.completo = True
            e.partes_ok = set()
        self._agendar_envio(e)
        self._info(self.ix.obter(a.no_id), fi[0])
        return w.STATUS_SUCCESS

    @seguro
    def Cleanup(self, fs, ctx, nome, flags):
        a = self.alcas.get(ctx)
        if not a:
            return
        if flags & w.FspCleanupDelete:
            refs = self.ix.refs_da_subarvore(a.no_id)
            self.ix.remover(a.no_id)
            self._apagar_remoto(refs)
            if a.estado:
                a.estado.fechar_fh()
                try:
                    a.estado.cache.unlink()
                except OSError:
                    pass
                self.estados.pop(a.no_id, None)
        elif a.estado and a.estado.sujo:
            self._agendar_envio(a.estado, mudou=False)

    @seguro
    def Close(self, fs, ctx):
        a = self.alcas.pop(ctx, None)
        if a and a.estado:
            with self.trava:
                a.estado.refs -= 1
                if a.estado.refs <= 0 and not a.estado.sujo:
                    a.estado.fechar_fh()

    @seguro
    def Read(self, fs, ctx, buf, off, tam, p_lido):
        a = self.alcas[ctx]
        e = a.estado
        if off >= e.tamanho:
            p_lido[0] = 0
            return 0xC0000011  # STATUS_END_OF_FILE
        n = min(tam, e.tamanho - off)
        e.acesso = time.time()
        self._garantir(e, off, off + n)
        with e.lock:
            fh = e.abrir()
            fh.seek(off)
            dados = fh.read(n)
        memmove(buf, dados, len(dados))
        p_lido[0] = len(dados)
        return w.STATUS_SUCCESS

    @seguro
    def Write(self, fs, ctx, buf, off, tam, fim_arq, restrito, p_escrito, fi):
        a = self.alcas[ctx]
        e = a.estado
        self._garantir(e, 0, e.tamanho)  # edição precisa do arquivo inteiro no cache
        with e.lock:
            if fim_arq:
                off = e.tamanho
            if restrito:
                if off >= e.tamanho:
                    p_escrito[0] = 0
                    self._info(self.ix.obter(a.no_id), fi[0])
                    return w.STATUS_SUCCESS
                tam = min(tam, e.tamanho - off)
            dados = ctypes.string_at(buf, tam)
            fh = e.abrir()
            fh.seek(off)
            fh.write(dados)
            e.tamanho = max(e.tamanho, off + tam)
            e.sujo = True
            e.versao += 1
        p_escrito[0] = tam
        self._info(self.ix.obter(a.no_id), fi[0])
        return w.STATUS_SUCCESS

    @seguro
    def Flush(self, fs, ctx, fi):
        if ctx:
            a = self.alcas[ctx]
            if a.estado and a.estado.sujo:
                self._agendar_envio(a.estado)
            self._info(self.ix.obter(a.no_id), fi[0])
        return w.STATUS_SUCCESS

    @seguro
    def GetFileInfo(self, fs, ctx, fi):
        self._info(self.ix.obter(self.alcas[ctx].no_id), fi[0])
        return w.STATUS_SUCCESS

    @seguro
    def SetBasicInfo(self, fs, ctx, attr, criacao, acesso, escrita, mudanca, fi):
        self._info(self.ix.obter(self.alcas[ctx].no_id), fi[0])
        return w.STATUS_SUCCESS

    @seguro
    def SetFileSize(self, fs, ctx, novo, so_alocacao, fi):
        a = self.alcas[ctx]
        e = a.estado
        if not so_alocacao:
            self._garantir(e, 0, e.tamanho)
            with e.lock:
                e.abrir().truncate(novo)
                e.tamanho = novo
                e.sujo = True
                e.versao += 1
        self._info(self.ix.obter(a.no_id), fi[0])
        return w.STATUS_SUCCESS

    @seguro
    def CanDelete(self, fs, ctx, nome):
        a = self.alcas[ctx]
        if a.pasta and self.ix.listar(a.no_id):
            return w.STATUS_DIRECTORY_NOT_EMPTY
        return w.STATUS_SUCCESS

    @seguro
    def SetDelete(self, fs, ctx, nome, apagar):
        return self.CanDelete(fs, ctx, nome) if apagar else w.STATUS_SUCCESS

    @seguro
    def Rename(self, fs, ctx, nome, novo, substituir):
        a = self.alcas[ctx]
        alvo = self.ix.resolver(novo)
        if alvo and alvo.id != a.no_id:
            if not substituir or alvo.pasta:
                return w.STATUS_OBJECT_NAME_COLLISION
            refs = self.ix.refs_da_subarvore(alvo.id)
            self.ix.remover(alvo.id)
            self.estados.pop(alvo.id, None)
            self._apagar_remoto(refs)
        pai_c, _, base = novo.rpartition("\\")
        pai = self.ix.resolver(pai_c)
        if not pai or not pai.pasta:
            return w.STATUS_OBJECT_PATH_NOT_FOUND
        self.ix.renomear(a.no_id, pai.id, base)
        return w.STATUS_SUCCESS

    @seguro
    def ReadDirectory(self, fs, ctx, padrao, marcador, buf, tam, p_transf):
        a = self.alcas[ctx]
        filhos = sorted(self.ix.listar(a.no_id), key=lambda n: n.nome.casefold())
        itens = []
        if a.no_id != RAIZ:
            atual = self.ix.obter(a.no_id)
            pai = self.ix.obter(atual.pai) if atual.pai else atual
            itens += [(".", atual), ("..", pai)]
        itens += [(n.nome, n) for n in filhos]
        if marcador:
            nomes = [n for n, _ in itens]
            if marcador in nomes:
                itens = itens[nomes.index(marcador) + 1:]
            else:
                m = marcador.casefold()
                itens = [(n, x) for n, x in itens if n not in (".", "..") and n.casefold() > m]
        for nome, no in itens:
            bruto = nome.encode("utf-16-le")
            bloco = ctypes.create_string_buffer(w.CAB + len(bruto) + 2)
            cab = w.DirInfoCab.from_buffer(bloco)
            cab.Size = w.CAB + len(bruto)
            self._info(no, cab.FileInfo)
            memmove(ctypes.addressof(bloco) + w.CAB, bruto, len(bruto))
            ok = self.dll.FspFileSystemAddDirInfo(
                ctypes.addressof(bloco), buf, tam, p_transf)
            if not ok:
                return w.STATUS_SUCCESS
        self.dll.FspFileSystemAddDirInfo(None, buf, tam, p_transf)
        return w.STATUS_SUCCESS


