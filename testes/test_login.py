import json

import pytest

from telecloud.credenciais import ErroCredenciais, MyTelegram, extrair_chaves, extrair_token_de_criacao
from telecloud.login import Fluxo

HTML_COM_APP = '''
<label for="app_id" class="col-md-4 text-right control-label">App api_id:</label>
<div class="col-md-7"><span class="form-control input-xlarge uneditable-input" onclick="this.select();"><strong>1234567</strong></span></div>
<label for="app_hash" class="col-md-4 text-right control-label">App api_hash:</label>
<div class="col-md-7"><span class="form-control input-xlarge uneditable-input" onclick="this.select();">0123456789abcdef0123456789ABCDEF</span></div>
'''
HTML_SEM_APP = '<form action="/apps/create"><input type="hidden" name="hash" value="abc123def"/></form>'


def test_extrair_chaves():
    assert extrair_chaves(HTML_COM_APP) == (1234567, "0123456789abcdef0123456789abcdef")
    assert extrair_chaves(HTML_SEM_APP) is None
    assert extrair_token_de_criacao(HTML_SEM_APP) == "abc123def"


class SiteFalso(MyTelegram):
    def __init__(self, tem_app):
        super().__init__()
        self.tem_app = tem_app
        self.chamadas = []

    def _requisitar(self, caminho, dados=None):
        self.chamadas.append((caminho, dados))
        if caminho == "/auth/send_password":
            return json.dumps({"random_hash": "h1"})
        if caminho == "/auth/login":
            return "true" if dados["password"] == "11111" else "Invalid confirmation code"
        if caminho == "/apps":
            return HTML_COM_APP if self.tem_app else HTML_SEM_APP
        if caminho == "/apps/create":
            self.tem_app = True
            return ""
        raise AssertionError(caminho)


def test_site_cria_app_quando_nao_existe():
    s = SiteFalso(tem_app=False)
    s.enviar_codigo("+5511999999999")
    with pytest.raises(ErroCredenciais):
        s.entrar("00000")
    s.entrar("11111")
    assert s.obter_ou_criar() == (1234567, "0123456789abcdef0123456789abcdef")
    criar = [d for c, d in s.chamadas if c == "/apps/create"][0]
    assert criar["app_title"] == "TeleCloud" and criar["hash"] == "abc123def"


def test_site_usa_app_existente_sem_criar():
    s = SiteFalso(tem_app=True)
    s.enviar_codigo("+5511999999999")
    s.entrar("11111")
    assert s.obter_ou_criar()[0] == 1234567
    assert not [c for c, _ in s.chamadas if c == "/apps/create"]


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


def test_fluxo_completo_primeira_vez(tmp_path):
    f = Fluxo(tmp_path, site=SiteFalso(tem_app=False), fabrica_arm=ArmFalso)
    with pytest.raises(ErroCredenciais):
        f.passo_telefone("11999999999")
    assert f.passo_telefone("+55 11 99999-9999".replace("-", "")) == "codigo_site"
    assert f.passo_codigo_site("11111") == "codigo_app"
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["api_id"] == 1234567
    with pytest.raises(ErroCredenciais):
        f.passo_codigo_app("99999")
    assert f.passo_codigo_app("22222") == "pronto"
    f.finalizar()
    assert f.arm is None


def test_fluxo_pula_o_site_quando_ja_tem_chaves(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"api_id": 1, "api_hash": "x"}))
    site = SiteFalso(tem_app=False)
    f = Fluxo(tmp_path, site=site, fabrica_arm=ArmFalso)
    assert f.passo_telefone("+5511999999999") == "codigo_app"
    assert site.chamadas == []
