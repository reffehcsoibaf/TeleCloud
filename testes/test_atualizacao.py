"""Limpeza das pastas temporárias que o atualizador do painel deixava no Temp."""
import os
import time

import pytest

from telecloud import sistema


@pytest.fixture
def temp(tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


def _pasta(temp, nome, idade_s):
    p = temp / nome
    p.mkdir()
    (p / "TeleCloud.exe").write_bytes(b"x" * 10)
    t = time.time() - idade_s
    os.utime(p, (t, t))
    return p


def test_apaga_so_as_antigas_do_atualizador(temp):
    velha = _pasta(temp, "TeleCloud-atualizacao-abc", 3600)
    nova = _pasta(temp, "TeleCloud-atualizacao-def", 5)         # download que pode estar em andamento
    outra = _pasta(temp, "OutroPrograma-xyz", 3600)             # não é do TeleCloud
    sistema.limpar_downloads_antigos()
    assert not velha.exists()
    assert nova.exists()
    assert outra.exists()


def test_nao_mexe_em_arquivo_com_o_mesmo_prefixo(temp):
    arq = temp / "TeleCloud-atualizacao-arquivo"
    arq.write_text("x")
    t = time.time() - 3600
    os.utime(arq, (t, t))
    sistema.limpar_downloads_antigos()
    assert arq.exists()


def test_pasta_de_atualizacao_so_dentro_do_temp(temp, tmp_path_factory):
    fora = tmp_path_factory.mktemp("fora") / "TeleCloud-atualizacao-x"
    fora.mkdir()
    dentro = temp / "TeleCloud-atualizacao-y"
    dentro.mkdir()
    assert sistema._pasta_de_atualizacao(dentro)
    assert not sistema._pasta_de_atualizacao(fora)
    assert not sistema._pasta_de_atualizacao(temp / "TeleCloud-atualizacao-nao-existe")


def test_apagar_download_proprio_nao_faz_nada_fora_do_exe_empacotado(temp, monkeypatch):
    chamadas = []
    monkeypatch.setattr(sistema.subprocess, "Popen", lambda *a, **k: chamadas.append(a))
    sistema.apagar_download_proprio()     # em desenvolvimento (não empacotado)
    assert chamadas == []


def test_apagar_download_proprio_agenda_remocao_da_pasta_do_download(temp, monkeypatch):
    pasta = _pasta(temp, "TeleCloud-atualizacao-zzz", 5)
    chamadas = []
    monkeypatch.setattr(sistema.sys, "frozen", True, raising=False)
    monkeypatch.setattr(sistema.sys, "executable", str(pasta / "TeleCloud.exe"))
    monkeypatch.setattr(sistema.subprocess, "Popen", lambda *a, **k: chamadas.append(a[0]))
    sistema.apagar_download_proprio()
    assert len(chamadas) == 1 and str(pasta.resolve()) in chamadas[0] and "rmdir" in chamadas[0]


def test_apagar_download_proprio_ignora_a_copia_instalada(temp, monkeypatch):
    instalada = temp / "Programs" / "TeleCloud"
    instalada.mkdir(parents=True)
    chamadas = []
    monkeypatch.setattr(sistema.sys, "frozen", True, raising=False)
    monkeypatch.setattr(sistema.sys, "executable", str(instalada / "TeleCloud.exe"))
    monkeypatch.setattr(sistema.subprocess, "Popen", lambda *a, **k: chamadas.append(a[0]))
    sistema.apagar_download_proprio()
    assert chamadas == []
