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
# Por muito tempo esta checagem só olhava dentro de <p> e <h2>, e a maior parte
# do texto da página não está lá: está nas dicas de hover, nos rótulos de aba e
# nos title= das colunas. Passavam "últimos 90 dias" e "45 anteriores" escritos
# à mão, que ficariam falsos no dia em que a constante mudasse. Agora as três
# origens são conferidas juntas.
pagina = (SCRIPTS / "pagina.py").read_text(encoding="utf-8")
tpl = pagina[pagina.find('PAGE = r"""'):]
# o <style> tem número por todo lado e não é texto para ninguém ler
sem_css = re.sub(r"<style>.*?</style>", "", tpl, flags=re.S)


def _sem_interp(s):
    """Troca cada ${...} por '·', casando chaves.

    Precisa contar chaves em vez de usar regex: as interpolações aninham
    template literal e aspas, e um regex ingênuo corta no meio e inventa
    número onde não há.
    """
    out, i = [], 0
    while i < len(s):
        if s.startswith("${", i):
            nivel, j = 1, i + 2
            while j < len(s) and nivel:
                if s[j] == "{":
                    nivel += 1
                elif s[j] == "}":
                    nivel -= 1
                j += 1
            out.append("·")
            i = j
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


limpo_tpl = _sem_interp(sem_css)


def _numeros(txt):
    """Números escritos à mão num pedaço de texto da página.

    As aspas ficaram fora do lookbehind de propósito: com elas, um rótulo
    inteiro como "90 dias" passava batido, porque o número encostava na aspa
    de abertura. Era assim que os rótulos das abas escapavam.
    """
    return re.findall(r'(?<![\w$.{#\-/])\b(\d{2,})\b', txt)


alvos = []
for m in re.finditer(r"<(p|h2|th|td)[^>]*>(.*?)</\1>", limpo_tpl, re.S):
    alvos.append(("prosa", m.group(2)))
for m in re.finditer(r'title="([^"]*)"', limpo_tpl):
    alvos.append(("dica", m.group(1)))
# o objeto AJUDA inteiro, que é só texto de hover
aj = re.search(r"const AJUDA = \{(.*?)\n\};", limpo_tpl, re.S)
if aj:
    alvos.append(("dica", aj.group(1)))
# os rótulos das abas
tabs = re.search(r"const ABAS = \[(.*?)\];", limpo_tpl, re.S)
if tabs:
    # o terceiro item de cada aba é índice de coluna, não texto
    alvos.append(("dica", re.sub(r",\s*\d+\]", "]", tabs.group(1))))

def _texto_dos_literais(js):
    """Todo pedaço de texto humano nos literais do JS, inclusive aninhados.

    Regex não serve aqui. O texto que mais interessa mora dentro de ${...} —
    é o caso do title= dos selos de ritmo, montado por ternário com template
    literal em cada braço. Uma varredura por regex casa a crase de abertura
    desse literal interno como se fosse o fechamento do externo, e o texto
    passa inteiro sem ser conferido. Só um scanner com pilha enxerga isso.
    """
    achados = []

    def literal(i):
        """Consome o literal que começa em js[i]; devolve o índice seguinte."""
        aspa, j, buf = js[i], i + 1, []
        while j < len(js):
            c = js[j]
            if c == "\\":
                j += 2
                continue
            if c == aspa:
                break
            if aspa == "`" and js.startswith("${", j):
                achados.append("".join(buf))
                buf = []
                j = expressao(j + 2)
                continue
            buf.append(c)
            j += 1
        achados.append("".join(buf))
        return j + 1

    def expressao(i):
        """Consome ${...} casando chaves e descendo em literais aninhados."""
        nivel, j = 1, i
        while j < len(js) and nivel:
            c = js[j]
            if c == "\\":
                j += 2
            elif c in "\"'`":
                j = literal(j)
            elif c == "{":
                nivel += 1
                j += 1
            elif c == "}":
                nivel -= 1
                j += 1
            else:
                j += 1
        return j

    i = 0
    while i < len(js):
        if js[i] in "\"'`":
            i = literal(i)
        else:
            i += 1
    return achados


# Rede final: qualquer texto de literal do JS que pareça frase em português.
# As extrações por contexto acima têm ponto cego; esta é por forma — se tem
# duas palavras seguidas, é frase, e frase não leva número escrito à mão.
# Pega inclusive o texto que ainda nem tem contexto definido.
for _s in _texto_dos_literais(
        re.sub(r"//[^\n]*", "", sem_css[sem_css.find("<script>"):])):
    if (re.search(r"[A-Za-zÀ-ÿ]{4,}\s+[a-zà-ÿ]{2,}", _s)
            and "px" not in _s and "var(" not in _s):
        alvos.append(("frase", _s))

for origem, txt in alvos:
    achados = _numeros(re.sub(r"\s+", " ", txt).strip())
    if achados:
        erro(origem, "número literal {} em: {}".format(
            achados, re.sub(r"<[^>]+>", "", txt).strip()[:70]))


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
