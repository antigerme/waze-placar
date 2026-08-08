#!/usr/bin/env python3
"""Recalcula do zero tudo que a página publica, e compara com o que está nela.

Escrito de propósito **sem** chamar as funções do `pagina.py`: se reusasse a
aritmética dele, a conferência só provaria que o código é igual a si mesmo.
Aqui cada número é refeito a partir do JSONL cru da coleta e comparado com o
que a página realmente carrega no `const D`.

    python3 scripts/placar.py --salvar-perfis perfis.jsonl --out placar.html
    python3 scripts/conferir.py --pagina placar.html --perfis perfis.jsonl

O JSONL precisa ser o da mesma coleta que gerou a página: o vetor diário é
ancorado no dia em que foi buscado, e comparar um de ontem com uma página de
hoje acusa divergência em tudo que é janela. O script confere isso antes de
começar e recusa em vez de despejar mil falhas.
"""
import argparse
import collections
import datetime as dt
import json
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))
import pagina as P          # noqa: E402  — só para ler as constantes nomeadas

falhas = []
checados = [0]


def conf(nome, esperado, obtido, tol=0):
    checados[0] += 1
    if isinstance(esperado, (int, float)) and isinstance(obtido, (int, float)):
        ok = abs(esperado - obtido) <= tol
    else:
        ok = esperado == obtido
    if not ok:
        falhas.append("%-46s esperado=%s  página=%s" % (nome, esperado, obtido))


