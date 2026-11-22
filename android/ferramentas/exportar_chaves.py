"""Extrai só api_id e api_hash do config.json do TeleCloud e grava no arquivo de destino.

Uso: python -I exportar_chaves.py <config.json de origem> <arquivo de destino>
Não imprime as chaves (a saída vai para o log).
"""
import json
import sys

origem, destino = sys.argv[1], sys.argv[2]
cfg = json.load(open(origem, encoding="utf-8-sig"))
api_id, api_hash = cfg.get("api_id"), cfg.get("api_hash")
if not api_id or not api_hash:
    sys.exit("ERRO: o arquivo não tem api_id e api_hash. Entre uma vez no TeleCloud do Windows.")
with open(destino, "w", encoding="utf-8", newline="\n") as f:
    json.dump({"api_id": int(api_id), "api_hash": str(api_hash)}, f)
print("Chaves lidas de", origem)
