# TeleCloud para Android

App nativo (Kotlin + Jetpack Compose + TDLib) que usa o **mesmo grupo e o mesmo índice** do TeleCloud do Windows:
o que um lado grava aparece no outro. Feito para uso com TalkBack.

## O que faz
- Login no Telegram (telefone, código, senha em duas etapas), um passo por tela.
- Lista pastas e arquivos do índice, baixa e envia arquivos (partes de 64 MB, igual ao Windows) e recebe
  arquivos pelo "Compartilhar" de outros apps.
- Sincroniza com o PC: o celular confere o grupo a cada 30 s; o PC incorpora o índice do celular
  (`Indice.mesclar`, comparando por caminho).

## Como compilar
1. **TDLib**: não está no repositório. Rode o fluxo de trabalho "TDLib para Android" (aba Actions) e baixe o
   artefato `tdlib-android` para `android\tdlib-baixado` (deve ficar `java\` e `libs\` dentro dela):
   `gh run download <id> -n tdlib-android -D android\tdlib-baixado`.
2. **Chaves do Telegram**: a compilação lê `api_id` e `api_hash` de `..\dados\config.json` (o mesmo arquivo do
   TeleCloud do Windows, fora do git) e as embute no APK. **Não compartilhe o APK gerado.** Sem o arquivo, o app
   pede as chaves na primeira abertura.
3. `set JAVA_HOME=C:\android\jdk17` e `gradlew.bat :app:assembleDebug`. Instalar: `adb install -r` ou
   `ferramentas\copiar_apk_para_celular.bat`.

## Erros
O app grava `files/telecloud.log` (build debug): `adb shell run-as br.com.fabioscheffer.telecloud cat files/telecloud.log`.

## Detalhes que custaram caro
- Id de mensagem da TDLib em grupo = id do servidor deslocado 20 bits (o índice guarda o id do servidor).
- A busca por texto do Telegram demora minutos para enxergar mensagem nova; o índice é procurado também pela lista
  de documentos do tópico geral, que enxerga na hora.
