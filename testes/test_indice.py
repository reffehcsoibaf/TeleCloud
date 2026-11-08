

def test_bytes_usados_soma_so_arquivos():
    from telecloud.indice import Indice, RAIZ
    ix = Indice()
    pasta = ix.criar(RAIZ, "p", True)
    ix.criar(pasta.id, "a.bin", False, 100)
    ix.criar(RAIZ, "b.bin", False, 250)
    assert ix.bytes_usados() == 350
