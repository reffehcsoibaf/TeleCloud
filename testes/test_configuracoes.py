import json

import pytest

from telecloud.configuracoes import ErroConfig, cache_max_bytes, gravar_cache_gb, interpretar_gb


def test_interpretar_gb():
    assert interpretar_gb("5") == 5
    assert interpretar_gb(" 2,5 ") == 2.5
    assert interpretar_gb("0.5") == 0.5
    for ruim in ("", "abc", "0", "0,2", "-3", "99999"):
        with pytest.raises(ErroConfig):
            interpretar_gb(ruim)


def test_gravar_preserva_outras_chaves(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"api_id": 1, "api_hash": "x"}))
    assert cache_max_bytes(tmp_path) == 5120 * 1024 * 1024
    gravar_cache_gb(tmp_path, 2.5)
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg == {"api_id": 1, "api_hash": "x", "cache_max_mb": 2560}
    assert cache_max_bytes(tmp_path) == 2560 * 1024 * 1024


def test_pausa_envios(tmp_path):
    from telecloud.configuracoes import gravar_pausa, interpretar_pausa, pausa_envios_s
    assert pausa_envios_s(tmp_path) == 0
    assert interpretar_pausa("") == 0 and interpretar_pausa("1,5") == 1.5
    for ruim in ("abc", "-1", "61"):
        with pytest.raises(ErroConfig):
            interpretar_pausa(ruim)
    (tmp_path / "config.json").write_text(json.dumps({"api_id": 1}))
    gravar_pausa(tmp_path, 1.5)
    assert pausa_envios_s(tmp_path) == 1.5
    assert json.loads((tmp_path / "config.json").read_text())["api_id"] == 1
