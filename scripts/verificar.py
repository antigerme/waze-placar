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

# A lista de scripts se descobre sozinha: fixá-la à mão já deixou uma
# ferramenta nova de fora da conferência, que é o jeito de a documentação
# descolar sem ninguém notar.
reais = set()
EU = Path(__file__).name
for caminho in sorted(SCRIPTS.glob("*.py")):
    # a si mesmo não: este arquivo cita a marca abaixo e chamaria a si próprio
    if caminho.name == EU:
        continue
    if "argparse.ArgumentParser" not in caminho.read_text(encoding="utf-8"):
        continue                              # módulo, não ferramenta de CLI
    try:
        reais |= flags_de(caminho.name)
    except Exception as e:                                   # noqa: BLE001
        erro("cli", "não consegui rodar {} --help: {}".format(caminho.name, e))

citadas = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", readme))
for f in sorted(citadas - reais):
    erro("cli", "README cita {}, que não existe mais".format(f))

# Ferramenta que ninguém sabe que existe é ferramenta perdida: os validadores
# mais pesados moraram fora do repositório e sumiram com o contêiner uma vez.
docs = readme + (RAIZ / "CLAUDE.md").read_text(encoding="utf-8")
for arq in sorted((RAIZ / "docs").glob("*.md")):
    docs += arq.read_text(encoding="utf-8")
for caminho in sorted(SCRIPTS.iterdir()):
    if caminho.suffix in (".py", ".mjs") and caminho.name not in docs:
        erro("cli", "scripts/{} não é citado em documento nenhum"
             .format(caminho.name))


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


# Número por extenso envelhece igual: "as três janelas" quebra no dia em que a
# API oferecer uma quarta, e nenhum dígito aparece para a checagem achar. Fora
# da lista: "um"/"uma", que em português são artigo antes de serem número, e
# sinalizariam em cada frase da página.
EXTENSO = ("dois", "duas", "três", "tres", "quatro", "cinco", "seis", "sete",
           "oito", "nove", "dez", "onze", "doze", "treze", "catorze",
           "quatorze", "quinze", "dezesseis", "dezessete", "dezoito",
           "dezenove", "vinte", "trinta", "quarenta", "cinquenta", "sessenta",
           "setenta", "oitenta", "noventa", "cem", "cento", "duzentos",
           "trezentos", "quinhentos", "mil")
_RX_EXTENSO = re.compile(
    r"(?<![0-9A-Za-zÀ-ÿ])(" + "|".join(EXTENSO) + r")(?![0-9A-Za-zÀ-ÿ])", re.I)


def _numeros(txt):
    """Números escritos à mão num pedaço de texto da página.

    As aspas ficaram fora do lookbehind de propósito: com elas, um rótulo
    inteiro como "90 dias" passava batido, porque o número encostava na aspa
    de abertura. Era assim que os rótulos das abas escapavam.
    """
    return (re.findall(r'(?<![\w$.{#\-/])\b(\d{2,})\b', txt)
            + _RX_EXTENSO.findall(txt))


alvos = []
# o lookahead impede que `<p` case `<path` de SVG e leve coordenada como prosa
for m in re.finditer(r"<(p|h2|th|td)(?=[\s/>])[^>]*>(.*?)</\1>", limpo_tpl, re.S):
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
    # Fora as tags: número em atributo é marcação — coordenada de SVG, largura,
    # viewBox —, não texto que alguém lê. Sem isto, `<circle cx="12"` passa pelo
    # teste de frase ("circle" seguido de "cx") e vira falso positivo. A prosa
    # que mora dentro de atributo já é conferida pela extração de `title=`.
    _s = re.sub(r"<[^>]*>", " ", _s)
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


