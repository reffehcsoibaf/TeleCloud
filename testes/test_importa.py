def test_modulos_principais_importam():
    """Pega erro de sintaxe em módulos que nenhum outro teste carrega (ex.: o app)."""
    import telecloud.app  # noqa: F401
