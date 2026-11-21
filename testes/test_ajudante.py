r"""O ajudante roda como SYSTEM: precisa recusar tudo que não seja uma letra livre e um volume \Device\Volume{GUID}."""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("ajudante", Path(__file__).resolve().parent.parent / "ajudante.py")
ajudante = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ajudante)

GUID = r"\Device\Volume{bd1e02c8-e515-11f1-ac30-94085327e844}"


@pytest.mark.parametrize("letra", ["T:", "D:", "Z:"])
def test_letras_aceitas(letra):
    assert ajudante.RE_LETRA.match(letra)


@pytest.mark.parametrize("letra", ["C:", "A:", "B:", "T", "T:\\", "TT:", "1:", "", "T: "])
def test_letras_recusadas(letra):
    assert not ajudante.RE_LETRA.match(letra)


def test_alvo_aceito():
    assert ajudante.RE_ALVO.match(GUID)


@pytest.mark.parametrize("alvo", [
    r"\Device\HarddiskVolume3", r"\Device\Volume{x}", r"\??\C:", r"\Device\Volume{bd1e02c8-e515-11f1-ac30-94085327e844}\x",
    GUID + " ", "", r"\Device\Volume{bd1e02c8-e515-11f1-ac30-94085327e84}",
])
def test_alvos_recusados(alvo):
    assert not ajudante.RE_ALVO.match(alvo)


@pytest.mark.parametrize("argv", [[], ["T:"], ["T:", GUID], ["C:", GUID, "1"], ["T:", r"\Device\HarddiskVolume1", "1"], ["T:", GUID, "abc"]])
def test_principal_recusa_argumentos_ruins(argv, monkeypatch):
    monkeypatch.setattr(ajudante, "registrar", lambda t: None)
    assert ajudante.principal(argv) == 2
