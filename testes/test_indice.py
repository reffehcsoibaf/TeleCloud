

def test_bytes_usados_soma_so_arquivos():
    from telecloud.indice import Indice, RAIZ
    ix = Indice()
    pasta = ix.criar(RAIZ, "p", True)
    ix.criar(pasta.id, "a.bin", False, 100)
    ix.criar(RAIZ, "b.bin", False, 250)
    assert ix.bytes_usados() == 350


def _com_arquivo(ix, pai, nome, refs, tam=10):
    from telecloud.indice import Parte
    n = ix.criar(pai, nome, False, tam)
    ix.definir_partes(n.id, [Parte(i, r, tam) for i, r in enumerate(refs)], tam * len(refs))
    return n


def test_mesclar_traz_arquivo_novo_do_celular():
    from telecloud.indice import Indice, RAIZ
    pc, cel = Indice(), Indice()
    pasta = pc.criar(RAIZ, "fotos", True)
    cel.criar(RAIZ, "fotos", True)           # números diferentes de propósito
    cel.criar(RAIZ, "extra", True)
    _com_arquivo(cel, cel.resolver("fotos").id, "a.jpg", ["101", "102"])
    n, antigas = pc.mesclar(cel.exportar())
    assert antigas == []
    assert n == 2  # pasta "extra" e o arquivo
    novo = pc.resolver("fotos/a.jpg")
    assert novo is not None and [p.ref for p in pc.partes(novo.id)] == ["101", "102"]
    assert pc.resolver("extra").pasta
    assert pc.mesclar(cel.exportar()) == (0, [])  # repetir não muda nada


def test_mesclar_substitui_pela_versao_mais_nova_e_devolve_partes_antigas():
    import time
    from telecloud.indice import Indice, RAIZ
    pc, cel = Indice(), Indice()
    _com_arquivo(pc, RAIZ, "x.bin", ["1"])
    time.sleep(1.1)
    _com_arquivo(cel, RAIZ, "x.bin", ["2", "3"])
    n, antigas = pc.mesclar(cel.exportar())
    assert n == 1 and antigas == ["1"]
    assert [p.ref for p in pc.partes(pc.resolver("x.bin").id)] == ["2", "3"]


def test_mesclar_nao_ressuscita_o_que_o_pc_apagou_depois_da_ultima_sincronia():
    import time
    from telecloud.indice import Indice, RAIZ
    pc, cel = Indice(), Indice()
    velho = _com_arquivo(cel, RAIZ, "apagado.bin", ["9"])
    cel.bd.execute("UPDATE nos SET modificado=? WHERE id=?", (time.time() - 3600, velho.id))
    cel.bd.commit()
    n, _ = pc.mesclar(cel.exportar(), desde=time.time() - 60)
    assert n == 0 and pc.resolver("apagado.bin") is None


def test_mesclar_ignora_envio_pendente_local():
    import time
    from telecloud.indice import Indice, RAIZ
    pc, cel = Indice(), Indice()
    pc.criar(RAIZ, "y.bin", False, 50)       # sem partes: envio ainda pendente
    time.sleep(1.1)
    _com_arquivo(cel, RAIZ, "y.bin", ["7"])
    assert pc.mesclar(cel.exportar()) == (0, [])
