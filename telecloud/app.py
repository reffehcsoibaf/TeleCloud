"""Fluxo principal do TeleCloud: login, restauração do índice, montagem da unidade, bandeja e encerramento."""
import argparse
import getpass
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

from . import sistema

log = logging.getLogger("telecloud")

LINK_WINFSP = "https://winfsp.dev/rel/"


def _argumentos(argv):
    ap = argparse.ArgumentParser(prog="TeleCloud")
    ap.add_argument("--unidade", default="T:", help="letra da unidade (padrão T:)")
    ap.add_argument("--memoria", action="store_true", help="armazenamento falso, só para testes")
    ap.add_argument("--dados", default=None, help="pasta de dados (padrão: automática)")
    ap.add_argument("--sem-bandeja", action="store_true", help="roda no console, sem ícone na bandeja")
    ap.add_argument("--entrar", action="store_true", help="refaz o login no Telegram")
    ap.add_argument("--console", action="store_true", help="login por texto no console (com --entrar)")
    ap.add_argument("--instalar", action="store_true", help="instala este programa para o usuário atual")
    ap.add_argument("--desinstalar", action="store_true", help="remove o programa instalado")
    ap.add_argument("--iniciar-com-windows", choices=["sim", "nao"], help="liga ou desliga o início automático")
    ap.add_argument("--sem-instalar", action="store_true", help="não oferecer a instalação")
    ap.add_argument("--configuracoes", action="store_true", help="abre a janela de configurações")
    return ap.parse_args(argv)


def _escrever(texto: str):
    if sys.stdout:
        print(texto, flush=True)


# ---------- login ----------
def _pedir(texto: str, secreto=False) -> str:
    return (getpass.getpass(texto) if secreto else input(texto)).strip()


def entrar(dados: Path, console=False) -> bool:
    """Login numa janela (telefone e códigos); as chaves da API vêm do my.telegram.org. Devolve True se entrou."""
    if console:
        entrar_console(dados)
        return True
    from .login import abrir_janela
    return abrir_janela(dados)


def entrar_console(dados: Path):
    """Pede, por texto no console, o que falta: chaves da API (uma vez) e o login no Telegram."""
    from .telegram import TelegramArmazenamento
    sistema.garantir_console()
    cfg_arq = dados / "config.json"
    cfg = json.loads(cfg_arq.read_text(encoding="utf-8-sig")) if cfg_arq.exists() else {}
    if not cfg.get("api_id") or not cfg.get("api_hash"):
        print("TeleCloud - primeiro uso.")
        print("Crie as chaves em https://my.telegram.org (API development tools) e digite abaixo.")
        cfg["api_id"] = int(_pedir("api_id: "))
        cfg["api_hash"] = _pedir("api_hash: ")
        dados.mkdir(parents=True, exist_ok=True)
        cfg_arq.write_text(json.dumps(cfg), encoding="utf-8")
    arm = TelegramArmazenamento(dados)
    tel = _pedir("Telefone com código do país, por exemplo +5511999999999: ")
    arm.entrar(tel, lambda: _pedir("Código recebido no Telegram: "),
               lambda: _pedir("Senha da verificação em duas etapas: ", secreto=True))
    arm.conectar()
    print("Login feito. O grupo de armazenamento é:", arm.grupo.title)
    arm.fechar()
    sistema.soltar_console()


_login_feito = False   # True quando este processo mostrou a janela de login


def _conectar(dados: Path):
    global _login_feito
    from .telegram import TelegramArmazenamento
    if not (dados / "config.json").exists():
        if not entrar(dados):
            raise RuntimeError("Login cancelado.")
        _login_feito = True
    arm = TelegramArmazenamento(dados)
    try:
        arm.conectar()
    except RuntimeError:  # sem sessão válida
        arm.fechar()
        if not entrar(dados):
            raise RuntimeError("Login cancelado.")
        _login_feito = True
        arm = TelegramArmazenamento(dados)
        arm.conectar()
    return arm


