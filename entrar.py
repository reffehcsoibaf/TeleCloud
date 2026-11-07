"""Login único no Telegram e criação do grupo de armazenamento. Rode: python entrar.py"""
import getpass
from pathlib import Path

from telecloud.telegram import TelegramArmazenamento

a = TelegramArmazenamento(Path(__file__).parent / "dados")
tel = input("Telefone com +55...: ").strip()
a.entrar(tel, lambda: input("Código recebido no Telegram: ").strip(),
         lambda: getpass.getpass("Senha da verificação em duas etapas: "))
a.conectar()
print("Pronto. Grupo:", a.grupo.title, a.grupo.id)

# Teste de ida e volta
ref = a.enviar("Teste", "ola.txt", b"ola telecloud", "#teste")
assert a.baixar(ref) == b"ola telecloud"
a.apagar([ref])
print("Envio, download e exclusão funcionaram.")
a.fechar()
