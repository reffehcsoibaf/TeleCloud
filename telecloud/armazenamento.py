"""Interface do armazenamento remoto. O Telegram é uma implementação; a memória serve para testes."""
from abc import ABC, abstractmethod


class Armazenamento(ABC):
    @abstractmethod
    def enviar(self, pasta: str, nome: str, dados: bytes, legenda: str = "") -> str:
        """Envia um bloco e devolve a referência para recuperá-lo."""

    @abstractmethod
    def baixar(self, ref: str) -> bytes: ...

    @abstractmethod
    def apagar(self, refs: list[str]) -> None: ...

    def garantir_pasta(self, caminho: str) -> None:
        """Cria o tópico/lugar correspondente a uma pasta de primeiro nível (opcional)."""


class ArmazenamentoMemoria(Armazenamento):
    def __init__(self):
        self.blocos: dict[str, bytes] = {}
        self.legendas: dict[str, str] = {}
        self._n = 0

    def enviar(self, pasta, nome, dados, legenda=""):
        self._n += 1
        ref = f"{pasta}:{self._n}"
        self.blocos[ref] = bytes(dados)
        self.legendas[ref] = legenda
        return ref

    def baixar(self, ref):
        return self.blocos[ref]

    def apagar(self, refs):
        for r in refs:
            self.blocos.pop(r, None)
            self.legendas.pop(r, None)
