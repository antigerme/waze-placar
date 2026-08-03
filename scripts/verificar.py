#!/usr/bin/env python3
"""Falha quando a documentação descola do código.

Cada checagem aqui existe porque a coisa correspondente já desatualizou sem
ninguém notar. Não faz requisição nenhuma: roda em menos de um segundo e serve
de hook.

    python3 scripts/verificar.py
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SCRIPTS = RAIZ / "scripts"
falhas = []


def erro(check, msg):
    falhas.append((check, msg))


# --------------------------------------------------------------- 1. compila
for f in sorted(SCRIPTS.glob("*.py")):
    try:
        ast.parse(f.read_text(encoding="utf-8"))
    except SyntaxError as e:
        erro("compila", "{}: {}".format(f.name, e))


# ------------------------------------------------- 2. flags do CLI no README
# O README já prometeu --print, --period e --json muito depois de deixarem de
# existir. Aqui as duas direções são conferidas.
readme = (RAIZ / "README.md").read_text(encoding="utf-8")

def flags_de(script):
    out = subprocess.run([sys.executable, str(SCRIPTS / script), "--help"],
                         capture_output=True, text=True, timeout=30).stdout
    return set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", out)) - {"--help"}

reais = set()
for script in ("placar.py", "perfis.py"):
    try:
        reais |= flags_de(script)
    except Exception as e:                                   # noqa: BLE001
        erro("cli", "não consegui rodar {} --help: {}".format(script, e))

citadas = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", readme))
for f in sorted(citadas - reais):
    erro("cli", "README cita {}, que não existe mais".format(f))


# ------------------------------------------ 3. endpoints documentados na API
recon = (RAIZ / "docs" / "api-recon.md").read_text(encoding="utf-8")
waze_src = (SCRIPTS / "waze.py").read_text(encoding="utf-8")
for nome, url in re.findall(r'^([A-Z_]+) = "(https://[^"]+)"', waze_src, re.M):
    caminho = url.split("waze.com/", 1)[-1]
    # o documento cita o caminho, não a URL inteira
    trecho = caminho.split("/")[-1]
    if trecho and trecho not in recon:
        erro("endpoints", "{} ({}) não aparece em docs/api-recon.md"
             .format(nome, trecho))


# ------------------------------------- 4. nada de número literal na prosa
pagina = (SCRIPTS / "pagina.py").read_text(encoding="utf-8")
tpl = pagina[pagina.find('PAGE = r"""'):]
for m in re.finditer(r"<(p|h2)[^>]*>(.*?)</\1>", tpl, re.S):
    txt = re.sub(r"\s+", " ", m.group(2)).strip()
    # ignora índice de slice e aritmética de porcentagem, que não são prosa
    limpo = re.sub(r"\.slice\([^)]*\)", "", txt)
    limpo = re.sub(r"Math\.round\([^)]*\)", "·", limpo)
    achados = re.findall(r'(?<![\w$.{#"\-/])\b(\d{2,})\b', limpo)
    if achados:
        erro("prosa", "número literal {} em: {}".format(
            achados, re.sub(r"<[^>]+>", "", limpo)[:70]))


# --------------------------------------- 5. lista de painéis no README
# O README anunciava "quinze painéis" e nomeava treze, com nomes de duas
# versões atrás. A lista fica entre marcadores para poder ser conferida.
pag_txt = (SCRIPTS / "pagina.py").read_text(encoding="utf-8")
# o painel de aviso da coleta sem perfis não é um dos painéis do placar
gerados = [t for linha, t in re.findall(r"(.*)<h2>([^<]+)</h2>", pag_txt)
           if "aviso" not in linha]
bloco = re.search(r"<!-- paineis:inicio -->(.*?)<!-- paineis:fim -->",
                  readme, re.S)
if not bloco:
    erro("paineis", "README perdeu os marcadores <!-- paineis:inicio/fim -->")
else:
    listados = re.findall(r"^- (.+?)\s*$", bloco.group(1), re.M)
    for nome in sorted(set(gerados) - set(listados)):
        erro("paineis", "o pagina.py gera '{}', que o README não lista".format(nome))
    for nome in sorted(set(listados) - set(gerados)):
        erro("paineis", "o README lista '{}', que o pagina.py não gera".format(nome))
    if len(gerados) != len(listados) and set(gerados) == set(listados):
        erro("paineis", "a lista do README tem {} itens e o pagina.py gera {}"
             .format(len(listados), len(gerados)))


# ------------------------------- 6. limiares do pagina.py citados no decisoes
# Não exige que todos estejam lá; exige que o documento exista e tenha a tabela
# de ordens de grandeza, que é o canário de regressão.
dec = RAIZ / "docs" / "decisoes.md"
if not dec.exists():
    erro("docs", "docs/decisoes.md sumiu")
else:
    d = dec.read_text(encoding="utf-8")
    for secao in ("Erros que este projeto já cometeu",
                  "Caminhos testados e descartados",
                  "Ordens de grandeza"):
        if secao not in d:
            erro("docs", "docs/decisoes.md perdeu a seção '{}'".format(secao))


# ------------------------------------------------------------------ relatório
if falhas:
    print("verificação falhou:\n")
    atual = None
    for check, msg in falhas:
        if check != atual:
            print("  [{}]".format(check))
            atual = check
        print("    {}".format(msg))
    print("\n{} problema(s). A documentação descolou do código.".format(len(falhas)))
    sys.exit(1)

print("verificação ok — código, README e docs conferem")
