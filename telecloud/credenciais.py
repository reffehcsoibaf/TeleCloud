"""Obtém o api_id e o api_hash da própria conta em my.telegram.org, sem o usuário abrir o site.

Fluxo (o mesmo que o site faz no navegador):
  1. enviar_codigo(telefone): o Telegram manda um código ao app da conta.
  2. entrar(codigo): valida o código e abre a sessão no site.
  3. obter_ou_criar(): lê as chaves do aplicativo já cadastrado ou cadastra "TeleCloud".
"""
import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request

SITE = "https://my.telegram.org"
TITULO = "TeleCloud"
NOME_CURTO = "telecloud"


class ErroCredenciais(Exception):
    """Mensagem já pronta para mostrar ao usuário."""


def extrair_chaves(html: str):
    """(api_id, api_hash) de /apps quando já existe aplicativo; senão None."""
    m_id = re.search(r"api_id:</label>.*?<strong>\s*(\d+)\s*</strong>", html, re.S)
    m_hash = re.search(r"api_hash:</label>.*?<span[^>]*>\s*([0-9a-fA-F]{32})\s*</span>", html, re.S)
    if m_id and m_hash:
        return int(m_id.group(1)), m_hash.group(1).lower()
    return None


def extrair_token_de_criacao(html: str):
    m = re.search(r'name="hash"\s+value="([^"]+)"', html) or re.search(r'value="([^"]+)"\s+name="hash"', html)
    return m.group(1) if m else None


class MyTelegram:
    def __init__(self):
        self._cookies = http.cookiejar.CookieJar()
        self._abridor = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._cookies))
        self._telefone = None
        self._random_hash = None

    def _requisitar(self, caminho: str, dados: dict = None) -> str:
        corpo = urllib.parse.urlencode(dados).encode() if dados is not None else None
        req = urllib.request.Request(SITE + caminho, data=corpo, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": SITE,
            "Referer": SITE + "/auth",
        })
        try:
            with self._abridor.open(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            texto = e.read().decode("utf-8", "replace")[:200]
            raise ErroCredenciais(f"O site do Telegram recusou o pedido ({e.code}). {texto}") from e
        except (urllib.error.URLError, OSError) as e:
            raise ErroCredenciais(f"Não consegui falar com o site do Telegram: {e}") from e

    def enviar_codigo(self, telefone: str):
        resposta = self._requisitar("/auth/send_password", {"phone": telefone})
        try:
            self._random_hash = json.loads(resposta)["random_hash"]
        except (ValueError, KeyError, TypeError):
            if "too many" in resposta.lower():
                raise ErroCredenciais("O Telegram bloqueou novos códigos por um tempo. Tente de novo mais tarde.")
            raise ErroCredenciais("O Telegram não aceitou esse telefone. Use o formato +5511999999999.")
        self._telefone = telefone

    def entrar(self, codigo: str):
        if not self._random_hash:
            raise ErroCredenciais("Peça o código antes.")
        resposta = self._requisitar("/auth/login", {
            "phone": self._telefone, "random_hash": self._random_hash, "password": codigo})
        if resposta.strip().lower() != "true":
            if "too many" in resposta.lower():
                raise ErroCredenciais("Muitas tentativas. Espere um pouco e comece de novo.")
            raise ErroCredenciais("Código incorreto.")

    def obter_ou_criar(self):
        html = self._requisitar("/apps")
        chaves = extrair_chaves(html)
        if chaves:
            return chaves
        token = extrair_token_de_criacao(html)
        if not token:
            raise ErroCredenciais("Não encontrei como cadastrar o aplicativo no site. "
                                  "Crie as chaves à mão em my.telegram.org.")
        resposta = self._requisitar("/apps/create", {
            "hash": token, "app_title": TITULO, "app_shortname": NOME_CURTO,
            "app_url": "", "app_platform": "desktop", "app_desc": "Unidade de disco com armazenamento no Telegram"})
        if resposta.strip() and "error" in resposta.lower()[:200]:
            raise ErroCredenciais("O Telegram não deixou cadastrar o aplicativo: " + resposta.strip()[:150])
        chaves = extrair_chaves(self._requisitar("/apps"))
        if not chaves:
            raise ErroCredenciais("O aplicativo foi cadastrado, mas não consegui ler as chaves.")
        return chaves
