"""Monta a unidade do TeleCloud. Uso: python montar.py [--unidade T:] [--memoria]
--memoria usa um armazenamento falso (nada vai ao Telegram), só para testar a unidade."""
import argparse
import logging
import sys
import time
from pathlib import Path

from telecloud.armazenamento import ArmazenamentoMemoria
from telecloud.indice import Indice
from telecloud.nuvem import Nuvem
from telecloud.unidade import Unidade
from telecloud.winfsp import SistemaDeArquivos

ap = argparse.ArgumentParser()
ap.add_argument("--unidade", default="T:")
ap.add_argument("--memoria", action="store_true")
ap.add_argument("--dados", default=str(Path(__file__).parent / "dados"))
args = ap.parse_args()

dados = Path(args.dados)
dados.mkdir(exist_ok=True)
logging.basicConfig(filename=str(dados / "telecloud.log"), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")

if args.memoria:
    arm, indice = ArmazenamentoMemoria(), Indice()
else:
    from telecloud.telegram import TelegramArmazenamento
    arm = TelegramArmazenamento(dados)
    arm.conectar()
    indice = Indice(str(dados / "indice.db"))

nuvem = Nuvem(indice, arm)
un = Unidade(nuvem, dados / "cache")
fs = SistemaDeArquivos(un, args.unidade)
print(f"TeleCloud montado em {args.unidade}  (Ctrl+C para encerrar)", flush=True)
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
print("Aguardando envios pendentes...", flush=True)
un.aguardar_fila()
fs.desmontar()
un.parar()
if not args.memoria:
    arm.fechar()
print("Encerrado.")
