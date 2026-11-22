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


def test_cache_completo_sobrevive_a_reinicio(tmp_path):
    arm = ArmazenamentoMemoria()
    ix = Indice(str(tmp_path / "i.db"))
    nuvem = Nuvem(ix, arm, tamanho_parte=4)
    no = nuvem.gravar("a.bin", b"0123456789")
    pasta = tmp_path / "cache"
    pasta.mkdir()
    (pasta / f"{no.id}.bin").write_bytes(b"0123456789")
    (pasta / f"{no.id}.ok").write_text("10")
    un = Unidade(nuvem, pasta)
    try:
        e = un._estado(no.id)
        assert (pasta / f"{no.id}.bin").exists() and e.completo and e.integro
        e.desmarcar_integro()          # qualquer escrita invalida a marca
        assert not (pasta / f"{no.id}.ok").exists()
    finally:
        un.parar()
    # sem marca (ou com tamanho diferente): o cache é apagado ao reiniciar
    un2 = Unidade(nuvem, pasta)
    try:
        assert not (pasta / f"{no.id}.bin").exists()
    finally:
        un2.parar()


def test_limpar_cache_a_pedido_apaga_tudo_que_ja_esta_no_telegram(tmp_path):
    un, nuvem, arm = _unidade(tmp_path, cache_max=10**9)
    try:
        no = nuvem.gravar("a.bin", b"0123456789")
        e = un._estado(no.id)
        e.abrir().write(b"0123456789")
        e.fechar_fh()
        e.tamanho = 10
        e.marcar_integro()
        assert un.limpar_cache() == 0            # dentro do limite: não apaga
        assert (un.cache_dir / f"{no.id}.bin").exists()
        assert un.limpar_cache(0) == 10          # pedido do usuário: apaga
        assert not (un.cache_dir / f"{no.id}.bin").exists() and not (un.cache_dir / f"{no.id}.ok").exists()
    finally:
        un.parar()


def test_limpar_cache_apaga_copias_de_sessoes_anteriores(tmp_path):
    """Cópias mantidas ao reiniciar não estão em un.estados; antes ficavam para sempre no disco."""
    import os
    arm = ArmazenamentoMemoria()
    nuvem = Nuvem(Indice(str(tmp_path / "i.db")), arm, tamanho_parte=4)
    velho = nuvem.gravar("velho.bin", b"0123456789")
    novo = nuvem.gravar("novo.bin", b"0123456789")
    pasta = tmp_path / "cache"
    pasta.mkdir()
    for no, t in ((velho, 1000), (novo, 2000)):
        (pasta / f"{no.id}.bin").write_bytes(b"0123456789")
        (pasta / f"{no.id}.ok").write_text("10")
        os.utime(pasta / f"{no.id}.bin", (t, t))
    un = Unidade(nuvem, pasta, cache_max=15)
    try:
        (pasta / "9999.bin").write_bytes(b"sem dono")  # arquivo que não existe mais no índice
        assert not un.estados                          # ninguém abriu nada nesta sessão
        liberado = un.limpar_cache()
        assert sorted(p.name for p in pasta.glob("*.bin")) == [f"{novo.id}.bin"]   # fica o mais recente
        assert liberado == 10 + 8
        assert un.limpar_cache(0) == 10 and not list(pasta.glob("*.bin"))
    finally:
        un.parar()


def _publicar_do_celular(arm, base_copia, alterar):
    """Simula o celular: parte da cópia do PC, altera e publica uma cópia filha no armazenamento."""
    cel = Indice()
    cel.substituir(base_copia)
    alterar(cel)
    cel.preparar_publicacao()
    arm.salvar_indice(cel.exportar())


def test_unidade_adota_copia_do_celular_quando_pc_nao_mexeu(tmp_path):
    un, nuvem, arm = _unidade(tmp_path, silencio_indice=0.2)
    try:
        nuvem.criar_pasta("Docs")
        nuvem.gravar("Docs/a.txt", b"abc")
        assert un.salvar_indice_agora()
        base = arm.copia_indice
        _publicar_do_celular(arm, base, lambda c: c.remover(c.resolver("Docs/a.txt").id))
        assert un.sincronizar_indice() == 1
        assert nuvem.indice.resolver("Docs/a.txt") is None     # a exclusão do celular valeu no PC
        assert nuvem.indice.resolver("Docs") is not None
    finally:
        un.parar()


def test_unidade_so_mescla_quando_pc_tem_mudanca_nao_publicada(tmp_path):
    un, nuvem, arm = _unidade(tmp_path, silencio_indice=60)    # não publica sozinho durante o teste
    try:
        nuvem.criar_pasta("Docs")
        nuvem.gravar("Docs/a.txt", b"abc")
        assert un.salvar_indice_agora()
        base = arm.copia_indice
        nuvem.criar_pasta("SoDoPC")                              # mudança local ainda não publicada
        def celular(c):
            c.remover(c.resolver("Docs/a.txt").id)
            c.criar(RAIZ, "SoDoCelular", True)
        _publicar_do_celular(arm, base, celular)
        un.sincronizar_indice()
        assert nuvem.indice.resolver("SoDoPC") is not None       # nada do PC se perdeu
        assert nuvem.indice.resolver("SoDoCelular") is not None  # o novo do celular entrou (mescla)
        assert nuvem.indice.resolver("Docs/a.txt") is not None   # a exclusão não vale na mescla (limitação conhecida)
    finally:
        un.parar()
