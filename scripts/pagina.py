#!/usr/bin/env python3
"""Monta o HTML do placar a partir dos perfis coletados."""

import datetime as dt
import html
import json
from collections import Counter, defaultdict

import waze

DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
BUCKETS = 15          # baldes da faísca; BUCKETS * BUCKET_DIAS = JANELA
BUCKET_DIAS = 6
VETOR = 91            # posições que o perfil devolve: a janela mais hoje

# Os textos da página derivam destes valores. Nada de número escrito à mão na
# prosa nem nas dicas de hover: se um limiar mudar aqui, a explicação muda
# junto. Tudo que a página menciona sai daqui para o `cfg` e de lá para o texto.
JANELA = 90           # dias fechados do vetor de atividade
JANELA_MEDIA = 30     # aba do meio
JANELA_CURTA = 7      # aba mais curta
META_DIAS = 45        # metade da janela, base da tendência
EVASAO_DIAS = 21      # silêncio que liga o alerta
EVASAO_MIN = 300      # produção mínima na 1ª metade para entrar na vigília
TOP_PARADOS = 60      # recorte do histórico para os "gigantes parados"
PARADO_MAX = 100      # abaixo disto na janela é "praticamente não edita"
SAFRA_MIN = 10        # tamanho mínimo de safra para a taxa significar algo
SAFRA_MADURA = 5      # anos para a safra ter tido tempo de perder quem ia sair
CAP_RANKING = 500     # teto de linhas por ranking, imposto pela API
RECENTE_DIAS = 14     # "ainda ativo" para quem acabou de estrear
CAL_DESVIOS = 2       # desvios da mediana para o dia entrar como fora da curva
CONC_FAIXAS = (5, 10, 25, 50, 100)   # cortes do painel de concentração
CONC_KPI = 50         # qual dos cortes vira KPI; precisa estar em CONC_FAIXAS
CANDIDATOS_LISTA = 12  # linhas do painel de quem está subindo de nível
# Até quando faz sentido estimar quanto falta para o próximo nível. Além disso
# o texto diz que está longe, sem número: projetar anos a partir de noventa
# dias de ritmo seria dar precisão que o dado não tem.
RITMO_HORIZONTE = 730  # dias
RITMO_EM_SEMANAS = 60  # abaixo disto o prazo sai em semanas, não em meses
REF_MIN = 10          # linhas na tela para as réguas da tabela significarem algo
# Teto de linhas desenhadas de uma vez. Não é enfeite: a aba do histórico tem
# milhares de editores, e cada linha vira mais de dez nós. Num celular modesto,
# montar tudo travava a página por quase três segundos a cada troca de aba.
LINHAS_MAX = 300
# Fatia mínima dos afilhados nomeados que precisa ser mensurável para a
# comparação de mentoria valer. Sem isso a página compara só quem já estava no
# universo — e estar no universo exige ter aparecido num ranking, ou seja, ter
# dado certo. Foi assim que este projeto quase publicou 100% de retenção.
MENTORIA_COBERTURA = 60   # por cento

# Tendência: variação entre as duas metades da janela.
TEND_MIN = 200        # volume mínimo para a razão significar algo
TEND_BANDA = 10       # variação em % dentro da qual o ritmo é "estável"

# Ritmo: maratonista ou velocista.
RITMO_MIN = 500       # edições na janela para valer a pena classificar
RITMO_DIAS = 60       # dias com edição para ser "constante"
RITMO_PICO_MAX = 10   # % do total no maior dia, teto do "constante"
RITMO_PICO_MIN = 25   # % do total no maior dia, piso do "explosivo"


def _streak(act):
    """Dias consecutivos editando, ignorando o dia de hoje (parcial)."""
    s = 0
    for x in reversed(act[:-1]):
        if x > 0:
            s += 1
        else:
            break
    return s


def _tendencia(act):
    """Variação entre os segundos 45 dias e os primeiros 45.

    Só devolve número quando há volume suficiente para a razão significar
    alguma coisa — senão 3 edições contra 1 viram '+200%'.
    """
    a, b = sum(act[:META_DIAS]), sum(act[META_DIAS:JANELA])
    if a + b < TEND_MIN:
        return None
    if a == 0:
        return 999
    return round(100 * (b - a) / a)


TIPOS = {
    "segment": "segmentos", "venue": "locais",
    "venueUpdateRequest": "UR local", "mapUpdateRequest": "UR mapa",
    "houseNumber": "numeração", "machineMapProblem": "MP auto",
    "schedule": "horários",
}
# Qual especialidade é maioria muda conforme a aba — entre os ativos não é a
# mesma que no histórico inteiro. Esmaecer a errada destacaria justamente o
# comum, então isto é medido por aba, não fixado aqui.


def _especialidade(tipos):
    """O tipo de edição que domina o trabalho histórico do editor."""
    t = {k: v for k, v in (tipos or {}).items() if v}
    if not t:
        return None
    return TIPOS.get(max(t, key=t.get), max(t, key=t.get))


def _ritmo(act, d90):
    """Maratonista ou velocista.

    Só classifica quem tem volume: com pouca edição no trimestre, 'explosivo'
    diria mais sobre o acaso do que sobre a pessoa.
    """
    if d90 < RITMO_MIN:
        return None
    dias = act[:-1]
    ativos = sum(1 for v in dias if v > 0)
    pico = max(dias) if dias else 0
    conc = 100 * pico / d90 if d90 else 0
    if ativos >= RITMO_DIAS and conc <= RITMO_PICO_MAX:
        return "constante"
    if conc >= RITMO_PICO_MIN:
        return "explosivo"
    return None


def _silencio(act):
    """Dias desde a última edição, sem contar hoje. None = nunca editou."""
    for i, v in enumerate(reversed(act[:-1])):
        if v > 0:
            return i
    return None


# Recorte do Brasil, com folga. Fora daqui há áreas de Champs com
# responsabilidade em outros países — contadas à parte, não desenhadas.
MAPA_LON = (-74.5, -33.5)
MAPA_LAT = (-34.0, 6.0)
# Lado da célula em grau. A conversão para km sai de CELULA * 111 e vai para o
# cfg — a página não repete o número, lê de lá.
CELULA = 0.5


def _dentro(x, y, anel):
    """Ray casting. Os polígonos têm até 3.445 vértices, então nada de
    embutir a geometria crua na página: a grade é o que vai."""
    dentro = False
    n = len(anel)
    j = n - 1
    for i in range(n):
        xi, yi = anel[i][0], anel[i][1]
        xj, yj = anel[j][0], anel[j][1]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
                dentro = not dentro
        j = i
    return dentro


def _grade_cobertura(areas, ufs):
    """Quantos editores distintos gerenciam cada célula da grade."""
    nx = int((MAPA_LON[1] - MAPA_LON[0]) / CELULA)
    ny = int((MAPA_LAT[1] - MAPA_LAT[0]) / CELULA)
    celulas = {}
    fora = set()

    for username, pols in areas.items():
        for pol in pols:
            anel = pol["coordinates"][0]
            xs = [p[0] for p in anel]
            ys = [p[1] for p in anel]
            if (max(xs) < MAPA_LON[0] or min(xs) > MAPA_LON[1]
                    or max(ys) < MAPA_LAT[0] or min(ys) > MAPA_LAT[1]):
                fora.add(username)
                continue
            i0 = max(0, int((min(xs) - MAPA_LON[0]) / CELULA))
            i1 = min(nx - 1, int((max(xs) - MAPA_LON[0]) / CELULA))
            j0 = max(0, int((min(ys) - MAPA_LAT[0]) / CELULA))
            j1 = min(ny - 1, int((max(ys) - MAPA_LAT[0]) / CELULA))
            for i in range(i0, i1 + 1):
                cx = MAPA_LON[0] + (i + 0.5) * CELULA
                for j in range(j0, j1 + 1):
                    cy = MAPA_LAT[0] + (j + 0.5) * CELULA
                    if _dentro(cx, cy, anel):
                        celulas.setdefault((i, j), set()).add(username)

    return {
        "nx": nx, "ny": ny,
        "celulas": sorted([i, j, len(v)] for (i, j), v in celulas.items()),
        "editores": len(areas),
        "fora": len(fora),
        "areas": sum(len(v) for v in areas.values()),
    }


