# TeleCloud: arquitetura

Unidade virtual no Windows (WinFsp) cujo conteúdo fica no Telegram.

## Decisões
- Python 3.13, Telethon (MTProto, conta de usuário): 2 GB por arquivo (4 GB com Premium).
- Drive virtual: WinFsp. Falta instalar o driver e ligar `Nuvem` ao WinFsp.
- Repositório próprio: C:\github\TeleCloud.

## Camadas
- `indice.py`: SQLite com a árvore (pastas, arquivos, partes, tags). Subpastas só existem aqui, porque tópicos do Telegram não aninham.
- `armazenamento.py`: interface `Armazenamento`. A implementação em memória serve para testes; a do Telegram ainda falta.
- `nuvem.py`: operações de alto nível (listar, criar pasta, gravar, ler por faixa, mover, apagar, tags), com divisão em partes de 1900 MB e cifra AES-256-GCM opcional.

## Mapeamento no Telegram
- Supergrupo com tópicos ativados. Pasta de primeiro nível = tópico.
- Arquivo = uma ou mais mensagens com documento. A legenda leva as tags como hashtags.
- Renomear e mover mexem só no índice, sem reenviar.
- O índice é salvo no próprio Telegram (arquivo fixado) para recuperar num PC novo.

## Camadas adicionais
- `unidade.py`: callbacks do WinFsp, cache local, fila de envio em segundo plano (com espera crescente nas falhas), exclusões remotas persistidas, limpeza do cache por último uso e guarda do índice após silêncio.
- `sistema.py`: instância única, iniciar com o Windows, instalar/desinstalar pelo próprio .exe, console para o login.
- `bandeja.py`: ícone e menu nativo; `app.py`: fluxo principal; `construir.py`: gera o .exe.

## Pendências
- Chave de cifra gerenciada pelo usuário (hoje opcional e fora da interface).
- Mover entre tópicos de verdade (hoje só o índice muda).
- Pré-leitura da próxima parte para streaming mais fluido.

## Riscos
- Limites de taxa e banimento por volume: controlar a velocidade de envio.
- O uso como armazenamento em massa fica numa zona cinzenta dos termos do Telegram.
