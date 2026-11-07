"""Índice local (SQLite): árvore de pastas, arquivos e partes guardadas no armazenamento."""
import sqlite3
import time
from dataclasses import dataclass


@dataclass
class No:
    id: int
    pai: int | None
    nome: str
    pasta: bool
    tamanho: int
    modificado: float
    tags: str = ""


@dataclass
class Parte:
    seq: int
    ref: str  # identificador da mensagem no armazenamento (ex.: "topico:mensagem")
    tamanho: int


RAIZ = 1


class Indice:
    def __init__(self, caminho=":memory:"):
        self.bd = sqlite3.connect(caminho, check_same_thread=False)
        self.bd.execute("PRAGMA foreign_keys=ON")
        self.bd.executescript(
            """
            CREATE TABLE IF NOT EXISTS nos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pai INTEGER REFERENCES nos(id) ON DELETE CASCADE,
                nome TEXT NOT NULL,
                pasta INTEGER NOT NULL,
                tamanho INTEGER NOT NULL DEFAULT 0,
                modificado REAL NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                UNIQUE(pai, nome)
            );
            CREATE TABLE IF NOT EXISTS partes(
                no INTEGER NOT NULL REFERENCES nos(id) ON DELETE CASCADE,
                seq INTEGER NOT NULL,
                ref TEXT NOT NULL,
                tamanho INTEGER NOT NULL,
                PRIMARY KEY(no, seq)
            );
            """
        )
        self.bd.execute(
            "INSERT OR IGNORE INTO nos(id, pai, nome, pasta, modificado) VALUES(?,NULL,'',1,?)",
            (RAIZ, time.time()),
        )
        self.bd.commit()

    @staticmethod
    def _no(l):
        return No(l[0], l[1], l[2], bool(l[3]), l[4], l[5], l[6])

    _COLS = "id,pai,nome,pasta,tamanho,modificado,tags"

    def resolver(self, caminho: str) -> No | None:
        """Resolve 'a/b/c' (ou '\\a\\b\\c') para um nó; '' ou '/' é a raiz."""
        atual = RAIZ
        for parte in [p for p in caminho.replace("\\", "/").split("/") if p]:
            l = self.bd.execute(
                f"SELECT {self._COLS} FROM nos WHERE pai=? AND nome=?", (atual, parte)
            ).fetchone()
            if not l:
                return None
            atual = l[0]
        return self.obter(atual)

    def obter(self, id: int) -> No | None:
        l = self.bd.execute(f"SELECT {self._COLS} FROM nos WHERE id=?", (id,)).fetchone()
        return self._no(l) if l else None

    def listar(self, pai: int) -> list[No]:
        return [
            self._no(l)
            for l in self.bd.execute(
                f"SELECT {self._COLS} FROM nos WHERE pai=? ORDER BY pasta DESC, nome COLLATE NOCASE",
                (pai,),
            )
        ]

    def criar(self, pai: int, nome: str, pasta: bool, tamanho=0) -> No:
        cur = self.bd.execute(
            "INSERT INTO nos(pai,nome,pasta,tamanho,modificado) VALUES(?,?,?,?,?)",
            (pai, nome, int(pasta), tamanho, time.time()),
        )
        self.bd.commit()
        return self.obter(cur.lastrowid)

    def definir_partes(self, no: int, partes: list[Parte], tamanho: int):
        self.bd.execute("DELETE FROM partes WHERE no=?", (no,))
        self.bd.executemany(
            "INSERT INTO partes(no,seq,ref,tamanho) VALUES(?,?,?,?)",
            [(no, p.seq, p.ref, p.tamanho) for p in partes],
        )
        self.bd.execute(
            "UPDATE nos SET tamanho=?, modificado=? WHERE id=?", (tamanho, time.time(), no)
        )
        self.bd.commit()

    def partes(self, no: int) -> list[Parte]:
        return [
            Parte(*l)
            for l in self.bd.execute(
                "SELECT seq,ref,tamanho FROM partes WHERE no=? ORDER BY seq", (no,)
            )
        ]

    def renomear(self, no: int, novo_pai: int, novo_nome: str):
        self.bd.execute(
            "UPDATE nos SET pai=?, nome=?, modificado=? WHERE id=?",
            (novo_pai, novo_nome, time.time(), no),
        )
        self.bd.commit()

    def definir_tags(self, no: int, tags: list[str]):
        self.bd.execute("UPDATE nos SET tags=? WHERE id=?", (" ".join(tags), no))
        self.bd.commit()

    def remover(self, no: int):
        self.bd.execute("DELETE FROM nos WHERE id=?", (no,))
        self.bd.commit()

    def refs_da_subarvore(self, no: int) -> list[str]:
        """Todas as referências de partes sob um nó (para apagar no armazenamento)."""
        return [
            l[0]
            for l in self.bd.execute(
                """
                WITH RECURSIVE sub(id) AS (
                    SELECT ? UNION ALL SELECT n.id FROM nos n JOIN sub s ON n.pai=s.id)
                SELECT ref FROM partes WHERE no IN sub
                """,
                (no,),
            )
        ]

    def buscar_tag(self, tag: str) -> list[No]:
        return [
            self._no(l)
            for l in self.bd.execute(
                f"SELECT {self._COLS} FROM nos WHERE (' '||tags||' ') LIKE ?", (f"% {tag} %",)
            )
        ]

    def fechar(self):
        self.bd.close()
