import threading

from telecloud.armazenamento import ArmazenamentoMemoria
from telecloud.bandeja import Bandeja, _tamanho
from telecloud.indice import RAIZ, Indice
from telecloud.nuvem import Nuvem
from telecloud.unidade import Unidade


def test_tamanho_legivel():
    assert _tamanho(512) == "512 B"
    assert _tamanho(1536) == "1,5 KB"
    assert _tamanho(5 * 1024**3) == "5,0 GB"


def test_resumo_e_fila(tmp_path):
    nuvem = Nuvem(Indice(), ArmazenamentoMemoria())
    un = Unidade(nuvem, tmp_path / "c")
    sair = threading.Event()
    try:
        b = Bandeja(un, "T:", tmp_path, sair.set)
        assert b._resumo() == ("Tudo enviado", "ok")
        assert [str(i.text) for i in b._itens_fila()] == ["Nenhum envio pendente"]

        no = nuvem.indice.criar(RAIZ, "relatorio.txt", False)
        e = un._estado(no.id)
        e.sujo = True
        texto, nivel = b._resumo()
        assert "1 arquivo" in texto and nivel == "ocupado"
        assert "Esperando: relatorio.txt" in [str(i.text) for i in b._itens_fila()]

        un.atual, un.progresso = "pasta/video.mp4", (50, 100)
        un._enviando_id = None
        assert "Enviando video.mp4 (50%)" in b._resumo()[0]

        un.erro = "OSError: sem rede"
        assert b._resumo()[1] == "erro"

        b._sair()
        assert sair.wait(2) and b._resumo()[0].startswith("Encerrando")
    finally:
        un.parar()


def test_menu_monta_com_todos_os_itens(tmp_path):
    un = Unidade(Nuvem(Indice(), ArmazenamentoMemoria()), tmp_path / "c")
    try:
        b = Bandeja(un, "T:", tmp_path, lambda: None)
        textos = [i.text for i in b.icone.menu.items if str(i.text) != "-"]
        assert len(textos) >= 8
        assert any("Sair" == str(t) for t in textos)
    finally:
        un.parar()


def test_pausa_do_telegram_vale_ate_reabrir(tmp_path):
    import time
    nuvem = Nuvem(Indice(), ArmazenamentoMemoria())
    un = Unidade(nuvem, tmp_path / "c")
    try:
        assert un.pausa_ate == 0
        un._definir_pausa(600)
        b = Bandeja(un, "T:", tmp_path, threading.Event().set)
        texto, nivel = b._resumo()
        assert texto.startswith("O Telegram pediu uma pausa") and nivel == "ocupado"
    finally:
        un.parar()
    outra = Unidade(Nuvem(Indice(), ArmazenamentoMemoria()), tmp_path / "c")
    try:
        assert outra.pausa_ate > time.time() + 500   # a pausa sobrevive a fechar e abrir o programa
    finally:
        outra.parar()


def test_menu_tem_desconectar_so_quando_ha_acao(tmp_path):
    nuvem = Nuvem(Indice(), ArmazenamentoMemoria())
    un = Unidade(nuvem, tmp_path / "c")
    try:
        sem = Bandeja(un, "T:", tmp_path, lambda: None)
        com = Bandeja(un, "T:", tmp_path, lambda: None, ao_desconectar=lambda: None)
        textos = lambda b: [str(i.text) for i in b.icone.menu.items]
        assert not any("Desconectar" in t for t in textos(sem))
        assert any("Desconectar a conta" in t for t in textos(com))
    finally:
        un.parar()
