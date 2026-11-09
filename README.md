# TeleCloud

Unidade virtual do Windows (WinFsp) cujo conteúdo fica guardado no Telegram. No dia a dia é uma pasta comum do Explorer. Detalhes técnicos em `docs/arquitetura.md`.

## Usar
1. O driver WinFsp (https://winfsp.dev) vem dentro do `.exe`: se faltar, o TeleCloud oferece instalá-lo (o Windows pede permissão de administrador). Para gerar o `.exe`, baixe antes o instalador: `gh release download v2.1 -R winfsp/winfsp -p "*.msi" -D build`.
2. Rode `dist\TeleCloud.exe` (veja "Gerar o programa") ou, a partir do código, `abrir.cmd`.
3. No primeiro uso aparece uma janela: explica como criar as chaves da API (botão que abre my.telegram.org), pede para colá-las e depois pede o telefone e o código. Os campos são nativos, lidos pelo NVDA.
4. A unidade **T:** aparece. O ícone perto do relógio mostra os envios; Enter nele abre a unidade.

O `.exe` também é o instalador: ao abrir fora da pasta de instalação ele pergunta se deve instalar (copia para `%LOCALAPPDATA%\Programs\TeleCloud`, cria atalho no menu Iniciar, entra em Configurações > Aplicativos e, se você quiser, inicia com o Windows). A desinstalação remove tudo isso e pergunta se apaga também os dados locais. O WinFsp não é removido.

## Menu do ícone da bandeja
Menu nativo (teclado e leitor de tela): estado dos envios, fila de envios, espaço usado no disco, quando o índice foi guardado, guardar o índice agora, Configurações (janela com o limite do cache e o início com o Windows), iniciar com o Windows, abrir a pasta de dados/registro e Sair (espera os envios pendentes terminarem).

## Comportamento
- Gravar é rápido: o arquivo vai para o cache em `dados\cache` e sobe ao Telegram em segundo plano. Se o programa fechar no meio, retoma no próximo início.
- Arquivos são divididos em partes de 64 MB; só a parte lida é baixada.
- O cache em disco tem limite (padrão 5 GB; mude em Configurações no menu da bandeja, ou `cache_max_mb` em `config.json`). Passando disso, saem primeiro os arquivos usados há mais tempo que já estão no Telegram.
- O índice (árvore de pastas, partes, tags) é guardado no grupo do Telegram depois de alguns segundos sem alterações e ao sair. Num computador novo, basta entrar com a mesma conta: o grupo e o índice são recuperados sozinhos.
- Exclusões pendentes no Telegram ficam registradas no índice e são concluídas mesmo depois de reiniciar.
- Falhas de rede: nova tentativa com espera crescente (até 5 min); o ícone avisa.

## Gerar o programa
`venv\Scripts\python construir.py` cria `dist\TeleCloud.exe` (arquivo único).

## Testes
`venv\Scripts\python -m pytest testes`

## Limites conhecidos
- Mover/renomear só muda o índice: a mensagem continua no tópico antigo.
- Se o índice ainda não foi guardado e o computador for perdido, as partes ficam no grupo mas sem a árvore.
- O índice e os arquivos não são cifrados por padrão (a cifra AES-256-GCM existe em `nuvem.py`, falta a gestão de senha).
- O uso como armazenamento em massa fica numa zona cinzenta dos termos do Telegram.