# ---------- principal ----------
def principal(argv=None):
    args = _argumentos(argv)
    if sys.stdout is None:  # programa sem console (pythonw / .exe de janela)
        sys.stdout = sys.stderr = open(os.devnull, "w")
    dados = Path(args.dados) if args.dados else sistema.pasta_dados()

    if args.configuracoes:
        from .configuracoes import abrir_janela
        abrir_janela(dados)
        return 0
    if args.desinstalar:
        return _desinstalar()
    if args.iniciar_com_windows:
        sistema.definir_inicio(args.iniciar_com_windows == "sim")
        return 0
    if sistema.empacotado() and not sistema.esta_instalado() and not args.sem_instalar and not args.memoria:
        if _oferecer_instalacao():
            return 0

    dados.mkdir(parents=True, exist_ok=True)
    import faulthandler
    faulthandler.enable(open(dados / "falha.log", "a"))   # se o processo morrer sem aviso, o motivo fica aqui
    logging.basicConfig(filename=str(dados / "telecloud.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    if args.entrar:
        entrar(dados, console=args.console)
        return 0
    if sistema.ja_em_execucao():
        if not args.sem_bandeja:
            sistema.aviso("O TeleCloud já está aberto. Procure o ícone dele na bandeja do sistema "
                          "(perto do relógio).")
        return 0

    if not sistema.winfsp_instalado() and not _garantir_winfsp():
        return 1

    from .armazenamento import ArmazenamentoMemoria
    from .indice import Indice
    from .nuvem import Nuvem

    try:
        if args.memoria:
            arm, indice = ArmazenamentoMemoria(), Indice()
        else:
            arm = _conectar(dados)
            if _login_feito and sistema.empacotado():
                # a janela de login (wx) e a bandeja não convivem bem no mesmo processo: recomeça limpo
                arm.fechar()
                _reabrir(argv)
                return 0
            caminho_indice = dados / "indice.db"
            if not caminho_indice.exists():
                copia = arm.carregar_indice()
                if copia:
                    Indice.gravar_copia(copia, str(caminho_indice))
                    log.info("índice restaurado a partir do Telegram")
            indice = Indice(str(caminho_indice))
    except Exception as e:
        log.exception("não consegui conectar")
        _falha(f"Não foi possível conectar ao Telegram:\n{e}", args)
        return 1

    from .configuracoes import cache_max_bytes, pausa_envios_s
    cache_max = cache_max_bytes(dados)

    try:
        from .unidade import Unidade
        from .winfsp import SistemaDeArquivos
        nuvem = Nuvem(indice, arm)
        un = Unidade(nuvem, dados / "cache", cache_max=cache_max)
        un.pausa_envios = pausa_envios_s(dados)
        fs = SistemaDeArquivos(un, args.unidade)
    except FileNotFoundError:
        _falha("O WinFsp não está instalado. Instale-o em " + LINK_WINFSP + " e abra o TeleCloud de novo.", args)
        return 1
    except OSError as e:
        _falha(f"Não foi possível criar a unidade {args.unidade}. Ela já está em uso?\n{e}", args)
        return 1

    def encerrar():
        _escrever("Aguardando envios pendentes...")
        un.aguardar_fila(limite=3600)
        un.salvar_indice_agora()
        fs.desmontar()
        un.parar()
        if not args.memoria:
            arm.fechar()
        _escrever("Encerrado.")

    if args.sem_bandeja:
        _escrever(f"TeleCloud montado em {args.unidade}  (Ctrl+C para encerrar)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        encerrar()
        return 0

    from .bandeja import Bandeja

    def sair():
        encerrar()
        bandeja.parar()

    def reler_configuracoes():
        un.cache_max = cache_max_bytes(dados)   # vale já, sem reiniciar
        un.pausa_envios = pausa_envios_s(dados)

    bandeja = Bandeja(un, args.unidade, dados, sair, ao_configurar=reler_configuracoes)

    evento_sair = sistema.criar_evento_sair()   # uma atualização pede por aqui que este programa feche

    def esperar_pedido():
        sistema.esperar_pedido_sair(evento_sair)
        bandeja._sair()
    threading.Thread(target=esperar_pedido, daemon=True).start()
    bandeja.executar(ao_pronto=lambda: bandeja.avisar(
        f"Unidade {args.unidade} pronta. Use o ícone perto do relógio para ver os envios."))
    return 0


def _reabrir(argv):
    import subprocess
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    subprocess.Popen([sys.executable, *(sys.argv[1:] if argv is None else argv)], env=env, close_fds=True)


def _garantir_winfsp() -> bool:
    """O WinFsp é o driver que cria a unidade. Oferece instalar o que vem dentro do .exe."""
    if sistema.instalador_winfsp() is None:
        sistema.aviso("O WinFsp não está instalado. Instale-o em " + LINK_WINFSP + " e abra o TeleCloud de novo.",
                      erro=True)
        return False
    if not sistema.perguntar(
            "O TeleCloud precisa do WinFsp, o driver que cria a unidade T:. Instalar agora?\n\n"
            "O Windows vai pedir permissão de administrador."):
        return False
    if not sistema.instalar_winfsp():
        sistema.aviso("A instalação do WinFsp não terminou. Você pode instalá-lo à mão em " + LINK_WINFSP,
                      erro=True)
        return False
    return True


def _falha(texto: str, args):
    log.error(texto)
    if args.sem_bandeja and sys.stdout:
        print(texto)
    else:
        sistema.aviso(texto, erro=True)


def _atualizar() -> bool:
    """Já existe uma cópia instalada: troca por esta, sem perguntas. Fecha a que estiver aberta (esperando os
    envios pendentes terminarem) e abre a nova. Devolve True se o assunto acabou aqui."""
    import subprocess
    import threading
    if sistema.instancia_ativa():
        if not sistema.pedir_para_sair():
            sistema.aviso("O TeleCloud instalado está aberto e é de uma versão que não fecha sozinha. "
                          "Use o ícone dele na bandeja, escolha Sair e abra este arquivo de novo.", erro=True)
            return True
        if not sistema.esperar_encerrar(15):
            threading.Thread(target=sistema.aviso, daemon=True, args=(
                "O TeleCloud está terminando os envios pendentes. A atualização continua sozinha quando "
                "eles acabarem; este aviso pode ser fechado.",)).start()
            if not sistema.esperar_encerrar(3600):
                return True
    try:
        exe = sistema.instalar(sistema.inicio_ativo())
    except Exception as e:
        sistema.aviso(f"Não consegui atualizar o TeleCloud:\n{e}", erro=True)
        return True
    subprocess.Popen([str(exe)], close_fds=True)
    return True


def _oferecer_instalacao() -> bool:
    """Este .exe também é o instalador. Devolve True se instalou (e já abriu a cópia instalada)."""
    if sistema.instalado_em_disco():
        return _atualizar()
    if not sistema.perguntar(
            "Instalar o TeleCloud neste computador?\n\n"
            "Sim: copia o programa para o seu perfil, cria um atalho no menu Iniciar e aparece em "
            "Configurações > Aplicativos para desinstalar.\n"
            "Não: abre o TeleCloud sem instalar."):
        return False
    inicio = sistema.perguntar("Abrir o TeleCloud automaticamente quando o Windows iniciar?")
    exe = sistema.instalar(inicio)
    import subprocess
    subprocess.Popen([str(exe)], close_fds=True)
    return True


def _desinstalar() -> int:
    if sistema.ja_em_execucao():
        sistema.aviso("O TeleCloud está aberto. Use o ícone dele na bandeja, escolha Sair e "
                      "execute a desinstalação de novo.", erro=True)
        return 1
    if not sistema.perguntar("Remover o TeleCloud deste computador?"):
        return 0
    dados = sistema.perguntar(
        "Apagar também os dados locais (login, índice e arquivos em cache)?\n\n"
        "Os arquivos guardados no Telegram NÃO são apagados. O índice fica salvo no grupo TeleCloud e "
        "permite recuperar tudo depois.")
    sistema.desinstalar(dados)
    sistema.aviso("TeleCloud removido. O driver WinFsp continua instalado (outros programas podem usá-lo); "
                  "remova-o em Configurações > Aplicativos se quiser.")
    return 0
