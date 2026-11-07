"""Núcleo: junta índice + armazenamento, com divisão em partes e cifra opcional."""
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .armazenamento import Armazenamento
from .indice import RAIZ, Indice, No, Parte

TAMANHO_PARTE = 1900 * 1024 * 1024  # abaixo do limite de 2 GB do Telegram


class ErroNuvem(Exception):
    pass


def _partir(caminho: str) -> tuple[str, str]:
    p = [x for x in caminho.replace("\\", "/").split("/") if x]
    if not p:
        raise ErroNuvem("caminho vazio")
    return "/".join(p[:-1]), p[-1]


class Nuvem:
    def __init__(self, indice: Indice, armazenamento: Armazenamento, chave: bytes | None = None,
                 tamanho_parte: int = TAMANHO_PARTE):
        self.indice = indice
        self.arm = armazenamento
        self.chave = chave  # 32 bytes para AES-256-GCM; None = sem cifra
        self.tamanho_parte = tamanho_parte

    # --- cifra: nonce(12) + texto cifrado por parte ---
    def _cifrar(self, dados: bytes) -> bytes:
        if not self.chave:
            return dados
        nonce = os.urandom(12)
        return nonce + AESGCM(self.chave).encrypt(nonce, dados, None)

    def _decifrar(self, dados: bytes) -> bytes:
        if not self.chave:
            return dados
        return AESGCM(self.chave).decrypt(dados[:12], dados[12:], None)

    def _topico(self, caminho: str) -> str:
        """Primeiro nível do caminho = tópico do grupo."""
        p = [x for x in caminho.replace("\\", "/").split("/") if x]
        return p[0] if len(p) > 1 else "(raiz)"

    def _pai(self, caminho_pai: str) -> No:
        pai = self.indice.resolver(caminho_pai)
        if not pai or not pai.pasta:
            raise ErroNuvem(f"pasta não existe: {caminho_pai!r}")
        return pai

    def listar(self, caminho: str = "") -> list[No]:
        no = self._pai(caminho)
        return self.indice.listar(no.id)

    def criar_pasta(self, caminho: str) -> No:
        pai, nome = _partir(caminho)
        pai_no = self._pai(pai)
        if self.indice.resolver(caminho):
            raise ErroNuvem("já existe")
        if pai_no.id == RAIZ:
            self.arm.garantir_pasta(nome)
        return self.indice.criar(pai_no.id, nome, True)

    def gravar(self, caminho: str, dados: bytes, tags: list[str] | None = None) -> No:
        pai, nome = _partir(caminho)
        pai_no = self._pai(pai)
        existente = self.indice.resolver(caminho)
        if existente and existente.pasta:
            raise ErroNuvem("já existe uma pasta com esse nome")
        antigas = self.indice.refs_da_subarvore(existente.id) if existente else []
        no = existente or self.indice.criar(pai_no.id, nome, False)
        legenda = " ".join(f"#{t.lstrip('#')}" for t in (tags or []))
        partes = []
        n = max(1, -(-len(dados) // self.tamanho_parte))
        for i in range(n):
            bloco = dados[i * self.tamanho_parte:(i + 1) * self.tamanho_parte]
            ref = self.arm.enviar(self._topico(caminho), f"{nome}.{i:03d}", self._cifrar(bloco), legenda)
            partes.append(Parte(i, ref, len(bloco)))
        self.indice.definir_partes(no.id, partes, len(dados))
        if tags is not None:
            self.indice.definir_tags(no.id, [t.lstrip("#") for t in tags])
        if antigas:
            self.arm.apagar(antigas)
        return self.indice.obter(no.id)

    def ler(self, caminho: str, inicio: int = 0, tamanho: int | None = None) -> bytes:
        no = self.indice.resolver(caminho)
        if not no or no.pasta:
            raise ErroNuvem("arquivo não existe")
        fim = no.tamanho if tamanho is None else min(no.tamanho, inicio + tamanho)
        saida, pos = [], 0
        for p in self.indice.partes(no.id):
            if pos + p.tamanho > inicio and pos < fim:
                bloco = self._decifrar(self.arm.baixar(p.ref))
                saida.append(bloco[max(0, inicio - pos):max(0, fim - pos)])
            pos += p.tamanho
            if pos >= fim:
                break
        return b"".join(saida)

    def mover(self, origem: str, destino: str):
        """Renomear/mover é só no índice, sem reenviar nada."""
        no = self.indice.resolver(origem)
        if not no or no.id == RAIZ:
            raise ErroNuvem("origem não existe")
        pai, nome = _partir(destino)
        pai_no = self._pai(pai)
        if self.indice.resolver(destino):
            raise ErroNuvem("destino já existe")
        self.indice.renomear(no.id, pai_no.id, nome)

    def apagar(self, caminho: str):
        no = self.indice.resolver(caminho)
        if not no or no.id == RAIZ:
            raise ErroNuvem("não existe")
        if no.pasta and self.indice.listar(no.id):
            raise ErroNuvem("pasta não está vazia")
        self.arm.apagar(self.indice.refs_da_subarvore(no.id))
        self.indice.remover(no.id)

    def baixar_parte(self, parte: Parte) -> bytes:
        return self._decifrar(self.arm.baixar(parte.ref))

    def enviar_no(self, no_id: int, local: str):
        """Envia o conteúdo de um arquivo local como o conteúdo do nó (substitui o anterior)."""
        no = self.indice.obter(no_id)
        if not no or no.pasta:
            raise ErroNuvem("nó não existe")
        caminho = self.indice.caminho_de(no_id)
        antigas = self.indice.refs_da_subarvore(no_id)
        tamanho = os.path.getsize(local)
        legenda = " ".join(f"#{t}" for t in no.tags.split())
        partes = []
        if tamanho:
            with open(local, "rb") as f:
                i = 0
                while True:
                    bloco = f.read(self.tamanho_parte)
                    if not bloco:
                        break
                    ref = self.arm.enviar(
                        self._topico(caminho), f"{no.nome}.{i:03d}", self._cifrar(bloco), legenda)
                    partes.append(Parte(i, ref, len(bloco)))
                    i += 1
        self.indice.definir_partes(no_id, partes, tamanho)
        if antigas:
            self.arm.apagar(antigas)

    def buscar_tag(self, tag: str) -> list[No]:
        return self.indice.buscar_tag(tag.lstrip("#"))
