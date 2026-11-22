# Como lançar uma versão do TeleCloud

Uma versão leva o Windows e o Android juntos, com o mesmo número `ano.mês.dia.N` (ex.: `2026.11.22.0`).
Os arquivos ficam como anexos da versão no GitHub; a página do TeleCloud acha sempre a mais nova.

## Peças

| Peça | Onde |
|---|---|
| Versão do Windows | `VERSAO` em `telecloud/sistema.py` |
| Versão do Android | `versionName` e `versionCode` em `android/app/build.gradle.kts` |
| Histórico | `CHANGELOG.md` (seção `## Não lançado`) |
| Script | `ferramentas/lancar.py`, chamado por `ferramentas/lancar.cmd` |
| Chave de assinatura do APK | `C:\android\keys\telecloud.jks` + `telecloud.properties` (fora do git) |
| Site e links fixos | `wrangler.jsonc`, `worker/`, `site/` (Worker `telecloud` na Cloudflare) |

## Passo a passo

1. Deixe o trabalho commitado no `main` (o script recusa mudanças soltas).
2. Descreva o que mudou em `## Não lançado` no `CHANGELOG.md` e faça o commit. Vazio = o script não lança.
3. Rode `ferramentas\lancar.cmd` (ensaio) ou `ferramentas\lancar.cmd --publicar` (lança de verdade). A saída vai para
   `C:\logs\telecloud_lancar.txt`.

O que o script faz, nesta ordem: confere a árvore limpa e o ramo `main`; vê a data de hoje e as tags já publicadas
(`.0` se nada saiu hoje, senão sobe o dígito); atualiza `VERSAO`, `versionName`/`versionCode` e o título da seção do
CHANGELOG juntos; roda os testes do Windows e do Android; gera `dist\TeleCloud.exe` e `dist\TeleCloud.apk`; confere
que o APK está assinado com a chave do TeleCloud; e, só com `--publicar`, faz o commit `Versão X`, a tag `vX`, o push
e `gh release create` com os dois arquivos e os SHA-256 nas notas.

Sem `--publicar` nada vai para o GitHub. As mudanças de versão ficam sem commit; `git checkout .` desfaz.

## A chave do APK

`telecloud.jks` é a identidade do aplicativo: o Android só aceita uma atualização assinada com a mesma chave. Se ela
for perdida, ninguém consegue atualizar o app sem desinstalar. **Guarde uma cópia de `telecloud.jks` e de
`telecloud.properties` fora do computador.** Nunca vão para o git.

O APK que você instala pelo `adb` durante o desenvolvimento (`assembleDebug`) é assinado com outra chave (a de teste
do Android). Ele não pode ser atualizado por cima pelo APK de lançamento, nem o contrário: trocar de um para o outro
exige desinstalar uma vez.

## Links fixos da página

- `/baixar/windows` e `/baixar/android` levam ao `TeleCloud.exe` e ao `TeleCloud.apk` da versão mais nova que tiver
  o arquivo (sem versão publicada, levam à lista de versões).
- `/versao.json` informa versão e tamanho para a página.
- A escolha da versão mais nova está em `worker/versoes.js`; o teste é `testes/versoes_teste.html`
  (`msedge --headless=new --allow-file-access-from-files --dump-dom file:///.../testes/versoes_teste.html`).
