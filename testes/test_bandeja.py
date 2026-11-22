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
        assert b.un.situacao()["esperando"] == []

        no = nuvem.indice.criar(RAIZ, "relatorio.txt", False)
        e = un._estado(no.id)
        e.sujo = True
        texto, nivel = b._resumo()
        assert "1 arquivo" in texto and nivel == "ocupado"
        assert "relatorio.txt" in b.un.situacao()["esperando"]

        un.atual, un.progresso = "pasta/video.mp4", (50, 100)
        un._enviando_id = None
        assert "Enviando video.mp4 (50%)" in b._resumo()[0]

        un.erro = "OSError: sem rede"
        assert b._resumo()[1] == "erro"

        b._sair()
        assert sair.wait(2) and b._resumo()[0].startswith("Encerrando")
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


def test_menu_da_bandeja_so_tem_unidade_painel_e_sair(tmp_path):
    nuvem = Nuvem(Indice(), ArmazenamentoMemoria())
    un = Unidade(nuvem, tmp_path / "c")
    try:
        b = Bandeja(un, "T:", tmp_path, lambda: None, ao_desconectar=lambda: None)
        textos = [str(i.text) for i in b.icone.menu.items]
        assert textos == ["Abrir a unidade T:", "Abrir o painel de controle", "Sair"]
    finally:
        un.parar()


def test_painel_mostra_cache_fila_e_indice(tmp_path):
    from telecloud import painel
    e = {"cache": 12 * 1024**3, "cache_max": 10 * 1024**3, "enviando": "a.bin", "progresso": [1024, 2048],
         "esperando": ["b.bin", "c.bin"], "apagando": 0, "indice_salvo_em": 0}
    t = painel.texto_cache(e)
    assert "12,0 GB usados de 10,0 GB (120%)" in t and "Acima do limite" in t
    assert "Acima" not in painel.texto_cache({"cache": 1024, "cache_max": 10 * 1024**3})
    f = painel.texto_fila(e)
    assert "Enviando: a.bin - 1,0 KB de 2,0 KB" in f and "Esperando: c.bin" in f
    assert painel.texto_fila({"esperando": [], "enviando": None}) == "Nenhum envio pendente."
    assert painel.texto_indice(e) == "Ainda não guardado nesta sessão."
    assert painel.texto_cache(None) == "Ainda sem informação."


def test_bandeja_grava_estado_para_o_painel(tmp_path):
    import json
    nuvem = Nuvem(Indice(), ArmazenamentoMemoria())
    un = Unidade(nuvem, tmp_path / "c")
    try:
        b = Bandeja(un, "T:", tmp_path, lambda: None)
        b._atualizar(forcar=True)
        e = json.loads((tmp_path / "estado.json").read_text(encoding="utf-8"))
        assert e["texto"] == "Tudo enviado" and e["unidade"] == "T:" and e["pendentes"] == 0
        assert b._config_mudou() is False
        (tmp_path / "config.json").write_text("{}")
        assert b._config_mudou() is False       # primeira leitura só marca a referência
        (tmp_path / "config.json").write_text('{"a": 1}')
        import os
        os.utime(tmp_path / "config.json", (1, 1))
        assert b._config_mudou() is True
    finally:
        un.parar()
