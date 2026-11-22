import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ferramentas"))
import lancar  # noqa: E402


def test_primeira_versao_do_dia_termina_em_zero():
    assert lancar.proxima_versao(date(2026, 11, 22), ["v2026.11.20.1", "v2026.11.9"]) == "2026.11.22.0"


def test_sobe_o_digito_quando_ja_saiu_versao_no_dia():
    tags = ["v2026.11.22.0", "v2026.11.22.1", "v2026.11.21.7"]
    assert lancar.proxima_versao(date(2026, 11, 22), tags) == "2026.11.22.2"


def test_tag_de_tres_numeros_vale_ponto_zero():
    assert lancar.proxima_versao(date(2026, 11, 9), ["v2026.11.9"]) == "2026.11.9.1"


def test_dia_nao_se_confunde_com_prefixo_parecido():
    # 2026.11.2 não pode contar tags do dia 22 nem do 20
    assert lancar.proxima_versao(date(2026, 11, 2), ["v2026.11.22.0", "v2026.11.20.3"]) == "2026.11.2.0"


def test_codigo_da_versao_cresce_com_a_data():
    a = lancar.codigo_da_versao("2026.11.22.3")
    assert a == 26112203
    assert lancar.codigo_da_versao("2026.11.22.4") > a
    assert lancar.codigo_da_versao("2026.12.1.0") > lancar.codigo_da_versao("2026.11.30.99")
    with pytest.raises(lancar.ErroLancamento):
        lancar.codigo_da_versao("2026.11.22.100")


def test_troca_de_versao_nos_arquivos():
    py = 'a = 1\nVERSAO = "2026.11.20.1"\nb = 2\n'
    assert lancar.trocar_versao_python(py, "2026.11.22.0") == 'a = 1\nVERSAO = "2026.11.22.0"\nb = 2\n'
    gr = '    versionCode = 28\n    versionName = "2026.11.22.26"\n'
    assert lancar.trocar_versao_gradle(gr, "2026.11.22.0") == '    versionCode = 26112200\n    versionName = "2026.11.22.0"\n'
    with pytest.raises(lancar.ErroLancamento):
        lancar.trocar_versao_python("nada", "2026.11.22.0")


def test_changelog_move_o_nao_lancado_para_a_versao():
    texto = "# Changelog\n\nintro\n\n## Não lançado\n\n- novo A\n- novo B\n\n## 2026.11.20.1 — 2026-11-21\n\n- velho\n"
    novo, notas = lancar.fechar_changelog(texto, "2026.11.22.0", date(2026, 11, 22))
    assert notas == "- novo A\n- novo B"
    assert novo.index("## Não lançado") < novo.index("## 2026.11.22.0 — 2026-11-22") < novo.index("## 2026.11.20.1")
    assert "- velho" in novo and novo.count("- novo A") == 1
    # a seção Não lançado fica vazia para a próxima rodada
    antes_da_versao = novo[novo.index("## Não lançado"):novo.index("## 2026.11.22.0")]
    assert antes_da_versao.strip() == "## Não lançado"


def test_changelog_vazio_ou_sem_secao_nao_lanca():
    with pytest.raises(lancar.ErroLancamento):
        lancar.fechar_changelog("# C\n\n## Não lançado\n\n## 2026.11.20.1 — x\n- a\n", "2026.11.22.0", date(2026, 11, 22))
    with pytest.raises(lancar.ErroLancamento):
        lancar.fechar_changelog("# C\n", "2026.11.22.0", date(2026, 11, 22))


def test_changelog_com_a_secao_no_fim_do_arquivo():
    novo, notas = lancar.fechar_changelog("# C\n\n## Não lançado\n\n- só isto\n", "2026.11.22.0", date(2026, 11, 22))
    assert notas == "- só isto" and "## 2026.11.22.0 — 2026-11-22" in novo
