"""Abre o TeleCloud (unidade T: + ícone na bandeja).
Uso: python montar.py [--unidade T:] [--sem-bandeja] [--memoria] [--entrar] ...  (veja --help)"""
import sys

from telecloud.app import principal

if __name__ == "__main__":
    sys.exit(principal())
