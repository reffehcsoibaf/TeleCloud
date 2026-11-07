import os

import pytest

from telecloud.armazenamento import ArmazenamentoMemoria
from telecloud.indice import Indice
from telecloud.nuvem import ErroNuvem, Nuvem


def nova(chave=None, parte=10):
    arm = ArmazenamentoMemoria()
    return Nuvem(Indice(), arm, chave, tamanho_parte=parte), arm


def test_gravar_e_ler_em_varias_partes():
    n, arm = nova()
    n.criar_pasta("Fotos")
    dados = os.urandom(35)
    n.gravar("Fotos/a.bin", dados)
    assert len(arm.blocos) == 4
    assert n.ler("Fotos/a.bin") == dados
    assert n.ler("Fotos/a.bin", 8, 15) == dados[8:23]


def test_cifra_nao_vaza_e_volta():
    n, arm = nova(chave=os.urandom(32))
    n.gravar("x.txt", b"segredo segredo segredo")
    assert all(b"segredo" not in b for b in arm.blocos.values())
    assert n.ler("x.txt") == b"segredo segredo segredo"


def test_mover_nao_reenvia():
    n, arm = nova()
    n.criar_pasta("A")
    n.criar_pasta("B")
    n.gravar("A/f", b"123")
    antes = dict(arm.blocos)
    n.mover("A/f", "B/g")
    assert arm.blocos == antes
    assert n.ler("B/g") == b"123"
    assert [x.nome for x in n.listar("A")] == []


def test_sobrescrever_apaga_partes_antigas():
    n, arm = nova()
    n.gravar("f", b"a" * 25)
    n.gravar("f", b"b")
    assert len(arm.blocos) == 1
    assert n.ler("f") == b"b"


def test_apagar_e_pasta_cheia():
    n, arm = nova()
    n.criar_pasta("P")
    n.gravar("P/f", b"1")
    with pytest.raises(ErroNuvem):
        n.apagar("P")
    n.apagar("P/f")
    n.apagar("P")
    assert not arm.blocos


def test_tags():
    n, _ = nova()
    n.gravar("f", b"1", tags=["viagem", "#2026"])
    assert [x.nome for x in n.buscar_tag("viagem")] == ["f"]
    assert n.buscar_tag("outra") == []
