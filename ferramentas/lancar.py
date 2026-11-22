"""Lança uma versão do TeleCloud (Windows + Android) no GitHub.

Uso (na raiz do repositório):   venv\\Scripts\\python -I ferramentas\\lancar.py [--publicar]

Sem --publicar, faz tudo menos publicar: calcula a versão, atualiza os arquivos, roda os testes e gera o
TeleCloud.exe e o TeleCloud.apk assinado em dist\\. Deixa as mudanças sem commit para você revisar; para desfazer:
git checkout . Com --publicar, também faz o commit, a tag, o push e cria a versão no GitHub com os dois arquivos.
A página (telecloud.fabioscheffer.workers.dev) acha sozinha os arquivos da versão nova.

Versão = ano.mês.dia.N (o mesmo número para o PC e o Android). N sobe se já houver versão publicada no dia.
Notas = o que estiver em "## Não lançado" no CHANGELOG.md; elas viram o título da seção da versão.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SISTEMA = RAIZ / "telecloud" / "sistema.py"
GRADLE = RAIZ / "android" / "app" / "build.gradle.kts"
CHANGELOG = RAIZ / "CHANGELOG.md"
DIST = RAIZ / "dist"
APK_SAIDA = RAIZ / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
NAO_LANCADO = "## Não lançado"
IMPRESSAO_ESPERADA = "93af369840896325f0aa4df6b300756689f420780151c63d721a9e7c8f1effd7"  # chave telecloud.jks


class ErroLancamento(Exception):
    """Mensagem já pronta para mostrar."""


# ---------- partes puras (testadas em testes/test_lancar.py) ----------
def proxima_versao(hoje: date, tags: list[str]) -> str:
    """ano.mês.dia.N do dia: .0 se nada saiu hoje; senão, o dígito seguinte ao maior já publicado."""
    prefixo = f"{hoje.year}.{hoje.month}.{hoje.day}"
    usados = []
    for t in tags:
        m = re.fullmatch(rf"v?{re.escape(prefixo)}(?:\.(\d+))?", t.strip())
        if m:
            usados.append(int(m.group(1) or 0))
    return f"{prefixo}.{max(usados) + 1 if usados else 0}"


def codigo_da_versao(versao: str) -> int:
    """versionCode do Android, sempre crescente com a data: 2026.11.22.3 -> 26112203."""
    a, m, d, n = (int(x) for x in versao.split("."))
    if not (0 <= n <= 99):
        raise ErroLancamento("O dígito final da versão passou de 99 no mesmo dia.")
    return (a - 2000) * 1_000_000 + m * 10_000 + d * 100 + n


def trocar_versao_python(texto: str, versao: str) -> str:
    novo, n = re.subn(r'^VERSAO = ".*"$', f'VERSAO = "{versao}"', texto, count=1, flags=re.M)
    if n != 1:
        raise ErroLancamento("Não achei a linha VERSAO = ... em telecloud/sistema.py.")
    return novo


def trocar_versao_gradle(texto: str, versao: str) -> str:
    novo, n1 = re.subn(r"versionCode = \d+", f"versionCode = {codigo_da_versao(versao)}", texto, count=1)
    novo, n2 = re.subn(r'versionName = ".*"', f'versionName = "{versao}"', novo, count=1)
    if n1 != 1 or n2 != 1:
        raise ErroLancamento("Não achei versionCode/versionName em android/app/build.gradle.kts.")
    return novo


def fechar_changelog(texto: str, versao: str, dia: date) -> tuple[str, str]:
    """Move o que está em 'Não lançado' para uma seção da versão. Devolve (novo texto, notas da versão)."""
    texto = texto.replace("\r\n", "\n")
    i = texto.find(NAO_LANCADO)
    if i < 0:
        raise ErroLancamento(f"O CHANGELOG.md não tem a seção '{NAO_LANCADO}'.")
    comeco = i + len(NAO_LANCADO)
    prox = texto.find("\n## ", comeco)
    fim = prox + 1 if prox >= 0 else len(texto)
    corpo = texto[comeco:fim].strip()
    if not corpo:
        raise ErroLancamento("A seção 'Não lançado' do CHANGELOG.md está vazia: descreva o que mudou antes de lançar.")
    novo = (texto[:i] + NAO_LANCADO + "\n\n" + f"## {versao} — {dia.isoformat()}\n\n{corpo}\n\n" + texto[fim:]).rstrip() + "\n"
    return novo, corpo


# ---------- execução ----------
def rodar(cmd, **kw):
    print("$", " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], cwd=kw.pop("cwd", RAIZ), text=True, **kw)
    if r.returncode != 0:
        raise ErroLancamento(f"Falhou (código {r.returncode}): {' '.join(str(c) for c in cmd)}")
    return r


def saida(cmd) -> str:
    r = subprocess.run([str(c) for c in cmd], cwd=RAIZ, capture_output=True, text=True)
    if r.returncode != 0:
        raise ErroLancamento(f"Falhou: {' '.join(str(c) for c in cmd)}\n{r.stderr.strip()}")
    return r.stdout


def sha256(arq: Path) -> str:
    h = hashlib.sha256()
    with open(arq, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def principal() -> int:
    ap = argparse.ArgumentParser(description="Lança o TeleCloud (Windows e Android).")
    ap.add_argument("--publicar", action="store_true", help="commit, tag, push e versão no GitHub")
    args = ap.parse_args()
    py = sys.executable
    os.environ.setdefault("JAVA_HOME", r"C:\android\jdk17")
    os.environ.setdefault("ANDROID_HOME", r"C:\android\sdk")
    gradlew = RAIZ / "android" / "gradlew.bat"

    # 1. a árvore precisa estar limpa e no main, para o lançamento ser exatamente o que está no git
    if saida(["git", "status", "--porcelain"]).strip():
        raise ErroLancamento("Há mudanças sem commit. Faça o commit (ou descarte) antes de lançar.")
    if saida(["git", "branch", "--show-current"]).strip() != "main":
        raise ErroLancamento("Lance a partir do ramo main.")
    rodar(["git", "fetch", "origin", "--tags", "--quiet"])
    if saida(["git", "rev-list", "--count", "HEAD..origin/main"]).strip() != "0":
        raise ErroLancamento("O main do GitHub tem commits que você não tem. Faça git pull antes.")
    if args.publicar and saida(["git", "rev-list", "--count", "origin/main..HEAD"]).strip() != "0":
        print("Aviso: há commits locais ainda não enviados; eles irão junto com a versão.")

    # 2. versão do dia (a data de hoje e as tags que já existem no GitHub)
    hoje = date.today()
    tags = [l.split("refs/tags/")[-1] for l in saida(["git", "ls-remote", "--tags", "origin"]).splitlines()]
    versao = proxima_versao(hoje, tags)
    print(f"Hoje é {hoje.isoformat()}. Versão a lançar: {versao} (tag v{versao}).")

    # 3. arquivos de versão e CHANGELOG (juntos)
    novo_cl, notas = fechar_changelog(CHANGELOG.read_text(encoding="utf-8"), versao, hoje)
    SISTEMA.write_text(trocar_versao_python(SISTEMA.read_text(encoding="utf-8"), versao), encoding="utf-8", newline="")
    GRADLE.write_text(trocar_versao_gradle(GRADLE.read_text(encoding="utf-8"), versao), encoding="utf-8", newline="")
    CHANGELOG.write_text(novo_cl, encoding="utf-8", newline="")

    # 4. testes e geração dos arquivos
    rodar([py, "-m", "pytest", "testes", "-q"])
    rodar([gradlew, ":app:testDebugUnitTest", ":app:assembleRelease", "--console=plain"], cwd=RAIZ / "android")
    rodar([py, "construir.py"])
    apk = DIST / "TeleCloud.apk"
    DIST.mkdir(exist_ok=True)
    shutil.copyfile(APK_SAIDA, apk)
    exe = DIST / "TeleCloud.exe"
    if not exe.exists():
        raise ErroLancamento("Não achei dist\\TeleCloud.exe depois de gerar.")

    # 5. o APK precisa estar assinado com a chave do TeleCloud
    apksigner = sorted(Path("C:/android/sdk/build-tools").glob("*/apksigner.bat"))[-1]
    cert = saida(["cmd", "/c", str(apksigner), "verify", "--print-certs", str(apk)])
    m = re.search(r"Signer #1 certificate SHA-256 digest: ([0-9a-f]+)", cert)
    if not m or m.group(1) != IMPRESSAO_ESPERADA:
        raise ErroLancamento("O APK não está assinado com a chave do TeleCloud (C:\\android\\keys\\telecloud.properties).")

    notas_completas = (
        f"{notas}\n\n### Arquivos\n"
        f"- `TeleCloud.exe` (Windows 10 ou 11), SHA-256 `{sha256(exe)}`\n"
        f"- `TeleCloud.apk` (Android 8 ou mais novo), SHA-256 `{sha256(apk)}`\n"
    )
    print(f"\nPronto: {exe} ({exe.stat().st_size // 1048576} MB) e {apk} ({apk.stat().st_size // 1048576} MB).")
    if not args.publicar:
        print("Sem --publicar: nada foi enviado. As mudanças de versão estão sem commit; para desfazer: git checkout .")
        return 0

    # 6. publicar
    rodar(["git", "add", "telecloud/sistema.py", "android/app/build.gradle.kts", "CHANGELOG.md"])
    rodar(["git", "commit", "-m", f"Versão {versao}\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"])
    rodar(["git", "tag", f"v{versao}"])
    rodar(["git", "push", "origin", "main", f"v{versao}"])
    rodar(["gh", "release", "create", f"v{versao}", str(exe), str(apk), "--title", f"TeleCloud {versao}", "--notes", notas_completas])
    print(f"\nVersão {versao} publicada: https://github.com/reffehcsoibaf/TeleCloud/releases/tag/v{versao}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(principal())
    except ErroLancamento as e:
        print(f"\nERRO: {e}", file=sys.stderr)
        sys.exit(1)
