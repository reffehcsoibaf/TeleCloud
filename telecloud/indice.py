"""Índice local (SQLite): árvore de pastas, arquivos e partes guardadas no armazenamento."""
import sqlite3
import threading
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
        self._trava = threading.RLock()
        self.bd = sqlite3.connect(caminho, check_same_thread=False)
        self.bd.execute("PRAGMA foreign_keys=ON")
        self.mudancas = 0  # sobe a cada alteração; quem salva cópias compara com o último valor salvo
        self.bd.executescript(
            """
            CREATE TABLE IF NOT EXISTS nos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pai INTEGER REFERENCES nos(id) ON DELETE CASCADE,
                nome TEXT NOT NULL COLLATE NOCASE,
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
            CREATE TABLE IF NOT EXISTS apagar_pendentes(ref TEXT PRIMARY KEY);
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

    def bytes_usados(self) -> int:
        """Soma do tamanho de todos os arquivos (pastas não contam)."""
        return self.bd.execute("SELECT COALESCE(SUM(tamanho), 0) FROM nos WHERE pasta=0").fetchone()[0]

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

    def caminho_de(self, id: int) -> str:
        partes = []
        while id and id != RAIZ:
            n = self.obter(id)
            if not n:
                break
            partes.append(n.nome)
            id = n.pai
        return "/".join(reversed(partes))

    def definir_tamanho(self, no: int, tamanho: int):
        self.bd.execute(
            "UPDATE nos SET tamanho=?, modificado=? WHERE id=?", (tamanho, time.time(), no)
        )
        self.bd.commit()

    def pendentes_de_envio(self) -> list[int]:
        """Arquivos com conteúdo mas sem partes no armazenamento (envio interrompido)."""
        return [
            l[0]
            for l in self.bd.execute(
                "SELECT id FROM nos WHERE pasta=0 AND tamanho>0 "
                "AND id NOT IN (SELECT no FROM partes)"
            )
        ]

    # --- exclusões remotas ainda por fazer (sobrevivem a um fechamento do programa) ---
    def marcar_apagar(self, refs: list[str]):
        self.bd.executemany("INSERT OR IGNORE INTO apagar_pendentes(ref) VALUES(?)", [(r,) for r in refs])
        self.bd.commit()

    def apagados(self, refs: list[str]):
        self.bd.executemany("DELETE FROM apagar_pendentes WHERE ref=?", [(r,) for r in refs])
        self.bd.commit()

    def apagar_pendentes(self) -> list[str]:
        return [l[0] for l in self.bd.execute("SELECT ref FROM apagar_pendentes")]

    # --- cópia do índice (para guardar no armazenamento remoto) ---
    def exportar(self) -> bytes:
        import zlib
        return zlib.compress(self.bd.serialize(), 6)

    @staticmethod
    def gravar_copia(copia: bytes, caminho: str):
        """Escreve em `caminho` o índice contido em `copia` (resultado de exportar)."""
        import zlib
        with open(caminho, "wb") as f:
            f.write(zlib.decompress(copia))

    def fechar(self):
        self.bd.close()


def _travar(f):
    import functools

    @functools.wraps(f)
    def g(self, *a, **k):
        with self._trava:
            return f(self, *a, **k)

    return g


def _muta(f):
    import functools

    @functools.wraps(f)
    def g(self, *a, **k):
        r = f(self, *a, **k)
        self.mudancas += 1
        return r

    return g


for _n in ("criar", "definir_partes", "renomear", "definir_tags", "remover", "definir_tamanho",
           "marcar_apagar", "apagados"):
    setattr(Indice, _n, _muta(getattr(Indice, _n)))

for _n in ("resolver", "obter", "listar", "criar", "definir_partes", "partes", "renomear",
           "definir_tags", "remover", "refs_da_subarvore", "buscar_tag", "caminho_de",
           "definir_tamanho", "pendentes_de_envio", "marcar_apagar", "apagados",
           "apagar_pendentes", "exportar", "bytes_usados"):
    setattr(Indice, _n, _travar(getattr(Indice, _n)))