def carrega_payload(caminho):
    """O `const D` que a página carrega, exatamente como o navegador o vê."""
    with open(caminho, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"const D = (\{.*?\});\n", html, re.S)
    if not m:
        sys.exit("não achei o payload `const D` em " + caminho)
    # o gerador escapa `</` para não fechar o <script> antes da hora
    return json.loads(m.group(1).replace("<\\/", "</"))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pagina", default="placar.html", help="HTML gerado")
    ap.add_argument("--perfis", required=True, help="JSONL da mesma coleta")
    ap.add_argument("--max-falhas", type=int, default=40,
                    help="quantas divergências imprimir")
    a = ap.parse_args()

    D = carrega_payload(a.pagina)
    with open(a.perfis, encoding="utf-8") as f:
        perfis = [json.loads(l) for l in f if l.strip()]

    # Numa coleta `--sem-perfis` não existe vetor diário: tudo que é janela sai
    # zerado por não ter sido medido, e a página diz isso em vez de mostrar
    # painel vazio. Não há o que conferir aqui, e sem esta saída o primeiro
    # painel dividia por zero e devolvia traceback em vez de explicação.
    if D["cfg"].get("semAtividade"):
        sys.exit("esta página foi gerada sem perfis, então não tem vetor diário "
                 "para conferir.\nGere com a coleta completa e rode de novo.")

    hoje = dt.date.today()
    d0 = hoje - dt.timedelta(days=P.JANELA)
    cal = D["paineis"].get("calendario") or []
    if cal and cal[0][0] != d0.isoformat():
        sys.exit("a página começa a janela em {} e hoje ela começaria em {}.\n"
                 "Página e JSONL precisam ser da mesma coleta, e do dia de hoje."
                 .format(cal[0][0], d0.isoformat()))

    ED = {e[0]: e for e in D["editores"]}
    conf("nº de editores no payload", len(perfis), len(D["editores"]))

    # ------------------------------------------------ 1. valores por editor
    for p in perfis:
        nome = p["username"]
        e = ED.get(nome)
        if e is None:
            falhas.append("editor %s sumiu do payload" % nome)
            continue
        act = list(p.get("activity") or [])
        if len(act) < P.VETOR:
            act = [0] * (P.VETOR - len(act)) + act
        fech = act[:-1]                       # a janela fechada, sem hoje
        conf("d7 de " + nome, sum(act[-P.JANELA_CURTA - 1:-1]), e[4])
        conf("d30 de " + nome, sum(act[-P.JANELA_MEDIA - 1:-1]), e[5])
        conf("d90 de " + nome, sum(fech), e[6])
        conf("total de " + nome, p.get("edits") or 0, e[3])
        # sequência: dias seguidos com edição, de trás para frente, sem hoje
        s = 0
        for x in reversed(fech):
            if x > 0:
                s += 1
            else:
                break
        conf("seq de " + nome, s, e[7] or 0)
        # tendência: segunda metade da janela contra a primeira
        pri, seg = sum(act[:P.META_DIAS]), sum(act[P.META_DIAS:P.JANELA])
        esp = None if pri + seg < P.TEND_MIN else (
            999 if pri == 0 else round(100 * (seg - pri) / pri))
        conf("tendência de " + nome, esp, e[8])
        # selo de ritmo
        d90 = sum(fech)
        r = None
        if d90 >= P.RITMO_MIN:
            ativos = sum(1 for v in fech if v > 0)
            pico = 100 * max(fech) / d90 if d90 else 0
            if ativos >= P.RITMO_DIAS and pico <= P.RITMO_PICO_MAX:
                r = "constante"
            elif pico >= P.RITMO_PICO_MIN:
                r = "explosivo"
        conf("ritmo de " + nome, r, e[12])
        # faísca: baldes de dias, ou nada para quem não editou na janela
        if d90 > 0:
            baldes = [sum(fech[i * P.BUCKET_DIAS:(i + 1) * P.BUCKET_DIAS])
                      for i in range(P.BUCKETS)]
            conf("faísca de " + nome, baldes, e[9])
        else:
            conf("faísca de " + nome, None, e[9])

    # ------------------------------------------------------------ 2. abas
    for k, col in (("d7", 4), ("d30", 5), ("d90", 6)):
        esp = [n for n, e in ED.items() if e[col] > 0]
        obt = [D["editores"][i][0] for i in D["abas"][k]]
        conf("aba %s: quantidade" % k, len(esp), len(obt))
        conf("aba %s: mesmo conjunto" % k, set(esp), set(obt))
        conf("aba %s: ordem decrescente" % k, True,
             all(ED[obt[i]][col] >= ED[obt[i + 1]][col]
                 for i in range(len(obt) - 1)))
    obt_tot = [D["editores"][i][0] for i in D["abas"]["tot"]]
    conf("aba tot: todo mundo", len(perfis), len(obt_tot))
    conf("aba tot: ordem por carreira", True,
         all(ED[obt_tot[i]][3] >= ED[obt_tot[i + 1]][3]
             for i in range(len(obt_tot) - 1)))

    # ------------------------------------------------------- 3. KPIs e resumo
    R = D["resumo"]
    conf("KPI ativos na janela média",
         sum(1 for e in ED.values() if e[5] > 0), R["ativos30"])
    conf("KPI edições na janela", sum(e[6] for e in ED.values()), R["edicoes90"])
    conf("resumo: ativos na janela",
         sum(1 for e in ED.values() if e[6] > 0), R["ativos90"])
    conf("resumo: universo", len(perfis), R["historico"])
    conf("resumo: soma das carreiras",
         sum(e[3] for e in ED.values()), R["edicoesTotal"])

    # ------------------------------------------------------- 4. concentração
    tot90 = sum(e[6] for e in ED.values())
    ord90 = sorted((e[6] for e in ED.values()), reverse=True)
    # ninguém editou na janela: o gerador divide por 1 para não estourar, e a
    # conferência precisa dividir igual — senão acusa divergência onde não há
    for n, pc in D["paineis"]["concentracao"]:
        conf("concentração top %d" % n,
             round(100 * sum(ord90[:n]) / (tot90 or 1), 1), pc, 0.05)
    conf("KPI de concentração casa com o corte",
         dict(D["paineis"]["concentracao"])[P.CONC_KPI], R["concKpi"])

    # ---------------------------------------------------- 5. fator de ônibus
    poruf = collections.defaultdict(list)
    for n, e in ED.items():
        if e[1] and e[6] > 0:
            poruf[e[1]].append(e[6])
    esp_est = []
    for uf, vs in poruf.items():
        vs.sort(reverse=True)
        tot, acc, f = sum(vs), 0, 0
        for v in vs:
            acc += v
            f += 1
            if acc >= tot / 2:
                break
        esp_est.append((uf, tot, len(vs), f))
    esp_est.sort(key=lambda r: -r[1])
    conf("estados: quantidade", len(esp_est), len(D["paineis"]["estados"]))
    for (uf, tot, n, f), linha in zip(esp_est, D["paineis"]["estados"]):
        conf("estado %s: sigla" % uf, uf, linha[0])
        conf("estado %s: edições" % uf, tot, linha[1])
        conf("estado %s: ativos" % uf, n, linha[2])
        conf("estado %s: fator" % uf, f, linha[3])
    conf("KPI de estados com fator 1",
         sum(1 for r in esp_est if r[3] == 1), R["fator1"])

    # --------------------------------------------------------- 6. níveis
    porniv = collections.defaultdict(lambda: [0, 0])
    for n, e in ED.items():
        if e[2]:
            porniv[e[2]][0] += 1
            if e[6] > 0:
                porniv[e[2]][1] += 1
    conf("níveis: linhas", sorted(porniv), [r[0] for r in D["paineis"]["niveis"]])
    for lv, n, viv in D["paineis"]["niveis"]:
        conf("nível %d: total" % lv, porniv[lv][0], n)
        conf("nível %d: ativos" % lv, porniv[lv][1], viv)

    # ------------------------------------------ 7. ritmo semanal e calendário
    semana = [0] * len(P.DIAS)
    diario = [0] * P.JANELA
    for p in perfis:
        act = p.get("activity") or []
        for i, v in enumerate(act[:-1]):
            if v and i < P.JANELA:
                semana[(d0 + dt.timedelta(days=i)).weekday()] += v
                diario[i] += v
    conf("ritmo semanal", semana, [x[1] for x in D["paineis"]["semana"]])
    uteis = [i for i in range(len(P.DIAS)) if i < 5]
    fds = [i for i in range(len(P.DIAS)) if i >= 5]
    media_util = sum(semana[i] for i in uteis) / len(uteis)
    if media_util:
        conf("delta de fim de semana",
             round(100 * ((sum(semana[i] for i in fds) / len(fds))
                          / media_util - 1)), R["deltaFds"])
    med = sorted(diario)[len(diario) // 2]
    conf("mediana diária", med, D["paineis"]["calMediana"])
    m = sum(diario) / len(diario)
    sd = (sum((v - m) ** 2 for v in diario) / len(diario)) ** 0.5
    esp_fora = [1 if v > med + P.CAL_DESVIOS * sd
                else (-1 if v < med - P.CAL_DESVIOS * sd else 0) for v in diario]
    conf("calendário: dias fora da curva", esp_fora,
         [c[2] for c in D["paineis"]["calendario"]])
    conf("calendário: nº de dias", P.JANELA, len(D["paineis"]["calendario"]))

    # --------------------------------------------------- 8. safras e retenção
    safras = collections.defaultdict(lambda: [0, 0])
    for p in perfis:
        if not p.get("firstEditDate"):
            continue
        ano = dt.datetime.utcfromtimestamp(p["firstEditDate"] / 1000).year
        safras[ano][0] += 1
        if ED[p["username"]][6] > 0:
            safras[ano][1] += 1
    esp_ent = [[an, safras[an][0], safras[an][1]] for an in sorted(safras)]
    conf("safras de entrada", esp_ent, D["paineis"]["entrada"])
    lim = hoje.year - P.SAFRA_MADURA
    taxas = sorted(round(100 * v / n) for an, n, v in esp_ent
                   if n >= P.SAFRA_MIN and an <= lim)
    # sem nenhuma safra grande e madura não há retenção a medir, e a página
    # também não a mostra — conferir aqui daria IndexError numa coleta pequena
    if taxas:
        conf("retenção mediana", taxas[len(taxas) // 2], R["retencao"])
        conf("faixa de retenção", [taxas[0], taxas[-1]], R["faixaRetencao"])
    conf("ano limite da safra madura", lim, R["safraLimite"])

    # ------------------------------------------- 9. gigantes parados e evasão
    por_tot = sorted(ED.values(), key=lambda e: -e[3])
    esp_par = [e[0] for e in por_tot[:P.TOP_PARADOS] if e[6] < P.PARADO_MAX][:12]
    conf("gigantes parados", esp_par, [r[0] for r in D["paineis"]["parados"]])

    def silencio(act):
        for i, v in enumerate(reversed(act[:-1])):
            if v > 0:
                return i
        return None

    ev = []
    for p in perfis:
        act = list(p.get("activity") or [])
        if len(act) < P.VETOR:
            act = [0] * (P.VETOR - len(act)) + act
        pri, sil = sum(act[:P.META_DIAS]), silencio(act)
        if pri >= P.EVASAO_MIN and sil is not None and sil >= P.EVASAO_DIAS:
            ev.append((p["username"], pri))
    ev.sort(key=lambda r: -r[1])
    conf("vigília de evasão", [r[0] for r in ev[:10]],
         [r[0] for r in D["paineis"]["evasao"]])

    # -------------------------------------------------------- 10. novatos
    nov = []
    for p in perfis:
        if not p.get("firstEditDate"):
            continue
        ini = dt.datetime.utcfromtimestamp(p["firstEditDate"] / 1000).date()
        if ini < d0:
            continue
        act = list(p.get("activity") or [])
        if len(act) < P.VETOR:
            act = [0] * (P.VETOR - len(act)) + act
        nov.append(1 if sum(act[-P.RECENTE_DIAS - 1:-1]) > 0 else 0)
    conf("novatos: total", len(nov), D["paineis"]["novatosTotal"])
    conf("novatos: ainda ativos", sum(nov), D["paineis"]["novatosVivos"])

    # -------------------------------------------------------- 11. mentoria
    apad = {}
    for p in perfis:
        for mt in (p.get("mentees") or []):
            n = mt.get("username") if isinstance(mt, dict) else mt
            if n:
                apad[n] = p["username"]
    MT = D["paineis"]["mentoria"]
    rastreados = [n for n in apad if n in ED]
    conf("mentoria: afilhados rastreados", len(rastreados), MT["rastreados"])
    resto = [n for n in ED if n not in apad]
    if rastreados and resto and MT.get("comparavel"):
        viv = sum(1 for n in rastreados if ED[n][6] > 0)
        conf("mentoria: % de apadrinhados ativos",
             round(100 * viv / len(rastreados)), MT["pctApad"])
        conf("mentoria: % dos demais ativos",
             round(100 * sum(1 for n in resto if ED[n][6] > 0) / len(resto)),
             MT["pctResto"])
    conf("mentoria: nº de mentores",
         sum(1 for p in perfis if p.get("mentees")), MT["mentores"])

    # ------------------------------------- 12. a caminho do próximo nível
    # O painel ordena por atividade. Ordenar por progresso acumulado punha no
    # topo quem já parou de editar — ver docs/decisoes.md.
    nv = D["paineis"].get("candidatos") or {}
    for lista in ("prontos", "quase"):
        for linha in (nv.get(lista) or []):
            u, _uf, _lv, _alvo, pct, ed, lim, dias, d90 = linha
            if u in ED:
                conf("candidato %s: edições da janela" % u, ED[u][6], d90)
            if lim:
                conf("candidato %s: progresso" % u, int(100 * ed / lim), pct)
    prontos = nv.get("prontos") or []
    conf("candidatos prontos: ordem por atividade", True,
         all(prontos[i][8] >= prontos[i + 1][8] for i in range(len(prontos) - 1)))
    quase = nv.get("quase") or []
    conf("candidatos: ninguém pronto na lista de quem falta", True,
         all(linha[4] < 100 for linha in quase))
    conf("candidatos que faltam: ordem por prazo", True,
         all(quase[i][7] <= quase[i + 1][7] for i in range(len(quase) - 1)))

    # ---------------------------------------------- 13. sanidade do payload
    bruto = json.dumps(D)
    for campo in ("mapEditingBanned", "rankLocked", "lastEditPoint",
                  "candidatosOmitidos"):
        conf("campo sensível '%s' fora do payload" % campo, True,
             campo not in bruto)
    conf("cfg tem todos os limiares que o texto usa", True, all(
        k in D["cfg"] for k in (
            "janela", "janelaMedia", "janelaCurta", "meta", "evasaoDias",
            "topParados", "paradoMax", "recenteDias", "concKpiN", "baldes",
            "baldeDias", "tendBanda", "ritmoDias", "ritmoPicoMax",
            "ritmoPicoMin", "calDesvios", "refMin", "safraMin", "safraMadura",
            "ritmoHorizonte", "ritmoEmSemanas")))
    conf("nenhum None onde a página espera número", True, all(
        isinstance(R[k], (int, float)) for k in
        ("ativos30", "ativos90", "historico", "edicoesTotal", "edicoes90",
         "concKpi", "deltaFds", "retencao", "fator1")))

    print("conferências: %d" % checados[0])
    if falhas:
        print("\nDIVERGÊNCIAS (%d):" % len(falhas))
        for f in falhas[:a.max_falhas]:
            print("  " + f)
        if len(falhas) > a.max_falhas:
            print("  ... e mais %d" % (len(falhas) - a.max_falhas))
        return 1
    print("tudo bate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
