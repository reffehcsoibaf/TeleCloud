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
            CREATE TABLE IF NOT EXISTS meta(chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
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
    _COL_NOME = 2

    def resolver(self, caminho: str) -> No | None:
        """Resolve 'a/b/c' (ou '\\a\\b\\c') para um nó; '' ou '/' é a raiz."""
        atual = RAIZ
        for parte in [p for p in caminho.replace("\\", "/").split("/") if p]:
            l = self.bd.execute(
                f"SELECT {self._COLS} FROM nos WHERE pai=? AND nome=?", (atual, parte)
            ).fetchone()
            if not l:
                # O Windows ignora maiúsculas/minúsculas (o Explorer manda o caminho em caixa alta ao renomear);
                # o COLLATE NOCASE do SQLite só cobre ASCII, então compara com casefold (acentos incluídos).
                alvo = parte.casefold()
                l = next(
                    (x for x in self.bd.execute(
                        f"SELECT {self._COLS} FROM nos WHERE pai=?", (atual,)) if x[self._COL_NOME].casefold() == alvo),
                    None,
                )
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

    # --- linhagem: dois aparelhos (PC e celular) editando o mesmo índice sem se atropelar ---
    # Cada publicação grava `geracao` (identificador novo) e `pai` (a geração em que ela se baseou). Quem recebe
    # uma cópia cujo `pai` é a sua geração atual, e não mexeu em nada desde então, pode adotá-la inteira: assim
    # apagar e renomear no celular valem no PC. Fora disso, só dá para mesclar o que é novo (`mesclar`).
    def _meta(self, chave: str) -> str:
        l = self.bd.execute("SELECT valor FROM meta WHERE chave=?", (chave,)).fetchone()
        return l[0] if l else ""

    def _definir_meta(self, chave: str, valor: str):
        self.bd.execute("INSERT OR REPLACE INTO meta(chave,valor) VALUES(?,?)", (chave, valor))
        self.bd.commit()

    def geracao(self) -> str:
        with self._trava:
            return self._meta("geracao")

    def preparar_publicacao(self) -> str:
        """Chamar logo antes de exportar: marca a cópia com uma geração nova, filha da geração atual."""
        import uuid
        with self._trava:
            base, nova = self._meta("geracao"), uuid.uuid4().hex
            self._definir_meta("pai", base)
            self._definir_meta("geracao", nova)
            return nova

    @staticmethod
    def linhagem(copia: bytes) -> tuple[str, str]:
        """(geração, pai) gravados numa cópia do índice; ('', '') se ela não tem linhagem (versão antiga)."""
        import zlib
        remoto = sqlite3.connect(":memory:")
        try:
            remoto.deserialize(zlib.decompress(copia))
            m = dict(remoto.execute("SELECT chave,valor FROM meta"))
            return m.get("geracao", ""), m.get("pai", "")
        except sqlite3.Error:
            return "", ""
        finally:
            remoto.close()

    def substituir(self, copia: bytes):
        """Troca todo o conteúdo pelo da cópia (ver `linhagem`). Não conta como mudança local."""
        import zlib
        remoto = sqlite3.connect(":memory:")
        try:
            remoto.deserialize(zlib.decompress(copia))
            nos = list(remoto.execute("SELECT id,pai,nome,pasta,tamanho,modificado,tags FROM nos"))
            partes = list(remoto.execute("SELECT no,seq,ref,tamanho FROM partes"))
            try:
                meta = list(remoto.execute("SELECT chave,valor FROM meta"))
            except sqlite3.Error:
                meta = []
        finally:
            remoto.close()
        with self._trava:
            self.bd.execute("BEGIN")
            try:
                self.bd.execute("PRAGMA defer_foreign_keys=ON")
                self.bd.execute("DELETE FROM partes")
                self.bd.execute("DELETE FROM nos")
                self.bd.executemany("INSERT INTO nos(id,pai,nome,pasta,tamanho,modificado,tags) VALUES(?,?,?,?,?,?,?)", nos)
                self.bd.executemany("INSERT INTO partes(no,seq,ref,tamanho) VALUES(?,?,?,?)", partes)
                self.bd.execute("DELETE FROM meta")
                self.bd.executemany("INSERT INTO meta(chave,valor) VALUES(?,?)", meta)
                self.bd.execute("COMMIT")
            except Exception:
                self.bd.execute("ROLLBACK")
                raise

    def mesclar(self, copia: bytes, desde: float = 0.0) -> tuple[int, list[str]]:
        """Incorpora ao índice local o que existe só na cópia remota (feita por outro aparelho, como o celular).

        A comparação é por caminho (os números dos nós divergem entre aparelhos). Só entra o que for novo ou
        mais recente que `desde` (menos 5 min de folga entre os relógios): assim, o que o PC apagou depois da
        última sincronização não ressuscita só porque a cópia do celular ainda o tinha. Arquivo que existe nos
        dois lados com partes diferentes fica com a versão mais recente.
        Devolve (quantos itens mudaram, referências de partes antigas que já podem ser apagadas do Telegram)."""
        import zlib
        remoto = sqlite3.connect(":memory:")
        try:
            remoto.deserialize(zlib.decompress(copia))
            nos = list(remoto.execute("SELECT id,pai,nome,pasta,tamanho,modificado,tags FROM nos"))
            partes: dict[int, list[Parte]] = {}
            for no, seq, ref, tam in remoto.execute("SELECT no,seq,ref,tamanho FROM partes ORDER BY no,seq"):
                partes.setdefault(no, []).append(Parte(seq, ref, tam))
        finally:
            remoto.close()
        filhos: dict[int, list] = {}
        for n in nos:
            if n[1] is not None:
                filhos.setdefault(n[1], []).append(n)
        margem = desde - 300
        mudou, antigas = 0, []
        with self._trava:
            fila = [(RAIZ, RAIZ)]  # (id remoto, id local)
            while fila:
                rid, lid = fila.pop()
                locais = {x.nome.casefold(): x for x in self.listar(lid)}
                for r in sorted(filhos.get(rid, []), key=lambda x: x[0]):
                    _, _, nome, pasta, tam, modif, tags = r
                    loc = locais.get(nome.casefold())
                    if pasta:
                        if loc is None:
                            if modif < margem:
                                continue
                            loc = self.criar(lid, nome, True)
                            mudou += 1
                        elif not loc.pasta:
                            continue
                        fila.append((r[0], loc.id))
                        continue
                    ps = partes.get(r[0])
                    if not ps:
                        continue
                    if loc is None:
                        if modif < margem:
                            continue
                        loc = self.criar(lid, nome, False, tam)
                    elif loc.pasta or modif <= loc.modificado + 1:
                        continue
                    else:
                        atuais = self.partes(loc.id)
                        if not atuais or [p.ref for p in atuais] == [p.ref for p in ps]:
                            continue  # sem partes = envio ainda pendente; iguais = nada a fazer
                        antigas += [p.ref for p in atuais]
                    self.definir_partes(loc.id, ps, tam)
                    self.bd.execute("UPDATE nos SET modificado=?, tags=? WHERE id=?", (modif, tags, loc.id))
                    self.bd.commit()
                    mudou += 1
        return mudou, antigas

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