# -------------------------------------------- 7. a página ainda monta inteira
# Compilar não basta: renomear um campo do payload quebra quem lê o nome antigo
# e só aparece no fim de uma coleta de quarenta minutos. Aconteceu com `top50`,
# que o placar.py lia depois de já ter publicado a página — KeyError com o
# arquivo no ar e saída diferente de zero no cron. Aqui a página é montada de
# ponta a ponta com dado sintético, sem tocar na rede.
sys.path.insert(0, str(SCRIPTS))
try:
    import pagina as _pag

    _perfis = [{
        "username": "fulano", "level": 3, "edits": 1234, "userId": "1",
        "activity": [i % 5 for i in range(_pag.VETOR)],
        "firstEditDate": 1400000000000, "menteesCount": 0,
        "editsByType": {"segmentos": 10},
    }]
    # `universo` entra porque sem ele o painel de alcance se omite, e a página
    # seria montada sem passar por ele — o smoke test não veria uma quebra lá.
    _dados = _pag.prepara(_perfis, {"fulano": "BR-SP"}, "01/01/2000 00:00 UTC",
                          estat={"foraPct": 1, "semEdicaoPct": 2, "universo": 3,
                                 "linhasJanela": 9, "ativosJanela": 2,
                                 "novatosForaDoRanking": 1,
                                 "candidatosForaDoRanking": 1})
    _html = _pag.build_html(_dados)
    if "__DATA__" in _html:
        erro("monta", "o marcador __DATA__ ficou na página")
    # os campos que o placar.py imprime no fim da execução
    _resumo = _dados["resumo"]
    _placar = (SCRIPTS / "placar.py").read_text(encoding="utf-8")
    for _campo in sorted(set(re.findall(r'\br\["(\w+)"\]', _placar))):
        if _campo not in _resumo:
            erro("monta", 'placar.py lê resumo["{}"], que prepara() não devolve'
                 .format(_campo))
    for _const in sorted(set(re.findall(r"\bpagina\.([A-Z_]+)\b", _placar))):
        if not hasattr(_pag, _const):
            erro("monta", "placar.py usa pagina.{}, que não existe".format(_const))

    # O painel de quem está subindo de nível ordena por atividade, não pelo
    # progresso acumulado. Voltar a ordenar por progresso é fácil e silencioso:
    # a página continua montando, só põe no topo quem parou de editar há meses.
    # Os quatro sintéticos abaixo têm as duas ordens invertidas de propósito.
    _quentes = {"activity": [10] * _pag.VETOR, "firstEditDate": 1400000000000}
    _frios = {"activity": [1] + [0] * (_pag.VETOR - 1),
              "firstEditDate": 1400000000000}
    _cands = [
        # nome           frac  edições  quanto falta / ritmo  = ordem esperada
        ("quase-ativo",  0.80,   2400,  _quentes),   # 600 a 10/dia
        ("quase-parado", 0.99,   2970,  _frios),     # 30 a 1/90 por dia
        ("feito-ativo",  1.10,   3300,  _quentes),
        ("feito-parado", 1.20,   3600,  _frios),
    ]
    _dados = _pag.prepara(
        [dict(_perf, username=_n, level=1, edits=_e, userId=_n)
         for _n, _f, _e, _perf in _cands],
        dict((_n, "BR-SP") for _n, _f, _e, _p in _cands),
        "01/01/2000 00:00 UTC",
        estat={"candidatos": [
            {"username": _n, "level": 1, "alvo": 2, "frac": _f, "edits": _e,
             "uf": "SP"} for _n, _f, _e, _p in _cands]})
    _nv = _dados["paineis"]["candidatos"]
    for _lista, _esperado in (("quase", ["quase-ativo", "quase-parado"]),
                              ("prontos", ["feito-ativo", "feito-parado"])):
        _obtido = [_l[0] for _l in _nv[_lista]]
        if _obtido != _esperado:
            erro("monta", "candidatos[{}] saiu {} — a ordem não é por atividade"
                 .format(_lista, _obtido))
    # a estimativa de prazo é o que ordena a lista de quem ainda não chegou
    if [_l[7] for _l in _nv["quase"]] != [60, 2700]:
        erro("monta", "prazo dos candidatos saiu {}, esperado [60, 2700]".format(
            [_l[7] for _l in _nv["quase"]]))
except Exception as _e:                                      # noqa: BLE001
    erro("monta", "a página não monta com dado sintético: {}: {}".format(
        type(_e).__name__, _e))


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
