# Changelog

O que mudou em cada versão do TeleCloud (Windows e Android). A versão é ano.mês.dia.N e vale para os dois.
Versões anteriores a este arquivo estão na lista de versões do GitHub.

Para lançar: descreva o que mudou em "Não lançado" e rode `ferramentas\lancar.cmd` (ver docs/lancamento.md).

## Não lançado

## 2026.11.22.1 — 2026-11-22

### Windows
- Corrigido: o cache em disco passava do limite e o botão "Limpar o cache do disco" não apagava nada. As cópias
  mantidas de sessões anteriores nunca eram consideradas na limpeza; agora são (as mais antigas primeiro), e as de
  arquivos que já não existem são apagadas.
- Painel de controle: mostra o espaço usado pelo cache (com aviso se passou do limite), a fila de envios e a hora do
  índice, atualizados sozinhos. Ganhou os botões que estavam no menu da bandeja: guardar o índice, buscar novidades do
  celular, exportar as chaves, abrir a pasta de dados e a opção de iniciar com o Windows.
- Menu da bandeja simplificado: só Abrir a unidade, Abrir o painel de controle e Sair.

## 2026.11.22.0 — 2026-11-22

### Android (primeira versão)
- Aplicativo Android com a mesma conta, o mesmo grupo e o mesmo índice do Windows: lista as pastas e os arquivos,
  baixa para a pasta Download, envia (inclusive pelo "Compartilhar" de outros aplicativos, como o WhatsApp), cria
  pastas, renomeia e apaga.
- O TeleCloud aparece também no aplicativo Arquivos do Android (gerenciador de arquivos do Google).
- Transferências em segundo plano, com notificação.
- Login pelo telefone; as chaves da API entram por arquivo (`telecloud-config.json`), sem digitá-las.

### Windows
- O índice agora tem linhagem: o que foi apagado ou renomeado no celular vale no PC, e vice-versa, em poucos
  segundos. O PC publica o índice 5 s depois da última mudança.
- Menu da bandeja: "Exportar as chaves para o celular..." e "Buscar novidades do celular no Telegram".

### Site
- Página em `telecloud.fabioscheffer.workers.dev`, com links fixos para o Windows e o Android.
