import json

import pytest

from telecloud.login import ErroLogin, Fluxo

HASH = "0123456789abcdef0123456789abcdef"


class ClienteFalso:
    def __init__(self):
        self.autorizado = False

    async def connect(self):
        pass

    async def is_user_authorized(self):
        return self.autorizado

    async def send_code_request(self, tel):
        self.tel = tel

    async def sign_in(self, telefone=None, codigo=None, password=None):
        from telethon.errors import PhoneCodeInvalidError
        if password is None and codigo != "22222":
            raise PhoneCodeInvalidError(request=None)


class ArmFalso:
    def __init__(self, pasta):
        self.client = ClienteFalso()
        self.fechado = False

    def _rodar(self, coro):
        import asyncio
        return asyncio.run(coro)

    def conectar(self):
        self.conectado = True

    def fechar(self):
        self.fechado = True


def test_chaves_validadas_e_gravadas(tmp_path):
    f = Fluxo(tmp_path, fabrica_arm=ArmFalso)
    assert not f.tem_chaves()
    with pytest.raises(ErroLogin):
        f.passo_chaves("abc", HASH)
    with pytest.raises(ErroLogin):
        f.passo_chaves("123", "curto")
    assert f.passo_chaves(" 1234567 ", HASH.upper()) == "telefone"
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg == {"api_id": 1234567, "api_hash": HASH}
    assert f.tem_chaves()


def test_fluxo_completo(tmp_path):
    f = Fluxo(tmp_path, fabrica_arm=ArmFalso)
    f.passo_chaves("1234567", HASH)
    with pytest.raises(ErroLogin):
        f.passo_telefone("11999999999")
    assert f.passo_telefone("+55 11 99999-9999") == "codigo"
    assert f.telefone == "+5511999999999"
    with pytest.raises(ErroLogin):
        f.passo_codigo("99999")
    assert f.passo_codigo("22222") == "pronto"
    f.finalizar()
    assert f.arm is None


def test_ja_autorizado_pula_o_codigo(tmp_path):
    f = Fluxo(tmp_path, fabrica_arm=ArmFalso)
    f.passo_chaves("1", HASH)
    f.arm = ArmFalso(tmp_path)
    f.arm.client.autorizado = True
    assert f.passo_telefone("+5511999999999") == "pronto"