def prepara(perfis, ufs, gerado, areas=None, estat=None, extras=None,
            transacoes=None):
    """Transforma os perfis crus na carga que a página consome."""
    areas = areas or {}
    estat = estat or {}
    # Perfis buscados só para a mentoria; não entram no placar nem nas abas.
    extras = extras or {}
    transacoes = transacoes or []
    eds = []
    for p in perfis:
        act = (p.get("activity") or [])
        if len(act) < VETOR:                   # normaliza vetores curtos
            act = [0] * (VETOR - len(act)) + list(act)
        completos = act[:-1]                   # a janela fechada, sem hoje
        # -1 sempre porque o dia de hoje ainda está correndo e sai da conta
        d7 = sum(act[-JANELA_CURTA - 1:-1])
        d30 = sum(act[-JANELA_MEDIA - 1:-1])
        d90 = sum(completos)
        semanas = [sum(completos[i * BUCKET_DIAS:(i + 1) * BUCKET_DIAS])
                   for i in range(BUCKETS)]
        ano = inicio = None
        if p.get("firstEditDate"):
            quando = dt.datetime.utcfromtimestamp(p["firstEditDate"] / 1000).date()
            ano, inicio = quando.year, quando
        eds.append({
            "u": p["username"], "uf": ufs.get(p["username"]),
            "lvl": p.get("level"), "tot": p.get("edits") or 0,
            "d7": d7, "d30": d30, "d90": d90,
            "recente": sum(act[-RECENTE_DIAS - 1:-1]),
            "inicio": inicio,
            "streak": _streak(act), "tend": _tendencia(act),
            "semanas": semanas if d90 > 0 else None, "ano": ano,
            "mentees": p.get("menteesCount") or 0,
            "esp": _especialidade(p.get("editsByType")),
            "ritmo": _ritmo(act, d90),
            "silencio": _silencio(act),
            "prim45": sum(act[:META_DIAS]), "seg45": sum(act[META_DIAS:JANELA]),
            "areas": len(areas.get(p["username"]) or []),
        })

    # Sem nenhum vetor diário não existe janela: `--sem-perfis`, ou uma coleta
    # em que o Descartes recusou todos os perfis. Tudo que é medido em 7/30/90
    # dias sai zerado, e zero aqui significa "não medido", não "não aconteceu".
    # A página precisa saber disso para omitir em vez de afirmar.
    sem_atividade = not any(p.get("activity") for p in perfis)

    idx = list(range(len(eds)))
    abas = {
        "d30": sorted([i for i in idx if eds[i]["d30"] > 0],
                      key=lambda i: -eds[i]["d30"]),
        "d7": sorted([i for i in idx if eds[i]["d7"] > 0],
                     key=lambda i: -eds[i]["d7"]),
        "d90": sorted([i for i in idx if eds[i]["d90"] > 0],
                      key=lambda i: -eds[i]["d90"]),
        "tot": sorted(idx, key=lambda i: -eds[i]["tot"]),
    }

    # --- painéis -----------------------------------------------------------
    hoje = dt.date.today()
    d0 = hoje - dt.timedelta(days=90)
    semana = [0] * 7
    diario = [0] * JANELA
    for p in perfis:
        act = p.get("activity") or []
        for i, v in enumerate(act[:-1]):
            if v and i < JANELA:
                semana[(d0 + dt.timedelta(days=i)).weekday()] += v
                diario[i] += v

    por90 = sorted(eds, key=lambda e: -e["d90"])
    tot90 = sum(e["d90"] for e in eds)
    # A guarda de divisão fica na divisão. Somando `or 1` no total, uma coleta
    # sem atividade diária publicava "1 edições em 90 dias".
    concentracao = [[n, round(100 * sum(e["d90"] for e in por90[:n]) / (tot90 or 1), 1)]
                    for n in CONC_FAIXAS]
    # O KPI é procurado pelo corte, não por posição na lista: com índice fixo,
    # mexer em CONC_FAIXAS trocaria o número sem trocar o rótulo.
    conc_kpi = dict(concentracao)[CONC_KPI]

    # Safras: quantos entraram em cada ano e quantos desses ainda editam.
    safras = defaultdict(lambda: [0, 0])
    for e in eds:
        if e["ano"]:
            safras[e["ano"]][0] += 1
            if e["d90"] > 0:
                safras[e["ano"]][1] += 1
    entrada = [[a, safras[a][0], safras[a][1]] for a in sorted(safras)]

    por_total = sorted(eds, key=lambda e: -e["tot"])
    parados = [[e["u"], e["uf"], e["tot"], e["d90"], i + 1, e["silencio"]]
               for i, e in enumerate(por_total[:TOP_PARADOS])
               if e["d90"] < PARADO_MAX][:12]

    # Fator de ônibus: quantos editores precisam sair para o estado perder
    # metade das edições. Um estado com fator 1 está a uma desistência de parar.
    poruf = defaultdict(list)
    for e in eds:
        if e["uf"] and e["d90"] > 0:
            poruf[e["uf"]].append(e)
    estados = []
    for uf, gente in poruf.items():
        gente.sort(key=lambda x: -x["d90"])
        tot = sum(g["d90"] for g in gente)
        acc = 0
        fator = 0
        for g in gente:
            acc += g["d90"]
            fator += 1
            if acc >= tot / 2:
                break
        estados.append([uf, tot, len(gente), fator, gente[0]["u"],
                        round(100 * gente[0]["d90"] / tot) if tot else 0])
    estados.sort(key=lambda r: -r[1])
    # UFs sem nenhuma edição na janela: têm gente no universo, mas todos
    # parados. Antes sumiam da tabela; agora entram como linha própria, para
    # o fator de ônibus no extremo — ninguém editando — não virar ausência
    # silenciosa. A lista canônica vem do waze.UFS, então uma UF sem ninguém
    # no universo também aparece.
    estados_inativos = sorted(set(waze.UFS) - {r[0] for r in estados})

    # Vigília: produzia no começo da janela e emudeceu no fim.
    evasao = sorted(
        ([e["u"], e["uf"], e["prim45"], e["silencio"]] for e in eds
         if e["prim45"] >= EVASAO_MIN and e["silencio"] is not None
         and e["silencio"] >= EVASAO_DIAS),
        key=lambda r: -r[2])[:10]
    retornos = sum(1 for e in eds if e["prim45"] < 50 and e["seg45"] >= 500)

    # Especialidade mais comum de cada aba, para esmaecer só o que é rotina ali.
    tipo_comum = {}
    for nome, indices in abas.items():
        c = Counter(eds[i]["esp"] for i in indices if eds[i]["esp"])
        tipo_comum[nome] = c.most_common(1)[0][0] if c else None

    # Ritmo semanal: em vez de afirmar que é plano, mede.
    util = sum(semana[:5]) / 5 if sum(semana) else 0
    fds = sum(semana[5:]) / 2 if sum(semana) else 0
    delta_fds = round(100 * (fds / util - 1)) if util else 0

    # Retenção típica das safras com gente suficiente para a razão significar algo.
    # Safra recente sobe por construção: quem entrou este ano ainda não teve
    # tempo de sair. Comparar só as maduras, e dizer isso na página.
    limite_safra = hoje.year - SAFRA_MADURA
    taxas = sorted(round(100 * viv / n) for a, n, viv in entrada
                   if n >= SAFRA_MIN and a <= limite_safra)
    retencao = taxas[len(taxas) // 2] if taxas else 0
    faixa = [taxas[0], taxas[-1]] if taxas else [0, 0]

    # --- nível x atividade -------------------------------------------------
    porniv = defaultdict(lambda: [0, 0])
    for e in eds:
        if e["lvl"]:
            porniv[e["lvl"]][0] += 1
            if e["d90"] > 0:
                porniv[e["lvl"]][1] += 1
    niveis = [[lv, porniv[lv][0], porniv[lv][1]] for lv in sorted(porniv)]

    # --- quem começou dentro da janela --------------------------------------
    novatos = []
    for e in eds:
        if not e["inicio"] or e["inicio"] < d0:
            continue
        novatos.append([e["u"], e["uf"], e["inicio"].isoformat(), e["d90"],
                        1 if e["recente"] > 0 else 0])
    novatos.sort(key=lambda r: -r[3])
    novatos_vivos = sum(1 for r in novatos if r[4])

    # --- calendário da janela, com os dias fora da curva --------------------
    ordenado = sorted(diario)
    mediana = ordenado[len(ordenado) // 2] if ordenado else 0
    if len(diario) > 1:
        m = sum(diario) / len(diario)
        desvio = (sum((v - m) ** 2 for v in diario) / len(diario)) ** 0.5
    else:
        desvio = 0
    calendario = []
    for i, v in enumerate(diario):
        fora = 0
        if desvio:
            if v > mediana + CAL_DESVIOS * desvio:
                fora = 1
            elif v < mediana - CAL_DESVIOS * desvio:
                fora = -1
        calendario.append([(d0 + dt.timedelta(days=i)).isoformat(), v, fora])

    # --- quem está a caminho do próximo nível --------------------------------
    # `frac` é a razão que o Waze calcula contra o limiar do próximo nível.
    # O limiar sai dividindo as edições pela fração — mas só vale citar quando
    # todo mundo do mesmo nível devolve o mesmo valor. Para o primeiro nível
    # isso acontece; acima dele o denominador muda de pessoa para pessoa, e a
    # página não tem como dizer quanto falta. Então o limiar é medido aqui, por
    # nível, e só é publicado onde for único.
    todos_cands = [c for c in (estat.get("candidatos") or []) if c.get("frac")]
    # O Waze lista como candidato quem bate o critério de edições acumuladas,
    # não quem está editando. Medido: a maior parte da lista não tinha nenhuma
    # edição na janela, e os primeiros colocados de "mais perto de chegar"
    # estavam todos parados — um painel chamado "a caminho" prometendo
    # movimento onde não há. Fica quem editou na janela; o resto do placar já
    # cuida de quem parou.
    ativos_ed = {e["u"] for e in eds if e["d90"] > 0}
    cands = [c for c in todos_cands if c["username"] in ativos_ed]
    parados_c = len(todos_cands) - len(cands)
    limiares = {}
    porniv_c = defaultdict(set)
    for c in cands:
        if c.get("level") and c.get("edits"):
            porniv_c[c["level"]].add(round(c["edits"] / c["frac"]))
    for lv, vals in porniv_c.items():
        if len(vals) == 1:
            limiares[lv] = vals.pop()
    # Quanto falta, no ritmo de quem está listado. O limiar sai da própria
    # razão que o Waze devolve — edições dividido por progresso —, e o ritmo do
    # vetor diário. Ordenar por progresso sozinho premiava o acumulado: o
    # primeiro da lista tinha 99% e três edições em noventa dias, enquanto quem
    # chegava em três semanas aparecia abaixo. É o mesmo erro que o placar
    # inteiro existe para não cometer.
    por_nome = {e["u"]: e for e in eds}
    for c in cands:
        d90 = (por_nome.get(c["username"]) or {}).get("d90") or 0
        limiar = c["edits"] / c["frac"] if c["frac"] else 0
        faltam = max(0.0, limiar - c["edits"])
        ritmo = d90 / JANELA
        # arredonda, não trunca: 2400 dividido por 0,8 não dá 3000 exato em
        # ponto flutuante, e truncar transformava 60 dias em 59 — o bastante
        # para o rótulo pular de meses para semanas por ruído de arredondamento
        c["dias"] = int(round(faltam / ritmo)) if ritmo else None
        c["d90"] = d90

    # quem já chegou não tem prazo a estimar; ordena por quem está mais presente
    prontos = sorted((c for c in cands if c["frac"] >= 1), key=lambda c: -c["d90"])
    quase = sorted((c for c in cands if c["frac"] < 1),
                   key=lambda c: (c["dias"] is None, c["dias"], -c["d90"]))

    def _linha(c):
        # trunca em vez de arredondar: com 99,9% arredondado, quem ainda não
        # chegou aparecia com "100%" na lista de quem ainda não chegou
        return [c["username"], c["uf"], c.get("level"), c.get("alvo"),
                int(100 * c["frac"]), c["edits"],
                limiares.get(c.get("level")), c["dias"], c["d90"]]
    candidatos = {
        "prontos": [_linha(c) for c in prontos[:CANDIDATOS_LISTA]],
        "quase": [_linha(c) for c in quase[:CANDIDATOS_LISTA]],
        "totalProntos": len(prontos),
        "totalQuase": len(quase),
        # booleano, não contagem: a página avisa que houve exclusão sem dizer
        # quantos. Mandar o número faria a página publicar, no HTML, o volume
        # de sanção da comunidade — e com o total do painel ao lado, a razão.
        "temOmitidos": bool(estat.get("candidatosOmitidos")),
        "parados": parados_c,
        "foraDoRanking": estat.get("candidatosForaDoRanking") or 0,
        # níveis cujo limiar é o mesmo para todo mundo, então dá para citar
        "limiares": sorted(limiares.items()),
    }

    # --- mentoria ------------------------------------------------------------
    apad = {}
    for p in perfis:
        for m in (p.get("mentees") or []):
            if m.get("username"):
                apad[m["username"]] = p["username"]
    por_nome = {e["u"]: e for e in eds}

    def _d90(u):
        """Atividade do afilhado, venha do universo ou da busca extra."""
        if u in por_nome:
            return por_nome[u]["d90"]
        x = extras.get(u)
        if x is None:
            return None                      # não conseguimos olhar
        return sum((x.get("activity") or [0])[:-1])

    medidos = [u for u in apad if _d90(u) is not None]
    ativos_ap = sum(1 for u in medidos if _d90(u) > 0)
    resto = [e for e in eds if e["u"] not in apad]
    ativos_re = sum(1 for e in resto if e["d90"] > 0)
    mentores = []
    truncados = 0
    for p in perfis:
        lista = [m for m in (p.get("mentees") or []) if m.get("username")]
        if not lista:
            continue
        total = p.get("menteesCount") or len(lista)
        if total > len(lista):
            truncados += 1
        viv = sum(1 for m in lista if (_d90(m["username"]) or 0) > 0)
        mentores.append([p["username"], ufs.get(p["username"]), total,
                         len(lista), viv])
    mentores.sort(key=lambda r: (-r[4], -r[2]))
    cobertura = round(100 * len(medidos) / len(apad)) if apad else 0
    mentoria = {
        "mentores": len(mentores),
        "afilhados": len(apad),
        "rastreados": len(medidos),
        "cobertura": cobertura,
        # Abaixo do piso a comparação não vai para a tela: com amostra parcial
        # ela mede quem já tinha aparecido num ranking, não quem foi
        # apadrinhado, e o número sai altíssimo parecendo achado.
        "comparavel": cobertura >= MENTORIA_COBERTURA,
        "ativosApad": ativos_ap,
        "pctApad": round(100 * ativos_ap / len(medidos)) if medidos else 0,
        "pctResto": round(100 * ativos_re / len(resto)) if resto else 0,
        "top": mentores[:8],
        # A API devolve no máximo 10 afilhados por mentor; para quem tem mais,
        # a fatia de ativos sai de uma amostra, não do conjunto.
        "truncados": truncados,
        "capLista": 10,
    }

    # --- áreas longe do próprio estado --------------------------------------
    centros = {}
    for u, pols in areas.items():
        pts = [(x, y) for pol in pols for x, y in pol["coordinates"][0]
               if MAPA_LON[0] <= x <= MAPA_LON[1] and MAPA_LAT[0] <= y <= MAPA_LAT[1]]
        if pts:
            centros[u] = (sum(q[0] for q in pts) / len(pts),
                          sum(q[1] for q in pts) / len(pts))
    porufc = defaultdict(list)
    for u, c in centros.items():
        if ufs.get(u):
            porufc[ufs[u]].append((u, c))
    forasteiros = []
    for uf, gente in porufc.items():
        if len(gente) < 3:
            continue
        xs = sorted(c[0] for _, c in gente)
        ys = sorted(c[1] for _, c in gente)
        mx, my = xs[len(xs) // 2], ys[len(ys) // 2]
        for u, c in gente:
            km = round((((c[0] - mx) ** 2 + (c[1] - my) ** 2) ** 0.5) * 111)
            if km >= 500:
                forasteiros.append([u, uf, km])
    forasteiros.sort(key=lambda r: -r[2])

    # --- onde as edições recentes aconteceram --------------------------------
    nx = int((MAPA_LON[1] - MAPA_LON[0]) / CELULA)
    ny = int((MAPA_LAT[1] - MAPA_LAT[0]) / CELULA)
    celtx = {}
    fora_br = 0
    cidades = Counter()
    tipos_tx = Counter()
    dias_tx = []
    # As últimas transações de quem edita pouco podem ser de muitos anos atrás
    # (ver docs/api-recon.md). Num painel sobre onde se edita agora, isso
    # mancharia o mapa com trabalho antigo; fora da janela, fora da conta.
    antigas = sum(1 for t in transacoes if (t.get("dias") or 0) > JANELA)
    for t in transacoes:
        if (t.get("dias") or 0) > JANELA:
            continue
        x, y = t["lon"], t["lat"]
        if t.get("cidade"):
            cidades[t["cidade"]] += 1
        for k, v in (t.get("tipos") or {}).items():
            tipos_tx[k] += v
        if t.get("dias") is not None:
            dias_tx.append(t["dias"])
        if not (MAPA_LON[0] <= x <= MAPA_LON[1] and MAPA_LAT[0] <= y <= MAPA_LAT[1]):
            fora_br += 1
            continue
        i = min(nx - 1, int((x - MAPA_LON[0]) / CELULA))
        j = min(ny - 1, int((y - MAPA_LAT[0]) / CELULA))
        celtx[(i, j)] = celtx.get((i, j), 0) + 1
    recentes = [t for t in transacoes if (t.get("dias") or 0) <= JANELA]
    atividade = {
        "nx": nx, "ny": ny,
        "celulas": sorted([i, j, n] for (i, j), n in celtx.items()),
        "edicoes": len(recentes),
        "descartadas": antigas,
        "editores": len({t["username"] for t in recentes}),
        "fora": fora_br,
        "comCidade": sum(1 for t in recentes if t.get("cidade")),
        "cidades": cidades.most_common(12),
        "tipos": tipos_tx.most_common(),
        "diasMax": max(dias_tx) if dias_tx else 0,
    }

    # --- alcance da coleta ---------------------------------------------------
    # De onde saiu cada editor do universo, e o que a fonte deixa de fora. Os
    # dois endpoints de mentoria só contam quem ainda não estava: o `universo()`
    # acrescenta os novatos antes dos candidatos, então as duas contagens não se
    # sobrepõem e a subtração fecha. Medido contra o universo, e não contra os
    # perfis coletados — perfil que falhou some destes, e a conta sairia errada.
    _univ = estat.get("universo") or 0
    _nov = estat.get("novatosForaDoRanking") or 0
    _cand = estat.get("candidatosForaDoRanking") or 0
    cobertura = {
        "universo": _univ,
        "porRanking": max(0, _univ - _nov - _cand),
        "novatos": _nov,
        "candidatos": _cand,
        "perfis": len(eds),
        # o que a varredura das janelas custou e o que ela devolveu
        "linhasJanela": estat.get("linhasJanela") or 0,
        "semEdicaoPct": estat.get("semEdicaoPct") or 0,
        "ativosJanela": estat.get("ativosJanela") or 0,
    }

    ativos30 = len(abas["d30"])
    return {
        "gerado": gerado,
        "janela": [d0.isoformat(), hoje.isoformat()],
        "editores": [[e["u"], e["uf"], e["lvl"], e["tot"], e["d7"], e["d30"],
                      e["d90"], e["streak"], e["tend"], e["semanas"],
                      e["mentees"], e["esp"], e["ritmo"], e["areas"]]
                     for e in eds],
        "abas": abas,
        "tipoComum": tipo_comum,
        "cfg": {
            "rankings": (len(waze.UFS) + 1) * len(waze.PERIODS),
            "quadros": len(waze.UFS) + 1,
            "janelasApi": len(waze.PERIODS),
            "ufs": len(waze.UFS),
            "cap": CAP_RANKING,
            "janela": JANELA,
            "janelaMedia": JANELA_MEDIA,
            "janelaCurta": JANELA_CURTA,
            "meta": META_DIAS,
            "evasaoDias": EVASAO_DIAS,
            "topParados": TOP_PARADOS,
            "celulaGrau": CELULA,
            "celulaKm": round(CELULA * 111),
            "vetorDias": VETOR,
            "safraMin": SAFRA_MIN,
            "safraMadura": SAFRA_MADURA,
            # o ano em que o editor mais antigo do país começou
            "primeiroAno": min([e["ano"] for e in eds if e["ano"]] or [0]),
            "paradoMax": PARADO_MAX,
            "recenteDias": RECENTE_DIAS,
            "calDesvios": CAL_DESVIOS,
            "concKpiN": CONC_KPI,
            "mentoriaCobertura": MENTORIA_COBERTURA,
            "refMin": REF_MIN,
            "linhasMax": LINHAS_MAX,
            "ritmoHorizonte": RITMO_HORIZONTE,
            "ritmoEmSemanas": RITMO_EM_SEMANAS,
            "baldes": BUCKETS,
            "baldeDias": BUCKET_DIAS,
            "tendBanda": TEND_BANDA,
            "ritmoDias": RITMO_DIAS,
            "ritmoPicoMax": RITMO_PICO_MAX,
            "ritmoPicoMin": RITMO_PICO_MIN,
            "transacoesPorEditor": waze.TRANSACOES_POR_EDITOR,
            "semAtividade": sem_atividade,
        },
        # A lista crua de candidatos já virou painel; mandá-la de novo aqui
        # dobraria o peso dela sem ninguém ler. E `candidatosOmitidos` é a
        # contagem de quem está sob sanção: a página avisa que houve exclusão,
        # mas o número não entra no HTML — com o total do painel ao lado, ele
        # daria a proporção de sancionados da comunidade.
        "estat": {k: v for k, v in estat.items()
                  if k not in ("candidatos", "candidatosOmitidos")},
        "resumo": {
            "ativos30": ativos30,
            "ativos90": len(abas["d90"]),
            "historico": len(eds),
            "edicoesTotal": sum(e["tot"] for e in eds),
            "edicoes90": tot90,
            "concKpi": conc_kpi,
            "deltaFds": delta_fds,
            "retencao": retencao,
            "faixaRetencao": faixa,
            "safraLimite": limite_safra,
            "novos": sum(n for a, n, _ in entrada if a >= hoje.year - 1),
            "fator1": sum(1 for r in estados if r[3] == 1),
        },
        "paineis": {
            "semana": [[DIAS[i], semana[i]] for i in range(7)],
            "concentracao": concentracao,
            "entrada": entrada,
            "parados": parados,
            "estados": estados,
            "estadosInativos": estados_inativos,
            "evasao": evasao,
            "retornos": retornos,
            "niveis": niveis,
            "novatos": novatos[:10],
            "novatosTotal": len(novatos),
            "novatosVivos": novatos_vivos,
            "calendario": calendario,
            "calInicio": d0.weekday(),
            "calMediana": mediana,
            "mentoria": mentoria,
            "atividade": atividade,
            "forasteiros": forasteiros[:8],
            "candidatos": candidatos,
            "cobertura": cobertura,
            "mapa": _grade_cobertura(areas, ufs),
        },
    }


PAGE = r"""<!doctype html>
<html lang="pt-BR">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Placar dos Editores do Waze — Brasil</title>
<meta name="description" content="Placar dos editores de mapa do Waze no Brasil, remontado a partir da API pública. Atividade recente, não acumulado de carreira.">
<script>
// Antes do CSS pintar, de propósito: aplicado lá embaixo com o resto do script,
// a página abriria no tema do sistema e piscaria para o escolhido.
(function () {
  try {
    var t = localStorage.getItem("tema");
    if (t === "dark" || t === "light") document.documentElement.dataset.theme = t;
  } catch (e) {}          // navegador com storage bloqueado só fica no automático
})();
</script>
<style>
  :root {
    color-scheme: light;
    --page:#f6f8fa; --card:#fff; --ink:#12212e; --muted:#5b6b7a;
    --line:#e3e9ef; --chip:#eef3f7;
    --series:#2a78d6; --series-soft:#cde2fb; --tab-ativa:#1a62b8;
    --grid:#e1e0d9; --baseline:#c3c2b7; --axis:#898781;
    --up:#006300; --down:#d03b3b;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --page:#0d1519; --card:#141f26; --ink:#e6eef4; --muted:#8ba3b4;
      --line:#22323d; --chip:#1b2a33;
      --series:#3987e5; --series-soft:#1b3f55; --tab-ativa:#2a6fc4; --tab-ativa:#2a6fc4;
      --grid:#2c2c2a; --baseline:#383835; --axis:#898781;
      --up:#0ca30c; --down:#e86b66;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --page:#0d1519; --card:#141f26; --ink:#e6eef4; --muted:#8ba3b4;
    --line:#22323d; --chip:#1b2a33;
    --series:#3987e5; --series-soft:#1b3f55; --tab-ativa:#2a6fc4;
    --grid:#2c2c2a; --baseline:#383835; --axis:#898781;
    --up:#0ca30c; --down:#e86b66;
  }
  * { box-sizing:border-box }
  body { margin:0; background:var(--page); color:var(--ink);
         font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif }
  .wrap { max-width:1100px; margin:0 auto; padding:28px 18px 64px }
  h1 { font-size:1.6rem; margin:0 0 4px; letter-spacing:-.02em }
  h2 { font-size:.85rem; margin:0 0 14px; text-transform:uppercase;
       letter-spacing:.06em; color:var(--muted) }
  .sub { color:var(--muted); font-size:.9rem; margin:0 0 22px }

  .topo { display:flex; align-items:flex-start; justify-content:space-between;
          gap:12px }
  .tema { flex:none; background:var(--card); border:1px solid var(--line);
          color:var(--muted); border-radius:10px; padding:8px; cursor:pointer;
          line-height:0 }
  .tema:hover { color:var(--ink); border-color:var(--muted) }
  .tema svg { width:18px; height:18px; display:block }

  /* 200px porque o número é o conteúdo: em 160px um total de oito dígitos
     vazava da caixa em 390 e 768px. Com esta largura o auto-fit prefere
     quebrar em menos colunas a cortar o número. */
  .kpis { display:grid; gap:10px; margin-bottom:20px;
          grid-template-columns:repeat(auto-fit,minmax(200px,1fr)) }
  /* Na faixa em que o auto-fit daria três colunas, o quarto cartão fica órfão
     numa linha só dele. Duas colunas casadas ficam melhor e cabem folgadas. */
  @media (min-width:640px) and (max-width:880px) {
    .kpis { grid-template-columns:repeat(2,1fr) }
  }
  .kpi { background:var(--card); border:1px solid var(--line);
         border-radius:12px; padding:14px 16px }
  .kpi b { display:block; font-size:1.7rem; letter-spacing:-.02em; line-height:1.15 }
  .kpi span { color:var(--muted); font-size:.78rem }

  .tabs { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:14px }
  .tab { border:1px solid var(--line); background:var(--card); color:var(--muted);
         padding:8px 16px; border-radius:999px; cursor:pointer; font-size:.9rem;
         font-weight:600; font-family:inherit }
  .tab[aria-selected="true"] { background:var(--tab-ativa);
                               border-color:var(--tab-ativa); color:#fff }
  /* o contador da aba se distingue pelo peso, não por opacidade: esmaecer
     texto pequeno sobre azul derrubava o contraste para menos de 3:1 */
  .tab .conta { font-weight:400 }
  .controls { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px }
  input, select { background:var(--card); border:1px solid var(--line);
                  color:var(--ink); border-radius:8px; padding:8px 12px;
                  font-size:.9rem; font-family:inherit }
  input { flex:1; min-width:180px }

  .tablewrap { background:var(--card); border:1px solid var(--line);
               border-radius:12px; overflow-x:auto }
  table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums }
  th, td { padding:9px 12px; text-align:left; border-bottom:1px solid var(--line);
           white-space:nowrap }
  th { font-size:.72rem; text-transform:uppercase; letter-spacing:.06em;
       color:var(--muted); font-weight:600; position:sticky; top:0;
       background:var(--card); white-space:normal }
  tr:last-child td { border-bottom:none }
  tbody tr:nth-child(even) { background:color-mix(in srgb, var(--chip) 45%, transparent) }
  tbody tr:hover { background:color-mix(in srgb, var(--series) 8%, transparent) }
  td.num, th.num { text-align:right }
  .pos { color:var(--muted); width:46px }
  .name { font-weight:600; width:99%; white-space:normal; line-height:1.35;
          overflow-wrap:anywhere }
  .name .selos { display:flex; flex-wrap:wrap; gap:4px; margin-top:3px }
  .name a { color:inherit; text-decoration:none }
  .name a:hover, .name a:focus-visible { color:var(--series);
                                         text-decoration:underline }
  .chip { background:var(--chip); border-radius:5px; padding:1px 7px;
          font-size:.75rem; color:var(--muted); font-weight:600 }
  /* o que distingue o selo esmaecido é não ter fundo, não ser translúcido:
     com opacidade .5 o texto ficava em 2:1, ilegível para muita gente */
  .chip.fraco { background:transparent; color:var(--muted); font-weight:500 }
  .up { color:var(--up); font-weight:600 }
  .down { color:var(--down); font-weight:600 }
  .flat { color:var(--muted) }

  /* faísca: 15 baldes de 6 dias, ancorados na linha de base */
  .spark { display:flex; align-items:flex-end; gap:2px; height:22px;
           border-bottom:1px solid var(--baseline); padding-bottom:0 }
  .spark i { width:5px; background:var(--series); border-radius:2px 2px 0 0;
             display:block; min-height:1px }
  .spark i.zero { background:var(--grid); height:1px }

  .paineis { display:grid; gap:14px; margin-top:22px; align-items:start;
             grid-template-columns:repeat(auto-fit,minmax(320px,1fr)) }
  .painel { background:var(--card); border:1px solid var(--line);
            border-radius:12px; padding:16px 18px }
  .barra { display:grid; grid-template-columns:minmax(2.4rem,max-content) 1fr auto;
           gap:10px; align-items:center; margin:5px 0; font-size:.85rem }
  /* o rótulo cresce até um teto e então corta com reticências; o texto inteiro
     continua no title da barra. Sem isso, nome de cidade invade o gráfico.
     O `>` não é decoração: sem ele o seletor também pegava a barra azul, que é
     o primeiro filho do trilho, e travava todo gráfico em 8rem — acima de uns
     dois terços, valores diferentes desenhavam do mesmo tamanho. */
  .barra > span:first-child { color:var(--muted); max-width:8rem; white-space:nowrap;
                              overflow:hidden; text-overflow:ellipsis }
  .barra .t { background:var(--grid); border-radius:4px; height:9px }
  .barra .f { background:var(--series); border-radius:4px; height:9px;
              min-width:2px }
  .barra .v { color:var(--muted); font-variant-numeric:tabular-nums;
              font-size:.8rem }
  /* hierarquia por tamanho, não por opacidade — ver o comentário do chip */
  .barra .v .sec, .painel p .sec { font-size:.88em }
  .painel table { font-size:.85rem; width:100% }
  .painel td, .painel th { padding:5px 8px; border-bottom:1px solid var(--line);
                           white-space:normal }
  .painel td.num, .painel th.num { white-space:nowrap }
  .painel .rola { overflow-x:auto; margin:0 -4px; padding:0 4px }
  .painel td.quebra { white-space:normal; min-width:110px;
                      overflow-wrap:anywhere }
  @media (max-width:620px) { .painel td.quebra { min-width:0 } }
  @media (min-width:720px) { .painel.largo { grid-column:span 2 } }

  @media (max-width:560px) {
    .wrap { padding:20px 12px 48px }
    th, td { padding:8px 6px }
    .pos { width:26px }
    .medal { display:none }        /* a medalha alarga a coluna do posto */
    .chip { padding:1px 5px; font-size:.7rem }
  }
  /* Em vez de rolagem lateral, o que é secundário some conforme aperta. */
  @media (max-width:980px) { .c-hist { display:none } }
  @media (max-width:820px) { .c-seq  { display:none } }
  @media (max-width:660px) { .c-spark { display:none } }
  @media (max-width:520px) { .c-tend { display:none } }
  @media (max-width:620px) { .c-ativos { display:none } }

  /* Coleta sem perfis: faísca, sequência e tendência saem do vetor diário, que
     não foi coletado. Coluna vazia se leria como "não editou". Histórico sai
     junto porque sobra só a aba do acumulado, e ela repetiria "Edições". */
  body.sem-atividade .c-spark,
  body.sem-atividade .c-seq,
  body.sem-atividade .c-tend,
  body.sem-atividade .c-hist { display:none }

  /* duas listas lado a lado dentro de um painel largo; empilham no estreito */
  .duplo { display:grid; gap:18px 24px;
           grid-template-columns:repeat(auto-fit,minmax(300px,1fr)) }
  /* Lado a lado, cada metade fica com menos de um terço da largura da página.
     Medido: com quatro colunas a tabela pedia 395px numa célula de 321px e
     invadia a lista vizinha. Quem tem quatro colunas empilha e usa a largura
     inteira do painel. */
  .duplo.empilha { grid-template-columns:1fr }
  /* No celular nem a largura inteira do painel basta: a tabela pedia 389px em
     364px. Aperta o respiro das células e o teto do nome, em vez de rolar. */
  @media (max-width:560px) {
    .duplo.empilha td, .duplo.empilha th { padding:5px 4px }
    .duplo.empilha td:first-child a { max-width:5.5rem }
  }
  .duplo h3 { font-size:.78rem; margin:0 0 8px; text-transform:uppercase;
              letter-spacing:.05em; color:var(--muted); font-weight:600 }
  /* Nome longo empurrava a coluna de progresso para fora do painel, cortando
     o número. O nome trunca; o selo de UF e o progresso ficam sempre visíveis,
     e o nome inteiro continua no title da célula. */
  .duplo td:first-child { white-space:nowrap }
  .duplo td:first-child a { display:inline-block; max-width:7rem;
    overflow:hidden; text-overflow:ellipsis; vertical-align:bottom }

  /* régua: linha que não é gente. Sem link, sem selo, em versalete e com
     tracejado dos dois lados, para não ser lida como mais um editor. */
  tr.regua td { border-top:1px dashed var(--muted); border-bottom:1px dashed var(--muted);
                background:var(--chip); color:var(--muted);
                font-size:.72rem; letter-spacing:.05em; text-transform:uppercase;
                padding-top:5px; padding-bottom:5px }
  tr.regua td.name { font-weight:600 }
  tr.regua td.num { font-variant-numeric:tabular-nums }

  .resto { display:flex; gap:12px; align-items:center; flex-wrap:wrap;
           margin:10px 2px 0; color:var(--muted); font-size:.82rem }
  .resto button { background:var(--card); border:1px solid var(--line);
                  color:var(--ink); border-radius:8px; padding:6px 14px;
                  cursor:pointer; font-size:.82rem; font-weight:600;
                  font-family:inherit }
  .resto button:hover { border-color:var(--muted) }

  footer { margin-top:24px; color:var(--muted); font-size:.8rem }
  footer p { margin:.45em 0 }
  code { background:var(--chip); padding:1px 5px; border-radius:4px; font-size:.9em }
  .empty { padding:28px; text-align:center; color:var(--muted) }
</style>

<div class="wrap">
  <div class="topo">
    <div>
      <h1>Placar dos Editores do Waze</h1>
      <p class="sub" id="sub"></p>
    </div>
    <button type="button" class="tema" id="tema"></button>
  </div>

  <div class="kpis" id="kpis"></div>

  <div class="tabs" id="tabs" role="tablist" aria-label="Janela de tempo"></div>
  <div class="controls">
    <input id="q" type="search" placeholder="Procurar editor…" autocomplete="off"
           aria-label="Procurar editor pelo nome">
    <select id="uf" aria-label="Filtrar por estado"></select>
  </div>

  <div class="tablewrap" id="painelTabela" role="tabpanel"
       aria-label="Classificação dos editores">
    <table>
      <thead><tr>
        <th class="pos" id="thPos">#</th><th id="thEditor">Editor</th>
        <th class="c-spark" id="thSpark"></th>
        <th class="num" id="thJanela">Edições</th>
        <th class="num c-seq" id="thSeq">Seq.</th>
        <th class="num c-tend" id="thTend">Tend.</th>
        <th class="num c-hist" id="thHist">Histórico</th>
      </tr></thead>
      <tbody id="body"></tbody>
    </table>
    <div class="empty" id="empty" hidden>Nenhum editor encontrado.</div>
  </div>
  <div class="resto" id="resto" hidden>
    <span id="restoTexto"></span>
    <button type="button" id="verTudo">Mostrar todos</button>
  </div>

  <div class="paineis" id="paineis"></div>

  <footer>
    <p><b>De onde vem.</b> A lista de editores sai de <span id="fRank"></span>
    rankings do Waze: os <span id="fQuad"></span> quadros — o nacional e os
    <span id="fUf"></span> estaduais — em cada uma das
    <span id="fJan"></span> janelas que a API oferece, <span id="fCap"></span>
    linhas cada. Todas as janelas entram porque o ranking histórico ordena por
    pontos acumulados: nesta coleta, <span id="fGap"></span> dos editores
    ativos não apareceriam se só ele fosse varrido. A atividade diária vem do perfil de
    cada editor, que expõe os últimos <span id="fVet"></span> dias. Como os
    rankings estaduais não se sobrepõem, a UF de cada um vem da varredura.</p>
    <p><b>Por que ordenar por atividade.</b> Os rankings do Waze ordenam por
    pontos — dirigir e editar somados — e cortam em <span id="fCap2"></span>
    linhas. Como o critério não separa dirigir de editar,
    <span id="fZero"></span> das linhas dos rankings de janela são de quem não
    fez nenhuma edição no período. Ordenando pelas edições reais da janela
    escolhida, o placar mostra quem está construindo o mapa agora, e não quem
    acumulou mais desde <span id="fAno"></span>.</p>
    <p><b>Tendência</b> compara os segundos <span id="fMeta"></span> dias com os
    primeiros <span id="fMeta2"></span>, e só
    aparece para quem tem volume suficiente no período. <b>Seq.</b> é o número de
    dias consecutivos editando, sem contar hoje, que está em andamento.</p>
    <p>Clique no nome para abrir o perfil do editor no Waze. Dados de
    <code>www.waze.com</code>. Página estática, sem servidor e sem banco.</p>
  </footer>
</div>

<script>
const D = __DATA__;
const NF = new Intl.NumberFormat("pt-BR");
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);
const perfil = (u) => "https://www.waze.com/user/editor/" + encodeURIComponent(u);
const $ = (id) => document.getElementById(id);

// --- tema -----------------------------------------------------------------
// Sem escolha gravada a página segue o sistema, que é o que o CSS já faz. O
// botão só fixa a escolha em data-theme, e o CSS cuida do resto.
const ICONE = {
  sol: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2M12 19.5v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2.5 12h2M19.5 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/></svg>',
  lua: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
};

const estaEscuro = () => document.documentElement.dataset.theme
  ? document.documentElement.dataset.theme === "dark"
  : matchMedia("(prefers-color-scheme: dark)").matches;

function pintaBotaoTema() {
  const b = $("tema");
  if (!b) return;
  const escuro = estaEscuro();
  // o ícone mostra para onde o clique leva, não onde a página está
  b.innerHTML = escuro ? ICONE.sol : ICONE.lua;
  const rot = escuro ? "Mudar para o tema claro" : "Mudar para o tema escuro";
  b.title = rot;
  b.setAttribute("aria-label", rot);
}

function ligaTema() {
  const b = $("tema");
  if (!b) return;
  b.onclick = () => {
    const novo = estaEscuro() ? "light" : "dark";
    document.documentElement.dataset.theme = novo;
    try { localStorage.setItem("tema", novo); } catch (e) {}
    pintaBotaoTema();
  };
  // enquanto ninguém escolheu, acompanha o sistema mudando ao vivo
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (!document.documentElement.dataset.theme) pintaBotaoTema();
  });
  pintaBotaoTema();
}

// Toda a ajuda de hover num lugar só, para poder ser lida e revisada de uma vez.
// Nenhum número aqui é escrito à mão: todos saem do cfg, que sai das constantes
// do pagina.py. Mudar um limiar lá muda a explicação aqui.
const C = D.cfg;
const AJUDA = {
  pos: "Posição nesta aba, ou dentro do estado quando há um filtrado — o estado é um recorte e tem classificação própria. Procurar um nome não renumera nada: a busca acha a pessoa e mostra a posição que ela já tinha. Como cada aba ordena por uma janela diferente, a mesma pessoa aparece em posições diferentes de uma para outra.",
  editor: "Nome no Waze. Clique para abrir o perfil. Logo abaixo vêm o estado, o nível e os selos.",
  janela: {
    d30: `Edições feitas nos últimos ${C.janelaMedia} dias fechados.`,
    d7: `Edições feitas nos últimos ${C.janelaCurta} dias fechados.`,
    d90: `Edições feitas nos últimos ${C.janela} dias fechados.`,
    tot: "Total de edições desde a primeira, em toda a carreira.",
  },
  janelaExtra: " Vem do histórico diário do perfil; o dia de hoje, que ainda está correndo, fica de fora da soma.",
  faisca: `Formato da atividade nos últimos ${C.janela} dias, em ${C.baldes} blocos de ${C.baldeDias} dias, do mais antigo ao mais recente. A altura é relativa ao melhor bloco da própria pessoa — serve para ver o ritmo dela, não para comparar com outra.`,
  seq: "Dias seguidos com pelo menos uma edição, contados de trás para frente. Hoje não entra, porque o dia ainda não fechou.",
  tend: `Compara o total dos últimos ${C.meta} dias com o dos ${C.meta} anteriores. Fica em branco para quem editou pouco no período, onde a razão diria mais sobre o acaso que sobre a pessoa.`,
  tot: "Total de edições da carreira inteira. Não muda conforme a aba escolhida.",
  uf: "Estado do editor, deduzido de qual ranking estadual ele aparece. Os rankings estaduais não se sobrepõem.",
  nivel: "Nível de editor no Waze. Sobe com experiência e dá mais permissões no editor de mapas.",
  regua: {
    mediana: "Linha de referência, não é um editor. Metade da lista fez mais edições que isto, metade fez menos. Acompanha o filtro de estado — o rótulo ao lado diz sobre quem ela está falando — e não muda com a busca, para você poder procurar seu nome e se comparar com ela.",
    media: "Linha de referência, não é um editor. É a soma das edições da lista dividida pelo número de editores. Acompanha o filtro de estado — o rótulo ao lado diz sobre quem ela está falando — e não muda com a busca, para você poder procurar seu nome e se comparar com ela.",
  },
  kpi: {
    ativos: `Quantas pessoas fizeram ao menos uma edição nos últimos ${C.janelaMedia} dias. A aba Histórico traz mais gente: lá entra também quem editou uma vez, anos atrás, e nunca voltou.`,
    edicoes: `Soma de todas as edições feitas no Brasil nos últimos ${C.janela} dias, por todos os editores que o placar acompanha.`,
    conc: `Fatia das edições dos últimos ${C.janela} dias que vem dos ${C.concKpiN} editores mais produtivos. Quanto mais alto, mais o mapa depende de pouca gente.`,
    universo: "Quantos editores os rankings devolveram. É o universo inteiro que o placar enxerga, sem recorte de janela.",
    carreiras: "Soma do total de carreira de todos esses editores. Cobre desde a primeira edição de cada um, sem recorte de janela.",
    fator1: "Estados em que um único editor responde por mais da metade das edições da janela. Quanto do mapa do estado saiu da mão de uma pessoa só.",
  },
};

// [chave, rótulo, índice da coluna em D.editores]
const ABAS = [
  ["d30", C.janelaMedia + " dias", 5], ["d7", C.janelaCurta + " dias", 4],
  ["d90", C.janela + " dias", 6], ["tot", "Histórico", 3],
];
let aba = "d30";

// [u, uf, lvl, tot, d7, d30, d90, streak, tend, semanas, mentees]
const col = () => ABAS.find((a) => a[0] === aba)[2];

// Os dois controles não fazem a mesma coisa, e a diferença é o que a posição e
// as réguas seguem.
//
// O estado troca o recorte: filtrar a Bahia é pedir o placar da Bahia, e ali
// ser o segundo é ser o segundo. Renumerar é o certo.
//
// A busca não troca recorte nenhum — é procurar alguém dentro do que já está
// escolhido. Renumerando ali, quem é o 30º da aba se via como "#1" ao digitar
// o próprio nome. Por isso a posição e as réguas saem do escopo, e a busca só
// esconde as linhas que não casam.
function escopoLista() {
  const uf = $("uf").value;
  return D.abas[aba]
    .map((i) => D.editores[i])
    .filter((e) => !uf || e[1] === uf);
}

function linhas() {
  const q = $("q").value.trim().toLowerCase();
  return escopoLista()
    .map((e, n) => [e, n + 1])
    .filter(([e]) => !q || e[0].toLowerCase().includes(q));
}

// De quem as réguas estão falando. Com um estado filtrado, dizer "desta aba"
// seria falso — o valor é o daquele estado.
function escopo() {
  const uf = $("uf").value;
  return uf ? "de " + uf : "desta aba";
}

function faisca(sem) {
  if (!sem) return "";
  const max = Math.max(...sem) || 1;
  const barras = sem.map((v) => {
    if (!v) return '<i class="zero"></i>';
    const h = Math.max(2, Math.round((v / max) * 22));
    return `<i style="height:${h}px"></i>`;
  }).join("");
  return `<div class="spark" title="Edições por período de 6 dias, do mais antigo ao mais recente. Pico: ${NF.format(max)}">${barras}</div>`;
}

// [.. 11=especialidade, 12=ritmo, 10=afilhados, 13=áreas]
function selos(e) {
  const s = [];
  // esmaece a especialidade mais comum da aba para as outras saltarem.
  if (e[11]) s.push(`<span class="chip${e[11] === D.tipoComum[aba] ? " fraco" : ""}"
    title="Especialidade: ${esc(e[11])} é o tipo de edição que mais fez na carreira. Sai esmaecido quando é o tipo mais comum entre os editores desta aba."
    >${esc(e[11])}</span>`);
  if (e[12]) s.push(`<span class="chip"
    title="${e[12] === "constante"
      ? `Ritmo constante: editou em ${C.ritmoDias} ou mais dos últimos ${C.janela} dias, e nenhum dia isolado passa de ${C.ritmoPicoMax}% do total — produção espalhada, sem depender de um dia só.`
      : `Ritmo explosivo: um único dia responde por ${C.ritmoPicoMin}% ou mais de tudo que fez em ${C.janela} dias.`}"
    >${e[12]}</span>`);
  if (e[10]) s.push(`<span class="chip"
    title="Mentor de ${e[10]} editor(es) novo(s) no Waze."
    >mentor</span>`);
  if (e[13]) s.push(`<span class="chip"
    title="Area Manager: tem responsabilidade formal sobre ${e[13]} área(s) do mapa."
    >AM</span>`);
  return s.join(" ");
}

function tend(t) {
  const cap = (txt) => ' title="' + txt + '"';
  if (t === null || t === undefined) {
    return '<span class="flat"' + cap("Editou pouco demais no período para a comparação significar algo.") + ">—</span>";
  }
  if (t >= 999) {
    return '<span class="up"' + cap(`Não tinha nenhuma atividade nos primeiros ${C.meta} dias da janela: começou ou voltou a editar na segunda metade.`) + ">↑ novo</span>";
  }
  if (t > C.tendBanda) {
    return '<span class="up"' + cap(`Fez ${t}% mais edições nos últimos ${C.meta} dias do que nos ${C.meta} anteriores.`) + ">↑ " + t + "%</span>";
  }
  if (t < -C.tendBanda) {
    return '<span class="down"' + cap(`Fez ${Math.abs(t)}% menos edições nos últimos ${C.meta} dias do que nos ${C.meta} anteriores.`) + ">↓ " + Math.abs(t) + "%</span>";
  }
  return '<span class="flat"' + cap(`Ritmo estável: a variação entre as metades da janela ficou dentro de ${C.tendBanda}%.`) + ">→</span>";
}

// Réguas dentro da tabela: onde cai o editor típico e onde cai a média.
// As duas porque a distância entre elas é a própria concentração — numa
// distribuição torta a média sobe muito acima do meio da lista, e quem só
// visse a média concluiria que quase todo mundo produz pouco.
// O valor sai do escopo — filtrou um estado, a régua é a daquele estado —, e a
// busca não mexe nele: procurar o próprio nome é justamente para se comparar
// com a régua, e uma régua calculada sobre o resultado da busca compararia a
// pessoa consigo mesma. Somem quando o escopo tem pouca gente para o valor
// significar algo.
function reguas(escopoDe, visiveis, c) {
  if (escopoDe.length < C.refMin) return {};
  const v = escopoDe.map((e) => e[c]);
  const ord = v.slice().sort((a, b) => a - b);
  const mediana = ord[Math.floor(ord.length / 2)];
  const media = v.reduce((s, x) => s + x, 0) / v.length;
  // a lista já vem em ordem decrescente: a régua entra antes do primeiro
  // registro que fica abaixo dela — e o lugar é entre o que está na tela
  const vis = visiveis.map(([e]) => e[c]);
  const onde = (lista, x) => {
    const i = lista.findIndex((y) => y < x);
    return i < 0 ? lista.length : i;
  };
  const r = {};
  // Além do lugar entre o que está na tela, vai a posição no escopo: é o que a
  // régua diz quando o desenho para antes de ela chegar.
  const põe = (rot, x, ajuda) => {
    const i = onde(vis, x);
    (r[i] = r[i] || []).push([rot, Math.round(x), ajuda, onde(v, x) + 1]);
  };
  põe("média", media, AJUDA.regua.media);
  põe("mediana", mediana, AJUDA.regua.mediana);
  return r;
}

function linhaRegua(rot, valor, ajuda, pos, presa) {
  // Presa = a régua cairia abaixo do pedaço desenhado. Em vez de sumir, ela
  // encosta no fim do que está na tela e diz em que posição fica de verdade.
  const onde = presa ? " · " + NF.format(pos) + "ª posição" : "";
  const extra = presa
    ? " Fica na " + NF.format(pos) + "ª posição, abaixo do pedaço desenhado."
    : "";
  return `<tr class="regua" title="${ajuda}${extra}">
      <td class="pos"></td>
      <td class="name">${rot} ${escopo()}${onde}</td>
      <td class="c-spark"></td>
      <td class="num">${NF.format(valor)}</td>
      <td class="num c-seq"></td>
      <td class="num c-tend"></td>
      <td class="num c-hist"></td>
    </tr>`;
}

// Só o pedaço que cabe na tela de uma vez. O resto continua na busca e no
// filtro — o corte é de desenho, não de dados.
let mostrarTudo = false;

function render() {
  const todas = linhas();
  const corta = !mostrarTudo && todas.length > C.linhasMax;
  const lista = corta ? todas.slice(0, C.linhasMax) : todas;
  const c = col();
  const reg = reguas(escopoLista(), todas, c);
  // Régua que cai além do pedaço desenhado não pode simplesmente sumir. No
  // Histórico inteiro a mediana fica lá pela metade da lista, e a página
  // passava a mostrar só a média — que numa distribuição torta é exatamente a
  // leitura que as duas réguas existem para evitar. Presas no fim do desenho,
  // com a posição real escrita ao lado.
  if (corta) {
    const presas = [];
    for (const k of Object.keys(reg)) {
      if (+k >= lista.length) {
        presas.push(...reg[k].map((r) => r.concat([true])));
        delete reg[k];
      }
    }
    if (presas.length) reg[lista.length] = presas;
  }
  const antes = (n) => (reg[n] || []).map((r) => linhaRegua(...r)).join("");
  $("body").innerHTML = lista.map(([e, pos], n) => `${antes(n)}<tr>
      <td class="pos">${pos}</td>
      <td class="name"><a href="${esc(perfil(e[0]))}" target="_blank"
         rel="noopener noreferrer" title="Ver perfil de ${esc(e[0])} no Waze"
         >${esc(e[0])}</a>
        <span class="selos"><span class="chip" title="${AJUDA.uf}"
          >${e[1] || "--"}</span>${e[2]
          ? `<span class="chip" title="${AJUDA.nivel}">N${e[2]}</span>` : ""
          }${selos(e)}</span></td>
      <td class="c-spark">${faisca(e[9])}</td>
      <td class="num">${NF.format(e[c])}</td>
      <td class="num c-seq" title="${e[7] ? e[7] + " dia(s) seguidos editando" : "Não está numa sequência"}">${e[7] || ""}</td>
      <td class="num c-tend">${tend(e[8])}</td>
      <td class="num c-hist" title="${NF.format(e[3])} edições desde a primeira">${NF.format(e[3])}</td>
    </tr>`).join("") + antes(lista.length);
  $("resto").hidden = !corta;
  if (corta) {
    $("restoTexto").textContent = "Mostrando " + NF.format(lista.length) +
      " de " + NF.format(todas.length) + " editores. A busca e o filtro de " +
      "estado procuram em todos.";
  }
  $("empty").hidden = todas.length > 0;
  $("thJanela").textContent =
    aba === "tot" ? "Edições" : "Edições · " + ABAS.find((a) => a[0] === aba)[1]
      .replace(" dias", "d");
  $("thJanela").title = AJUDA.janela[aba] + (aba === "tot" ? "" : AJUDA.janelaExtra);
}

function barras(itens, fmt, ajuda) {
  const max = Math.max(...itens.map((i) => i[1])) || 1;
  return itens.map(([k, v]) => {
    const t = ajuda ? ' title="' + esc(ajuda(k, v)) + '"' : "";
    return `<div class="barra"${t}>
      <span>${esc(k)}</span>
      <span class="t"><span class="f" style="width:${Math.max(1, (v / max) * 100)}%;display:block"></span></span>
      <span class="v">${fmt(v)}</span>
    </div>`;
  }).join("");
}

function link(u) {
  return `<a href="${esc(perfil(u))}" target="_blank" rel="noopener noreferrer"
     style="color:inherit">${esc(u)}</a>`;
}

function calendario(p) {
  const dias = p.calendario;
  if (!dias.length) return "";
  const max = Math.max(...dias.map((d) => d[1])) || 1;
  const SEM = Math.ceil((dias.length + p.calInicio) / 7);
  const L = 13, G = 3;                      // lado da célula e respiro
  const celulas = dias.map(([iso, v, fora], i) => {
    const pos = i + p.calInicio;
    const x = Math.floor(pos / 7) * (L + G), y = (pos % 7) * (L + G);
    const o = v ? Math.max(0.12, v / max) : 0;
    const anel = fora
      ? `<rect x="${x - 1}" y="${y - 1}" width="${L + 2}" height="${L + 2}" rx="3"
           fill="none" stroke="var(${fora > 0 ? "--up" : "--down"})" stroke-width="1.5"/>`
      : "";
    return `<rect x="${x}" y="${y}" width="${L}" height="${L}" rx="2.5"
        fill="var(--series)" fill-opacity="${o.toFixed(3)}"
        ><title>${iso}: ${NF.format(v)} edições${
          fora > 0 ? " (acima da curva)" : fora < 0 ? " (abaixo da curva)" : ""
        }</title></rect>${anel}`;
  }).join("");
  const rotulos = [0, 2, 4, 6].map((d) =>
    `<text x="-5" y="${d * (L + G) + L - 3.5}" text-anchor="end" font-size="6.5"
       fill="var(--axis)">${["seg","ter","qua","qui","sex","sáb","dom"][d]}</text>`).join("");
  const destaque = dias.filter((d) => d[2]);

  return `<div class="painel largo"><h2>Calendário de edições</h2>
    <div style="overflow:visible">
    <svg viewBox="-20 -4 ${SEM * (L + G) + 24} ${7 * (L + G) + 8}"
         style="width:100%;max-width:640px;height:auto" role="img"
         aria-label="Calendário de edições diárias nos últimos ${D.cfg.janela} dias">
      ${rotulos}${celulas}
    </svg></div>
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    Cada quadrado é um dia; a intensidade é o total de edições do país.
    A mediana diária é <b>${NF.format(p.calMediana)}</b>.
    ${destaque.length
      ? `Contornados, os <b>${destaque.length}</b> dias que fogem
         ${D.cfg.calDesvios} desvios da mediana — ${destaque.map((d) => (d[2] > 0 ? "↑" : "↓") + " " +
           d[0].slice(8, 10) + "/" + d[0].slice(5, 7)).join(", ")}.
         O que causou cada um não sai daqui.`
      : `Nenhum dia foge ${D.cfg.calDesvios} desvios da mediana no período.`}
    </p></div>`;
}

// Mesma projeção e mesmo passo do mapa de cobertura, de propósito: um diz onde
// alguém tem responsabilidade formal, o outro onde a mão encostou de verdade.
function mapaAtividade(a) {
  if (!a.celulas.length) return "";
  const FAIXAS = [[8, 1, "8 ou mais"], [4, .74, "4 a 7"],
                  [2, .5, "2 a 3"], [1, .28, "1"]];
  const cor = (n) => (FAIXAS.find((f) => n >= f[0]) || FAIXAS[3])[1];
  const cells = a.celulas.map(([i, j, n]) =>
    `<rect x="${i}" y="${a.ny - 1 - j}" width="1" height="1"
       fill="var(--series)" fill-opacity="${cor(n)}"><title>${n} edição(ões)</title></rect>`
  ).join("");
  let grade = "";
  for (let g = 10; g < a.nx; g += 20)
    grade += `<line x1="${g}" y1="0" x2="${g}" y2="${a.ny}" stroke="var(--grid)" stroke-width=".35"/>`;
  for (let g = 10; g < a.ny; g += 20)
    grade += `<line x1="0" y1="${g}" x2="${a.nx}" y2="${g}" stroke="var(--grid)" stroke-width=".35"/>`;
  const legenda = FAIXAS.slice().reverse().map(([n, o, rot]) =>
    `<span style="display:inline-flex;align-items:center;gap:5px;margin-right:12px">
       <span style="width:12px;height:12px;border-radius:3px;background:var(--series);
                    opacity:${o};display:inline-block"></span>${rot}</span>`).join("");

  return `<div class="painel" style="grid-column:1/-1"><h2>Onde se edita agora</h2>
    <svg viewBox="0 0 ${a.nx} ${a.ny}" style="width:100%;max-width:520px;height:auto;
         display:block;margin:0 auto" shape-rendering="crispEdges" role="img"
         aria-label="Mapa das edições mais recentes no Brasil">${grade}${cells}</svg>
    <p style="margin:12px 0 0;font-size:.8rem;color:var(--muted)">${legenda}</p>
    <p style="color:var(--muted);font-size:.8rem;margin:8px 0 0">
      As <b>${NF.format(a.edicoes)}</b> edições mais recentes de
      ${NF.format(a.editores)} editores — a API devolve as
      ${D.cfg.transacoesPorEditor} últimas de cada um, e ficam só as dos
      últimos ${D.cfg.janela} dias.${a.descartadas
        ? ` Outras ${NF.format(a.descartadas)} eram mais antigas que isso e
            saíram da conta.` : ""}
      Mesma grade do mapa de cobertura, para comparar: lá é onde há gerente,
      aqui é onde a mão encostou.
      ${a.fora ? NF.format(a.fora) + " ficaram fora do recorte do Brasil." : ""}
    </p></div>`;
}

function cidadesEtipos(a) {
  if (!a.edicoes) return "";
  const totTipos = a.tipos.reduce((s, [, v]) => s + v, 0) || 1;
  const ROT = { MapUpdateRequest: "pedido", Segment: "segmento",
    Venue: "local", Node: "nó", PermanentHazard: "alerta fixo",
    Street: "via", HouseNumber: "numeração", RoadClosure: "bloqueio",
    MapCorrection: "correção", SegmentSuggestion: "sugestão de via",
    Camera: "câmera", MapComment: "comentário", BigJunction: "entroncamento",
    RoutingPreference: "preferência de rota" };
  return `<div class="painel"><h2>Cidades mais editadas</h2>
    ${barras(a.cidades.map(([c, n]) => [c, n]), (v) => NF.format(v),
      (k, v) => v + " das edições recentes coletadas caíram em " + k + ".")}
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    O Waze só nomeia a cidade em ${Math.round(100 * a.comCidade / a.edicoes)}% das
    edições; as demais entram no mapa mas não nesta lista.</p></div>
    <div class="painel"><h2>O que está sendo mexido</h2>
    ${(() => {
      // arredondar para zero um tipo que existe deixava barra desenhada com
      // rótulo "0%", que parece defeito; abaixo de meio ponto o texto vira "<1%"
      const pc = (v) => { const x = 100 * v / totTipos;
        return x > 0 && x < 1 ? "<1%" : Math.round(x) + "%"; };
      return barras(a.tipos.slice(0, 8).map(([k, v]) => [ROT[k] || k, v]), pc,
        (k, v) => NF.format(v) + " operações do tipo " + k + ", que é " +
                  pc(v) + " de tudo que foi tocado nas edições recentes.");
    })()}
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    Operações das edições recentes, por tipo de objeto tocado. É o trabalho dos
    últimos dias, não o acumulado de carreira que aparece nos selos da
    tabela.</p></div>`;
}

function mapa(m) {
  if (!m.celulas.length) return "";
  // O topo da escala é o máximo de gerentes numa célula NESTA coleta — dinâmico,
  // não um balde fixo. O antigo "5+" achatava tudo de 5 ao máximo num tom só, e
  // mais da metade das células caía ali. Curva de raiz porque a distribuição
  // concentra no meio: linear jogaria a mediana no quase-invisível.
  const max = m.celulas.reduce((a, c) => Math.max(a, c[2]), 1);
  const op = (n) => max <= 1 ? 1 : 0.12 + 0.88 * Math.sqrt((n - 1) / (max - 1));
  const cells = m.celulas.map(([i, j, n]) =>
    `<rect x="${i}" y="${m.ny - 1 - j}" width="1" height="1"
       fill="var(--series)" fill-opacity="${op(n).toFixed(3)}"><title>${n} gerente(s)</title></rect>`
  ).join("");
  // Retículas a cada 10° dão referência sem inventar geografia.
  let grade = "";
  for (let g = 10; g < m.nx; g += 20)
    grade += `<line x1="${g}" y1="0" x2="${g}" y2="${m.ny}"
      stroke="var(--grid)" stroke-width=".35"/>`;
  for (let g = 10; g < m.ny; g += 20)
    grade += `<line x1="0" y1="${g}" x2="${m.nx}" y2="${g}"
      stroke="var(--grid)" stroke-width=".35"/>`;
  // Legenda contínua: a mesma cor e a mesma curva das células, amostradas em
  // stops, com os extremos rotulados — um (mais claro) e o máximo medido.
  const stops = [0, .2, .4, .6, .8, 1].map((t) =>
    `<stop offset="${t}" stop-color="var(--series)"
       stop-opacity="${op(1 + t * (max - 1)).toFixed(3)}"/>`).join("");
  const legenda = `<span style="display:inline-flex;align-items:center;gap:8px">
      <span style="color:var(--muted)">1</span>
      <svg width="180" height="12" style="display:block" aria-hidden="true">
        <defs><linearGradient id="cbar">${stops}</linearGradient></defs>
        <rect width="180" height="12" rx="3" fill="url(#cbar)"/>
      </svg>
      <span style="color:var(--muted)">${NF.format(max)} gerentes</span></span>`;

  return `<div class="painel" style="grid-column:1/-1">
    <h2>Cobertura de gerentes</h2>
    <svg viewBox="0 0 ${m.nx} ${m.ny}" style="width:100%;max-width:520px;
         height:auto;display:block;margin:0 auto" shape-rendering="crispEdges"
         role="img" aria-label="Mapa de cobertura de gerentes de área no Brasil">
      ${grade}${cells}
    </svg>
    <p style="margin:12px 0 0;font-size:.8rem;color:var(--muted)">${legenda}</p>
    <p style="color:var(--muted);font-size:.8rem;margin:8px 0 0">
      ${NF.format(m.editores)} dos editores ativos gerenciam
      ${NF.format(m.areas)} áreas. Cada quadrado tem ${String(D.cfg.celulaGrau).replace(".", ",")}° de lado
      (~${D.cfg.celulaKm} km) e a cor vai do mais claro (um gerente) ao mais
      escuro (${NF.format(max)}, o máximo nesta coleta); onde não há quadrado,
      nenhum editor ativo gerencia. Projeção simples por latitude e longitude,
      sem contorno político — é um esboço de cobertura, não um mapa.
      ${m.fora ? NF.format(m.fora) + " editores gerenciam áreas fora do Brasil, não desenhadas." : ""}
    </p></div>`;
}

// Quem o placar alcança, e por onde. Existe porque a pergunta mais comum de
// quem não se acha na lista é "por que eu não estou aqui?", e a resposta é
// medível: o ranking do Waze ordena por pontos, corta num teto fixo, e quem
// edita muito sem pontuar fica abaixo do corte. O painel não estima quantos
// são — a fonte não consegue mostrar quem ela esconde. Mostra o que dá para
// medir: quanto os endpoints fora do ranking acrescentaram.
function alcance(c) {
  if (!c || !c.universo) return "";
  const itens = [
    ["rankings", c.porRanking],
    ["novatos", c.novatos],
    ["candidatos", c.candidatos],
  ].filter(([, v]) => v > 0);
  const foraDoRanking = c.novatos + c.candidatos;
  const pctFora = Math.round(100 * foraDoRanking / c.universo);
  return `<div class="painel largo"><h2>Alcance da coleta</h2>
    ${barras(itens, (v) => NF.format(v), (k, v) =>
      NF.format(v) + " editores entraram no placar por " + k + ".")}
    <p style="color:var(--muted);font-size:.8rem;margin:12px 0 0">
    O universo tem <b>${NF.format(c.universo)}</b> editores${
      c.perfis && c.perfis !== c.universo
        ? `, dos quais <b>${NF.format(c.perfis)}</b> tiveram o perfil lido` : ""}.
    ${foraDoRanking
      ? `<b>${NF.format(foraDoRanking)}</b> deles — ${pctFora}% — não apareciam
         em ranking nenhum e entraram pela lista de novatos ou pela de
         candidatos a subir de nível.`
      : "Nesta coleta todos apareciam em algum ranking; as listas de novatos e de candidatos não trouxeram ninguém novo."}${
      c.linhasJanela ? ` As varreduras das janelas curtas
    leram <b>${NF.format(c.linhasJanela)}</b> linhas e devolveram
    <b>${NF.format(c.ativosJanela)}</b> editores com alguma edição:
    ${c.semEdicaoPct}% das linhas são de quem não editou no período, porque o
    ranking do Waze ordena por pontos, que somam dirigir e editar.
    Lendo depois o perfil de cada um do universo, o placar acha
    <b>${NF.format(D.resumo.ativos30)}</b> com edição nos últimos
    ${D.cfg.janelaMedia} dias e <b>${NF.format(D.resumo.ativos90)}</b> nos
    últimos ${D.cfg.janela} — é a diferença entre o que o ranking mostra e o
    que a coleta mede.` : ""}</p>
    <p style="color:var(--muted);font-size:.8rem;margin:8px 0 0">
    Por isso <b>o placar não é um censo</b>. Cada quadro do Waze corta em
    ${NF.format(D.cfg.cap)} linhas e não pagina, então quem edita muito e
    pontua pouco fica abaixo do corte em todos os
    ${NF.format(D.cfg.rankings)} — e só entra aqui se algum dos outros
    endpoints o alcançar. Quantos são não dá para dizer: a fonte não mostra
    quem ela não lista.</p></div>`;
}

function paineis() {
  const p = D.paineis;
  const blocos = [];

  // Sem vetor diário nenhum painel tem o que medir: todos recortam por janela,
  // por data de estreia ou por área, e nada disso foi coletado. Mostrar os
  // painéis zerados diria "não aconteceu" onde o certo é "não foi medido".
  if (D.cfg.semAtividade) {
    $("paineis").innerHTML = `<div class="painel largo aviso"><h2>Só o acumulado</h2>
      <p style="color:var(--muted);font-size:.85rem;margin:0">
      Esta execução leu os ${NF.format(D.cfg.rankings)} rankings mas não buscou
      o perfil de ninguém, então não existe histórico diário — e é dele que
      saem as janelas de atividade, as estreias e todos os painéis. A tabela
      acima é o ranking acumulado, a única coisa que esta coleta mediu.</p></div>`;
    return;
  }

  blocos.push(`<div class="painel largo"><h2>Estados e fator de ônibus</h2>
    <table><thead><tr>
    <th title="Sigla do estado, deduzida de qual ranking estadual os editores aparecem.">UF</th>
    <th class="num" title="Total de edições feitas no estado nos últimos ${D.cfg.janela} dias.">Edições</th>
    <th class="num c-ativos" title="Editores do estado com ao menos uma edição nos últimos ${D.cfg.janela} dias.">Ativos</th>
    <th class="num" title="Fator de ônibus: quantos editores precisariam parar para o estado perder metade das edições. Fator 1 é o pior caso — uma só pessoa segura mais da metade.">Fator</th>
    <th title="Quem mais produziu no estado, e a fatia do total que veio dessa pessoa.">Maior editor</th>
    </tr></thead><tbody>
    ${p.estados.map(([uf, ed, n, fator, topo, pct]) => `<tr>
       <td><span class="chip">${uf}</span></td>
       <td class="num" title="${NF.format(ed)} edições em ${D.cfg.janela} dias, de ${n} editor(es) ativo(s)">${NF.format(ed)}</td>
       <td class="num c-ativos">${n}</td>
       <td class="num ${fator === 1 ? "down" : ""}" title="${fator === 1
         ? "Fator 1: " + topo + " sozinho responde por " + pct + "% das edições de " + uf + "."
         : "Precisam parar " + fator + " editores para " + uf + " perder metade das edições."}">${fator}</td>
       <td class="quebra">${link(topo)}
         <span style="color:var(--muted)">${pct}%</span></td>
      </tr>`).join("")}
    ${p.estadosInativos.map((uf) => `<tr>
       <td><span class="chip">${uf}</span></td>
       <td colspan="4" style="color:var(--muted)">sem atividade na janela</td>
      </tr>`).join("")}
    </tbody></table>
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    <b>Fator</b> é quantos editores precisariam parar para o estado perder
    metade das edições. Fator 1 significa que um único editor responde por
    mais da metade — ${NF.format(D.resumo.fator1)} estados estão nessa
    situação.${p.estadosInativos.length
      ? " As UFs ao final não registraram nenhuma edição na janela."
      : ""}</p></div>`);

  blocos.push(`<div class="painel"><h2>Concentração</h2>
    ${barras(p.concentracao.map(([n, pc]) => ["top " + n, pc]), (v) => NF.format(v) + "%",
      (k, v) => "Os " + k.replace("top ", "") + " editores mais produtivos dos últimos " +
                D.cfg.janela + " dias somam " + NF.format(v) + "% de tudo que foi editado no país.")}
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    Fatia das edições dos últimos ${D.cfg.janela} dias.</p></div>`);

  blocos.push(`<div class="painel"><h2>Safras de entrada</h2>
    ${p.entrada.map(([ano, n, viv]) => {
      const max = Math.max(...p.entrada.map((r) => r[1])) || 1;
      const pct = n ? Math.round(100 * viv / n) : 0;
      const poucos = n < D.cfg.safraMin;
      return `<div class="barra" title="${n} pessoa(s) fizeram a primeira edição em ${ano}; ${viv} (${pct}%) ainda editaram nos últimos ${D.cfg.janela} dias.${poucos ? " Safra pequena demais para o percentual significar muito." : ""}">
        <span>${ano}</span>
        <span class="t"><span class="f" style="width:${Math.max(1, (n / max) * 100)}%;display:block"></span></span>
        <span class="v" title="${n} pessoa(s) fizeram a primeira edição em ${ano}; ${viv} delas ainda editaram nos últimos ${D.cfg.janela} dias.">${n}
          <span class="sec">· ${pct}%${poucos ? "*" : ""}</span></span>
      </div>`;
    }).join("")}
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    Barra é quantos entraram no ano; o percentual é quanto dessa safra ainda
    edita hoje. Entre as safras de ${D.resumo.safraLimite} ou antes — as que já
    têm ao menos ${D.cfg.safraMadura} anos — a mediana é
    <b>${D.resumo.retencao}%</b>, variando de ${D.resumo.faixaRetencao[0]}% a
    ${D.resumo.faixaRetencao[1]}%. As mais novas ficam fora dessa conta porque
    tiveram menos tempo para perder gente, e não porque marquem mais ou menos.
    <span class="sec">* menos de ${D.cfg.safraMin} pessoas — o percentual
    oscila demais para significar algo.</span></p></div>`);

  blocos.push(`<div class="painel"><h2>Produziam e pararam</h2>
    ${p.evasao.length ? `<table><thead><tr>
    <th title="Editor que produzia no começo da janela e parou.">Editor</th>
    <th class="num" title="Edições feitas nos primeiros ${D.cfg.meta} dias da janela — o que a pessoa estava produzindo antes de sumir.">Antes</th>
    <th class="num" title="Dias desde a última edição. Só entra na lista quem está em silêncio há ${D.cfg.evasaoDias} dias ou mais.">Calado</th>
    </tr></thead><tbody>
    ${p.evasao.map(([u, uf, prim, sil]) => `<tr>
       <td>${link(u)} <span class="chip">${uf || "--"}</span></td>
       <td class="num">${NF.format(prim)}</td>
       <td class="num down" title="Última edição há ${sil} dias.">${sil} d</td></tr>`).join("")}
    </tbody></table>` : `<p style="color:var(--muted)">Ninguém nessa situação.</p>`}
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    Editaram nos primeiros ${D.cfg.meta} dias da janela e estão em silêncio há
    ${D.cfg.evasaoDias} dias ou mais. No mesmo período houve <b>${NF.format(p.retornos)}</b> retorno(s) —
    editor parado que voltou a produzir.</p></div>`);

  blocos.push(`<div class="painel"><h2>Gigantes parados</h2>
    <table><thead><tr>
    <th title="Posição no ranking histórico e nome do editor.">Editor</th>
    <th class="num" title="Total de edições da carreira. São nomes grandes do mapa brasileiro.">Total</th>
    <th class="num" title="Dias desde a última edição. '${D.cfg.janela}+ d' significa que não editou nenhuma vez em toda a janela.">Parado</th>
    </tr></thead><tbody>
    ${p.parados.map(([u, uf, tot, d90, pos, sil]) => `<tr>
        <td><span style="color:var(--muted)">${pos}.</span> ${link(u)}
            <span class="chip">${uf || "--"}</span></td>
        <td class="num">${NF.format(tot)}</td>
        <td class="num" title="${sil === null
          ? "Nenhuma edição em toda a janela de " + D.cfg.janela + " dias."
          : "Última edição há " + sil + " dias."}">${sil === null
          ? D.cfg.janela + "+ d" : sil + " d"}</td></tr>`).join("")}
    </tbody></table>
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    Do top ${D.cfg.topParados} histórico, os que fizeram menos de
    ${D.cfg.paradoMax} edições nos últimos ${D.cfg.janela} dias.</p></div>`);

  blocos.push(`<div class="painel"><h2>Ritmo semanal</h2>
    ${barras(p.semana, (v) => NF.format(v),
      (k, v) => NF.format(v) + " edições caíram numa " + k + " ao longo dos últimos " +
                D.cfg.janela + " dias, somando todas as pessoas.")}
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    ${(() => { const d = D.resumo.deltaFds;
       if (Math.abs(d) < 5) return "Fim de semana e dia útil rendem praticamente o mesmo.";
       return `O fim de semana rende <b>${d > 0 ? "+" : ""}${d}%</b> em relação ao dia
               útil médio.`; })()}</p></div>`);

  blocos.push(`<div class="painel"><h2>Nível e atividade</h2>
    ${p.niveis.map(([lv, n, viv]) => {
      const pct = n ? Math.round(100 * viv / n) : 0;
      return `<div class="barra" title="Nível ${lv}: ${NF.format(n)} editores no nível, ${viv} deles ativos nos últimos ${D.cfg.janela} dias — ${pct}%.">
        <span>N${lv}</span>
        <span class="t"><span class="f" style="width:${Math.max(1, pct)}%;display:block"></span></span>
        <span class="v">${pct}% <span class="sec">de ${NF.format(n)}</span></span>
      </div>`;
    }).join("")}
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    Barra é a fatia de cada nível que editou nos últimos ${D.cfg.janela} dias;
    ao lado, quantos editores existem no nível.
    ${(() => {
      // Se o gradiente sobe do primeiro nível ao último, dizer que sobe. Se
      // quebrar, dizer onde quebrou — nunca afirmar a forma sem conferir.
      const t = p.niveis.map(([lv, n, viv]) => [lv, n ? viv / n : 0]);
      const quebras = t.filter((v, i) => i > 0 && v[1] < t[i - 1][1]);
      if (t.length < 2) return "";
      if (!quebras.length) return `Sobe sem exceção do nível ${t[0][0]} ao ${t[t.length - 1][0]}.`;
      return "Não sobe de ponta a ponta: cai " +
        quebras.map(([lv]) => "no nível " + lv).join(" e ") + ".";
    })()}</p></div>`);

  blocos.push(`<div class="painel"><h2>Chegaram na janela</h2>
    ${p.novatos.length ? `<table><thead><tr>
    <th title="Quem fez a primeira edição da vida dentro da janela. O selo 'parou' marca quem não editou nos últimos ${D.cfg.recenteDias} dias.">Editor</th>
    <th class="num" title="Data da primeiríssima edição da pessoa no Waze.">Desde</th>
    <th class="num" title="Quanto essa pessoa já produziu desde que começou, dentro da janela.">${D.cfg.janela} d</th>
    </tr></thead><tbody>
    ${p.novatos.map(([u, uf, desde, ed, vivo]) => `<tr>
      <td>${link(u)} <span class="chip">${uf || "--"}</span>${
        vivo ? "" : ` <span class="chip" title="Não editou nos últimos ${D.cfg.recenteDias} dias.">parou</span>`}</td>
      <td class="num">${desde.slice(8,10)}/${desde.slice(5,7)}</td>
      <td class="num">${NF.format(ed)}</td></tr>`).join("")}
    </tbody></table>` : `<p style="color:var(--muted)">Ninguém estreou na janela.</p>`}
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    <b>${NF.format(p.novatosTotal)}</b> fizeram a primeira edição da vida dentro
    da janela; <b>${NF.format(p.novatosVivos)}</b> ainda editaram nos
    últimos ${D.cfg.recenteDias} dias.</p></div>`);

  const mt = p.mentoria;
  const nv = p.candidatos;
  if (nv && (nv.totalProntos || nv.totalQuase)) {
    // Conversão de calendário, só para o rótulo caber na coluna. Os dois
    // valores que decidem qual formato usar são limiares e vêm do cfg.
    const DIAS_SEM = 7, DIAS_MES = 30;
    const prazo = (d) => {
      if (d === null || d === undefined) return "--";
      if (d > C.ritmoHorizonte) return "longe";
      if (d < C.ritmoEmSemanas) return "~" + Math.max(1, Math.round(d / DIAS_SEM)) + " sem";
      const n = Math.max(1, Math.round(d / DIAS_MES));
      return "~" + n + (n === 1 ? " mês" : " meses");
    };
    const ritmoAjuda = (a) => NF.format(a) + " edições nos últimos " + C.janela
      + " dias. Esta lista está ordenada por isto.";
    const prazoAjuda = (d, a) => d === null || d === undefined
      ? "Sem edição na janela, não há ritmo para projetar."
      : d > C.ritmoHorizonte
        ? "Mantido o ritmo de " + NF.format(a) + " edições em " + C.janela
          + " dias, chegar ao limiar passaria de " + NF.format(C.ritmoHorizonte)
          + " dias. A página não projeta além disso."
        : "Mantido o ritmo de " + NF.format(a) + " edições em " + C.janela
          + " dias, o que falta até o limiar sai em cerca de " + NF.format(d)
          + " dias. É projeção a ritmo constante, não previsão.";
    const progAjuda = (pronto, ed, lim) => pronto
      ? NF.format(ed) + " edições no total"
        + (lim ? ", contra o limiar de " + NF.format(lim) + " deste nível" : "")
        + " — já está no limiar ou acima."
      : lim
        ? NF.format(ed) + " de " + NF.format(lim) + " edições — o limiar deste nível é o mesmo para todo mundo nesta coleta."
        : NF.format(ed) + " edições. O limiar deste nível não é o mesmo para todo mundo, então a página não cita quantas edições faltam.";
    const linhas = (arr, pronto) => arr.map(([u, uf, lv, alvo, pct, ed, lim, dias, d90]) => `<tr>
      <td title="${esc(u)}">${link(u)} <span class="chip">${uf || "--"}</span></td>
      <td class="num" title="${lv ? "Está no nível " + lv + " e é candidato ao nível " + alvo + "." : "Nível não informado."}">${lv ? "N" + lv + "→N" + alvo : "--"}</td>
      <td class="num${pronto ? " up" : ""}" title="${progAjuda(pronto, ed, lim)}">${pronto ? "✓" : pct + "%"}</td>
      <td class="num" title="${pronto ? ritmoAjuda(d90) : prazoAjuda(dias, d90)}">${
        pronto ? NF.format(d90) : prazo(dias)}</td>
      </tr>`).join("");
    blocos.push(`<div class="painel largo"><h2>A caminho do próximo nível</h2>
      <div class="duplo empilha">
      <div><h3>Já chegaram ao limiar</h3>
      ${nv.totalProntos ? `<table><thead><tr>
        <th title="Editor que o Waze lista como candidato e que já atingiu o limiar do próximo nível.">Editor</th>
        <th class="num" title="Nível atual e o nível a que é candidato.">Nível</th>
        <th class="num" title="Progresso que o Waze calcula até o próximo nível. O visto marca quem já está no limiar ou acima.">Progr.</th>
        <th class="num" title="Edições nos últimos ${C.janela} dias. Entre quem já está no limiar, aparece primeiro quem segue editando mais.">${C.janela} dias</th>
        </tr></thead><tbody>${linhas(nv.prontos, true)}</tbody></table>`
        : `<p style="color:var(--muted)">Ninguém no limiar agora.</p>`}</div>
      <div><h3>Mais perto de chegar</h3>
      ${nv.totalQuase ? `<table><thead><tr>
        <th title="Editor que o Waze lista como candidato e ainda não atingiu o limiar.">Editor</th>
        <th class="num" title="Nível atual e o nível a que é candidato.">Nível</th>
        <th class="num" title="Progresso que o Waze calcula até o próximo nível.">Progr.</th>
        <th class="num" title="Quanto levaria até o limiar mantendo o ritmo dos últimos ${C.janela} dias. Esta lista está ordenada por isto. Acima de ${C.ritmoHorizonte} dias a página só diz que está longe.">No ritmo</th>
        </tr></thead><tbody>${linhas(nv.quase, false)}</tbody></table>`
        : `<p style="color:var(--muted)">Ninguém abaixo do limiar agora.</p>`}</div>
      </div>
      <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
      <b>${NF.format(nv.totalProntos)}</b> já estão no limiar do próximo nível e
      <b>${NF.format(nv.totalQuase)}</b> ainda não. O progresso é o que o próprio
      Waze calcula${nv.limiares.length
        ? `; medindo edições contra progresso, o limiar sai igual para todos os
           candidatos ${nv.limiares.map(([lv, v]) =>
             "do nível " + lv + " (" + NF.format(v) + " edições)").join(" e ")}.
           Nos demais níveis ele muda de pessoa para pessoa, e o que entra nessa
           conta não vem no dado — por isso a página não cita quantas edições
           faltam`
        : ", e o que entra nessa conta não vem no dado"}.
      As listas são ordenadas por atividade, não por acumulado: quem já
      chegou, pelas edições da janela; quem ainda não, pelo prazo que o ritmo da
      janela daria. Esse prazo é o que falta até o limiar dividido pelo ritmo
      medido, e vale enquanto o ritmo valer — é projeção, não previsão.
      Só entram candidatos que editaram nos últimos ${D.cfg.janela} dias${
        nv.parados ? `: outros <b>${NF.format(nv.parados)}</b> estão na lista do
        Waze com o progresso feito, mas pararam de editar` : ""}.
      ${nv.foraDoRanking ? `A lista trouxe <b>${NF.format(nv.foraDoRanking)}</b>
        editores que não apareciam em ranking nenhum e por ela entraram no
        placar.` : ""}
      ${nv.temOmitidos ? "Candidatos com restrição ativa não entram nesta lista." : ""}
      </p></div>`);
  }

  blocos.push(`<div class="painel"><h2>Mentoria</h2>
    ${mt.comparavel ? `<div class="barra" title="Dos ${NF.format(mt.rastreados)} editores que aparecem como afilhados de alguém, ${mt.pctApad}% editaram nos últimos ${D.cfg.janela} dias."><span>apadr.</span>
       <span class="t"><span class="f" style="width:${mt.pctApad}%;display:block"></span></span>
       <span class="v">${mt.pctApad}%</span></div>
     <div class="barra" title="Entre todos os outros editores do placar, ${mt.pctResto}% editaram nos últimos ${D.cfg.janela} dias. É a taxa de base para comparar."><span>demais</span>
       <span class="t"><span class="f" style="width:${mt.pctResto}%;display:block"></span></span>
       <span class="v">${mt.pctResto}%</span></div>
     <p style="color:var(--muted);font-size:.8rem;margin:8px 0 12px">
     Fatia que editou nos últimos ${D.cfg.janela} dias, entre os
     ${NF.format(mt.rastreados)} apadrinhados que a coleta conseguiu olhar
     — ${mt.cobertura}% dos nomeados — e entre os demais editores. Os
     números lado a lado não mostram que apadrinhar faz ficar. Quem vira afilhado
     não é sorteado, e esta coleta não tem como separar o efeito do
     apadrinhamento de quem já ia continuar de todo jeito.</p>
     <table><thead><tr>
     <th title="Editor que apadrinha novatos no Waze.">Mentor</th>
     <th class="num" title="Quantos afilhados o Waze registra para essa pessoa.">Afilh.</th>
     <th class="num" title="Quantos desses afilhados editaram nos últimos ${D.cfg.janela} dias.">Ativos</th>
     </tr></thead><tbody>
     ${mt.top.map(([u, uf, n, lst, viv]) => `<tr>
        <td>${link(u)} <span class="chip">${uf || "--"}</span></td>
        <td class="num">${n}${n > lst ? "*" : ""}</td>
        <td class="num">${viv}${n > lst ? "*" : ""}</td></tr>`).join("")}
     </tbody></table>`
     : `<p style="color:var(--muted)">Esta coleta só conseguiu olhar
        ${mt.cobertura}% dos afilhados nomeados, abaixo do piso de
        ${D.cfg.mentoriaCobertura}% — comparar com essa amostra mediria quem já
        aparecia num ranking, não quem foi apadrinhado.</p>`}
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    ${NF.format(mt.mentores)} editores aparecem como mentores, com
    ${NF.format(mt.afilhados)} afilhados nomeados.${mt.truncados
      ? ` <span class="sec">* a API lista no máximo ${mt.capLista}
          afilhados por mentor, então para ${NF.format(mt.truncados)} deles a
          coluna de ativos sai de uma amostra.</span>` : ""}</p></div>`);

  if (p.forasteiros.length) {
    blocos.push(`<div class="painel"><h2>Cuidam de longe</h2>
      <table><thead><tr>
      <th title="Editor cujas áreas gerenciadas ficam longe das áreas dos colegas do mesmo estado.">Editor</th>
      <th class="num" title="Distância entre o centro das áreas dessa pessoa e o centro das áreas dos demais editores do estado dela. Áreas fora do Brasil não entram no cálculo.">Distância</th>
      </tr></thead><tbody>
      ${p.forasteiros.map(([u, uf, km]) => `<tr>
        <td>${link(u)} <span class="chip">${uf}</span></td>
        <td class="num" title="As áreas de ${esc(u)} ficam a cerca de ${NF.format(km)} km do centro das áreas dos outros editores de ${uf}.">${NF.format(km)} km</td></tr>`).join("")}
      </tbody></table>
      <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
      Distância entre o centro das áreas que a pessoa gerencia dentro do Brasil
      e o centro das áreas dos demais editores do mesmo estado. Áreas fora do
      país não entram na conta.</p></div>`);
  }

  blocos.push(cidadesEtipos(p.atividade));
  blocos.push(calendario(p));
  blocos.push(mapaAtividade(p.atividade));
  blocos.push(mapa(p.mapa));
  blocos.push(alcance(p.cobertura));

  $("paineis").innerHTML = blocos.join("");
  const m2 = $("fMin");
  if (m2) m2.textContent = D.cfg.safraMin;
}

function montaUfs() {
  const keep = $("uf").value;
  const ufs = [...new Set(D.abas[aba].map((i) => D.editores[i][1]).filter(Boolean))].sort();
  $("uf").innerHTML = '<option value="">Todos os estados</option>' +
    ufs.map((u) => `<option${u === keep ? " selected" : ""}>${u}</option>`).join("");
}

function build() {
  const r = D.resumo;
  const so = D.cfg.semAtividade;
  if (so) { aba = "tot"; document.body.classList.add("sem-atividade"); }

  $("sub").textContent = "Brasil · "
    + (so ? "só o ranking acumulado" : `atividade de ${D.janela[0]} a ${D.janela[1]}`)
    + ` · gerado em ${D.gerado}`;

  $("kpis").innerHTML = (so ? [
    [NF.format(r.historico), "editores no ranking histórico", AJUDA.kpi.universo],
    [NF.format(r.edicoesTotal), "edições somadas nas carreiras", AJUDA.kpi.carreiras],
  ] : [
    [NF.format(r.ativos30), `editores ativos nos últimos ${C.janelaMedia} dias`, AJUDA.kpi.ativos],
    [NF.format(r.edicoes90), `edições em ${C.janela} dias`, AJUDA.kpi.edicoes],
    [NF.format(r.concKpi) + "%", `das edições vêm de ${C.concKpiN} pessoas`, AJUDA.kpi.conc],
    [NF.format(r.fator1), "estados dependem de um único editor", AJUDA.kpi.fator1],
  ]).map(([v, k, aj]) =>
    `<div class="kpi" title="${aj}"><b>${v}</b><span>${k}</span></div>`).join("");

  $("tabs").innerHTML = ABAS.filter(([k]) => !so || k === "tot").map(([k, rot]) =>
    `<button class="tab" role="tab" data-k="${k}" aria-selected="${k === aba}"
       aria-controls="painelTabela"
       title="${AJUDA.janela[k]} ${k === "tot"
         ? "O número ao lado é o universo inteiro que o placar enxerga."
         : "O número ao lado é quantos editores têm ao menos uma edição nessa janela."}">
       ${rot} <span class="conta">${NF.format(D.abas[k].length)}</span>
     </button>`).join("");
  $("tabs").onclick = (e) => {
    const b = e.target.closest(".tab");
    if (!b) return;
    aba = b.dataset.k;
    mostrarTudo = false;
    [...$("tabs").children].forEach((t) =>
      t.setAttribute("aria-selected", t.dataset.k === aba));
    montaUfs();
    render();
  };
  // desenhar milhares de linhas trava a aba por segundos; o rótulo muda antes,
  // num quadro à parte, senão a troca só apareceria depois de tudo pronto
  $("verTudo").onclick = () => {
    const b = $("verTudo");
    b.disabled = true;
    b.textContent = "Desenhando…";
    setTimeout(() => { mostrarTudo = true; render(); b.disabled = false;
                       b.textContent = "Mostrar todos"; }, 16);
  };
  [["thPos", AJUDA.pos], ["thEditor", AJUDA.editor], ["thSpark", AJUDA.faisca],
   ["thSeq", AJUDA.seq], ["thTend", AJUDA.tend], ["thHist", AJUDA.tot]]
    .forEach(([id, t]) => { const el = $(id); if (el) el.title = t; });
  $("thSpark").textContent = C.janela + " dias";

  const c = D.cfg;
  [["fRank", c.rankings], ["fUf", c.ufs], ["fCap", c.cap], ["fCap2", c.cap],
   ["fQuad", c.quadros], ["fJan", c.janelasApi],
   ["fVet", c.vetorDias], ["fMeta", c.meta], ["fMeta2", c.meta],
   ["fMin", c.safraMin]]
    .forEach(([id, v]) => { const el = $(id); if (el) el.textContent = NF.format(v); });
  // ano é ano: 2009, não 2.009
  if ($("fAno")) $("fAno").textContent = String(c.primeiroAno);
  const e = D.estat || {};
  if ($("fGap")) $("fGap").textContent = (e.foraPct || 0) + "%";
  if ($("fZero")) $("fZero").textContent = (e.semEdicaoPct || 0) + "%";

  montaUfs();
  $("q").oninput = render;
  $("uf").onchange = render;
  render();
  paineis();
}

ligaTema();
build();
</script>
"""


def build_html(dados: dict) -> str:
    data = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    # `</script>` dentro do JSON encerraria o bloco cedo demais.
    data = data.replace("</", "<\\/")
    return PAGE.replace("__DATA__", data)
