def test_modulos_principais_importam():
    """Pega erro de sintaxe em módulos que nenhum outro teste carrega (ex.: o app)."""
    import telecloud.app  # noqa: F401


def test_painel_importa_e_compara_versoes():
    from telecloud import painel, sistema
    assert sistema.versao_em_numeros("v2026.11.14.2") == (2026, 11, 14, 2)
    assert sistema.versao_em_numeros("2026.11.9") == (2026, 11, 9, 0)
    assert painel.mais_nova("v2026.11.14.2", "2026.11.14")
    assert painel.mais_nova("2026.11.15", "2026.11.14.9")
    assert not painel.mais_nova("2026.11.14", "2026.11.14.0")
    assert not painel.mais_nova("2026.11.9", "2026.11.14.1")
