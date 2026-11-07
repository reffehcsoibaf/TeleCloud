import time

from telecloud.armazenamento import ArmazenamentoMemoria
from telecloud.indice import RAIZ, Indice
from telecloud.nuvem import Nuvem
from telecloud.unidade import Unidade


def test_copia_do_indice_restaura_tudo(tmp_path):
    arm = ArmazenamentoMemoria()
    ix = Indice(str(tmp_path / "a.db"))
    nuvem = Nuvem(ix, arm, tamanho_parte=4)
    nuvem.criar_pasta("Docs")
    nuvem.gravar("Docs/x.txt", b"0123456789", tags=["lazer"])
    arm.salvar_indice(ix.exportar())
    ix.fechar()

    # "computador novo": só existe a cópia guardada no armazenamento
    Indice.gravar_copia(arm.carregar_indice(), str(tmp_path / "b.db"))
    novo = Nuvem(Indice(str(tmp_path / "b.db")), arm, tamanho_parte=4)
    assert novo.ler("Docs/x.txt") == b"0123456789"
    assert [n.nome for n in novo.buscar_tag("lazer")] == ["x.txt"]


def test_mudancas_conta_alteracoes():
    ix = Indice()
    antes = ix.mudancas
    ix.listar(RAIZ)
    assert ix.mudancas == antes
    ix.criar(RAIZ, "a", True)
    assert ix.mudancas > antes


def test_exclusoes_pendentes_sobrevivem(tmp_path):
    ix = Indice(str(tmp_path / "i.db"))
    ix.marcar_apagar(["1", "2"])
    ix.fechar()
    ix = Indice(str(tmp_path / "i.db"))
    assert sorted(ix.apagar_pendentes()) == ["1", "2"]
    ix.apagados(["1", "2"])
    assert ix.apagar_pendentes() == []


def test_nuvem_apagar_limpa_pendencia():
    arm = ArmazenamentoMemoria()
    nuvem = Nuvem(Indice(), arm)
    nuvem.gravar("a.txt", b"oi")
    nuvem.apagar("a.txt")
    assert nuvem.indice.apagar_pendentes() == [] and not arm.blocos


def _unidade(tmp_path, **kw):
    arm = ArmazenamentoMemoria()
    nuvem = Nuvem(Indice(), arm, tamanho_parte=4)
    return Unidade(nuvem, tmp_path / "cache", **kw), nuvem, arm


def test_cache_libera_o_mais_antigo_primeiro(tmp_path):
    un, nuvem, arm = _unidade(tmp_path, cache_max=15)
    try:
        ids = []
        for nome in ("a", "b", "c"):
            no = nuvem.indice.criar(RAIZ, nome, False)
            e = un._estado(no.id)
            e.cache.write_bytes(b"x" * 10)
            e.tamanho = 10
            nuvem.enviar_no(no.id, str(e.cache))
            e.completo = True
            ids.append(no.id)
            time.sleep(0.01)
        un.estados[ids[0]].acesso = 1
        un.estados[ids[1]].acesso = 2
        un.estados[ids[2]].acesso = 3
        un.limpar_cache()
        existentes = sorted(p.stem for p in (tmp_path / "cache").glob("*.bin"))
        assert existentes == [str(ids[2])]
        assert ids[0] not in un.estados and ids[2] in un.estados
        # o arquivo liberado volta do armazenamento quando lido de novo
        e = un._estado(ids[0])
        assert not e.completo
        un._garantir(e, 0, 10)
        assert e.cache.read_bytes() == b"x" * 10
    finally:
        un.parar()


def test_cache_nao_libera_arquivo_aberto_nem_pendente(tmp_path):
    un, nuvem, arm = _unidade(tmp_path, cache_max=0)
    try:
        aberto = nuvem.indice.criar(RAIZ, "aberto", False)
        e = un._estado(aberto.id)
        e.cache.write_bytes(b"yy")
        e.tamanho = 2
        nuvem.enviar_no(aberto.id, str(e.cache))
        e.refs = 1
        pendente = nuvem.indice.criar(RAIZ, "pendente", False)
        p = un._estado(pendente.id)
        p.cache.write_bytes(b"zz")
        p.tamanho = 2
        p.sujo = True
        un.limpar_cache()
        assert e.cache.exists() and p.cache.exists()
    finally:
        un.parar()


def test_indice_e_guardado_apos_silencio(tmp_path):
    un, nuvem, arm = _unidade(tmp_path, silencio_indice=0.2)
    try:
        nuvem.criar_pasta("Novo")
        for _ in range(60):
            if arm.copia_indice:
                break
            time.sleep(0.2)
        assert arm.copia_indice
        assert un.indice_salvo_em
    finally:
        un.parar()


def test_falha_no_meio_do_envio_nao_deixa_partes_soltas(tmp_path):
    class Falha(ArmazenamentoMemoria):
        def enviar(self, *a, **k):
            if self._n >= 1:
                raise RuntimeError("rede caiu")
            return super().enviar(*a, **k)

    arm = Falha()
    nuvem = Nuvem(Indice(), arm, tamanho_parte=4)
    no = nuvem.indice.criar(RAIZ, "f", False)
    f = tmp_path / "f.bin"
    f.write_bytes(b"0123456789")
    try:
        nuvem.enviar_no(no.id, str(f))
        assert False
    except RuntimeError:
        pass
    assert not arm.blocos and not nuvem.indice.partes(no.id)
