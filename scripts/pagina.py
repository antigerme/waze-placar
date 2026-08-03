#!/usr/bin/env python3
"""Monta o HTML do placar a partir dos perfis coletados."""

import datetime as dt
import html
import json
from collections import Counter, defaultdict

DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
BUCKETS = 15          # 15 baldes de 6 dias = os 90 dias completos
BUCKET_DIAS = 6


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
    a, b = sum(act[:45]), sum(act[45:90])
    if a + b < 200:
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
TIPO_COMUM = "segmentos"      # 4 em 5 editores; fica esmaecido para não poluir


def _especialidade(tipos):
    """O tipo de edição que domina o trabalho histórico do editor."""
    t = {k: v for k, v in (tipos or {}).items() if v}
    if not t:
        return None
    return TIPOS.get(max(t, key=t.get), max(t, key=t.get))


def _ritmo(act, d90):
    """Maratonista ou velocista.

    Só classifica quem tem volume: com 30 edições no trimestre, 'explosivo'
    diria mais sobre o acaso do que sobre a pessoa.
    """
    if d90 < 500:
        return None
    dias = act[:-1]
    ativos = sum(1 for v in dias if v > 0)
    pico = max(dias) if dias else 0
    conc = pico / d90 if d90 else 0
    if ativos >= 60 and conc <= 0.10:
        return "constante"
    if conc >= 0.25:
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
CELULA = 0.5                  # grau; ~55 km, resolução honesta para o tamanho


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


def prepara(perfis, ufs, gerado, areas=None):
    """Transforma os perfis crus na carga que a página consome."""
    areas = areas or {}
    eds = []
    for p in perfis:
        act = (p.get("activity") or [])
        if len(act) < 91:                      # normaliza vetores curtos
            act = [0] * (91 - len(act)) + list(act)
        completos = act[:-1]                   # 90 dias fechados
        d7, d30, d90 = sum(act[-8:-1]), sum(act[-31:-1]), sum(completos)
        semanas = [sum(completos[i * BUCKET_DIAS:(i + 1) * BUCKET_DIAS])
                   for i in range(BUCKETS)]
        ano = None
        if p.get("firstEditDate"):
            ano = dt.datetime.utcfromtimestamp(p["firstEditDate"] / 1000).year
        eds.append({
            "u": p["username"], "uf": ufs.get(p["username"]),
            "lvl": p.get("level"), "tot": p.get("edits") or 0,
            "d7": d7, "d30": d30, "d90": d90,
            "streak": _streak(act), "tend": _tendencia(act),
            "semanas": semanas if d90 > 0 else None, "ano": ano,
            "mentees": p.get("menteesCount") or 0,
            "esp": _especialidade(p.get("editsByType")),
            "ritmo": _ritmo(act, d90),
            "silencio": _silencio(act),
            "prim45": sum(act[:45]), "seg45": sum(act[45:90]),
            "areas": len(areas.get(p["username"]) or []),
        })

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
    for p in perfis:
        act = p.get("activity") or []
        for i, v in enumerate(act[:-1]):
            if v:
                semana[(d0 + dt.timedelta(days=i)).weekday()] += v

    por90 = sorted(eds, key=lambda e: -e["d90"])
    tot90 = sum(e["d90"] for e in eds) or 1
    concentracao = [[n, round(100 * sum(e["d90"] for e in por90[:n]) / tot90, 1)]
                    for n in (5, 10, 25, 50, 100)]

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
               for i, e in enumerate(por_total[:60]) if e["d90"] < 100][:12]

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

    # Vigília: produzia no começo da janela e emudeceu no fim.
    evasao = sorted(
        ([e["u"], e["uf"], e["prim45"], e["silencio"]] for e in eds
         if e["prim45"] >= 300 and e["silencio"] is not None
         and e["silencio"] >= 21),
        key=lambda r: -r[2])[:10]
    retornos = sum(1 for e in eds if e["prim45"] < 50 and e["seg45"] >= 500)

    ativos30 = len(abas["d30"])
    return {
        "gerado": gerado,
        "janela": [d0.isoformat(), hoje.isoformat()],
        "editores": [[e["u"], e["uf"], e["lvl"], e["tot"], e["d7"], e["d30"],
                      e["d90"], e["streak"], e["tend"], e["semanas"],
                      e["mentees"], e["esp"], e["ritmo"], e["areas"]]
                     for e in eds],
        "abas": abas,
        "tipoComum": TIPO_COMUM,
        "resumo": {
            "ativos30": ativos30,
            "ativos90": len(abas["d90"]),
            "historico": len(eds),
            "edicoes90": tot90,
            "top50": concentracao[3][1],
            "novos": sum(n for a, n, _ in entrada if a >= hoje.year - 1),
            "fator1": sum(1 for r in estados if r[3] == 1),
        },
        "paineis": {
            "semana": [[DIAS[i], semana[i]] for i in range(7)],
            "concentracao": concentracao,
            "entrada": entrada,
            "parados": parados,
            "estados": estados,
            "evasao": evasao,
            "retornos": retornos,
            "mapa": _grade_cobertura(areas, ufs),
        },
    }


PAGE = r"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Placar dos Editores do Waze — Brasil</title>
<style>
  :root {
    color-scheme: light;
    --page:#f6f8fa; --card:#fff; --ink:#12212e; --muted:#5b6b7a;
    --line:#e3e9ef; --chip:#eef3f7;
    --series:#2a78d6; --series-soft:#cde2fb;
    --grid:#e1e0d9; --baseline:#c3c2b7; --axis:#898781;
    --up:#006300; --down:#d03b3b;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --page:#0d1519; --card:#141f26; --ink:#e6eef4; --muted:#8ba3b4;
      --line:#22323d; --chip:#1b2a33;
      --series:#3987e5; --series-soft:#1b3f55;
      --grid:#2c2c2a; --baseline:#383835; --axis:#898781;
      --up:#0ca30c; --down:#d03b3b;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --page:#0d1519; --card:#141f26; --ink:#e6eef4; --muted:#8ba3b4;
    --line:#22323d; --chip:#1b2a33;
    --series:#3987e5; --series-soft:#1b3f55;
    --grid:#2c2c2a; --baseline:#383835; --axis:#898781;
    --up:#0ca30c; --down:#d03b3b;
  }
  * { box-sizing:border-box }
  body { margin:0; background:var(--page); color:var(--ink);
         font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif }
  .wrap { max-width:1100px; margin:0 auto; padding:28px 18px 64px }
  h1 { font-size:1.6rem; margin:0 0 4px; letter-spacing:-.02em }
  h2 { font-size:.85rem; margin:0 0 14px; text-transform:uppercase;
       letter-spacing:.06em; color:var(--muted) }
  .sub { color:var(--muted); font-size:.9rem; margin:0 0 22px }

  .kpis { display:grid; gap:10px; margin-bottom:20px;
          grid-template-columns:repeat(auto-fit,minmax(160px,1fr)) }
  .kpi { background:var(--card); border:1px solid var(--line);
         border-radius:12px; padding:14px 16px }
  .kpi b { display:block; font-size:1.7rem; letter-spacing:-.02em; line-height:1.15 }
  .kpi span { color:var(--muted); font-size:.78rem }

  .tabs { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:14px }
  .tab { border:1px solid var(--line); background:var(--card); color:var(--muted);
         padding:8px 16px; border-radius:999px; cursor:pointer; font-size:.9rem;
         font-weight:600; font-family:inherit }
  .tab[aria-selected="true"] { background:var(--series); border-color:var(--series);
                               color:#fff }
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
       background:var(--card) }
  tr:last-child td { border-bottom:none }
  td.num, th.num { text-align:right }
  .pos { color:var(--muted); width:56px }
  .name { font-weight:600; width:99%; white-space:normal }
  .name a { color:inherit; text-decoration:none }
  .name a:hover, .name a:focus-visible { color:var(--series);
                                         text-decoration:underline }
  .chip { background:var(--chip); border-radius:5px; padding:1px 7px;
          font-size:.75rem; color:var(--muted); font-weight:600 }
  .chip.fraco { background:transparent; color:var(--muted); opacity:.5;
                font-weight:500 }
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
  .barra { display:grid; grid-template-columns:42px 1fr auto; gap:10px;
           align-items:center; margin:5px 0; font-size:.85rem }
  .barra span:first-child { color:var(--muted) }
  .barra .t { background:var(--grid); border-radius:4px; height:9px }
  .barra .f { background:var(--series); border-radius:4px; height:9px;
              min-width:2px }
  .barra .v { color:var(--muted); font-variant-numeric:tabular-nums;
              font-size:.8rem }
  .painel table { font-size:.85rem }
  .painel td, .painel th { padding:5px 8px; border-bottom:1px solid var(--line) }
  .painel .rola { overflow-x:auto; margin:0 -4px; padding:0 4px }
  .painel td.quebra { white-space:normal; min-width:110px }
  @media (min-width:720px) { .painel.largo { grid-column:span 2 } }

  footer { margin-top:24px; color:var(--muted); font-size:.8rem }
  footer p { margin:.45em 0 }
  code { background:var(--chip); padding:1px 5px; border-radius:4px; font-size:.9em }
  .empty { padding:28px; text-align:center; color:var(--muted) }
</style>

<div class="wrap">
  <h1>Placar dos Editores do Waze</h1>
  <p class="sub" id="sub"></p>

  <div class="kpis" id="kpis"></div>

  <div class="tabs" id="tabs"></div>
  <div class="controls">
    <input id="q" type="search" placeholder="Procurar editor…" autocomplete="off">
    <select id="uf"></select>
  </div>

  <div class="tablewrap">
    <table>
      <thead><tr>
        <th class="pos">#</th><th>Editor</th><th>UF</th><th>Nível</th>
        <th>Perfil</th>
        <th class="num" id="thJanela">Edições</th>
        <th>90 dias</th>
        <th class="num">Seq.</th><th class="num">Tend.</th>
        <th class="num">Histórico</th>
      </tr></thead>
      <tbody id="body"></tbody>
    </table>
    <div class="empty" id="empty" hidden>Nenhum editor encontrado.</div>
  </div>

  <div class="paineis" id="paineis"></div>

  <footer>
    <p><b>De onde vem.</b> A lista de editores sai de 84 rankings do Waze — o
    nacional e os 27 estaduais, nas três janelas que a API oferece, 500 linhas
    cada. Varrer só o histórico deixava de fora 40% de quem edita hoje, porque
    aquele ranking ordena por pontos acumulados. A atividade diária vem do
    perfil de cada editor, que expõe os últimos 91 dias. Como os rankings
    estaduais não se sobrepõem, a UF de cada um vem da varredura.</p>
    <p><b>Por que ordenar por atividade.</b> Os rankings do Waze ordenam por
    pontos — dirigir e editar somados — e cortam em 500, então em janelas curtas
    as vagas enchem de motorista. Ordenando pelas edições reais dos últimos 30
    dias, o placar mostra quem está construindo o mapa agora, e não quem
    acumulou mais desde 2011.</p>
    <p><b>Tendência</b> compara os segundos 45 dias com os primeiros 45, e só
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

const ABAS = [
  ["d30", "30 dias", 5], ["d7", "7 dias", 4],
  ["d90", "90 dias", 6], ["tot", "Histórico", 3],
];
let aba = "d30";

// [u, uf, lvl, tot, d7, d30, d90, streak, tend, semanas, mentees]
const col = () => ABAS.find((a) => a[0] === aba)[2];

function linhas() {
  const q = $("q").value.trim().toLowerCase();
  const uf = $("uf").value;
  return D.abas[aba]
    .map((i) => D.editores[i])
    .filter((e) => (!uf || e[1] === uf) && (!q || e[0].toLowerCase().includes(q)));
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
  // 4 em 5 editores são de segmento: esmaece o comum para os outros saltarem.
  if (e[11]) s.push(`<span class="chip${e[11] === D.tipoComum ? " fraco" : ""}"
    title="Tipo de edição que domina o trabalho histórico">${esc(e[11])}</span>`);
  if (e[12]) s.push(`<span class="chip"
    title="${e[12] === "constante" ? "Edita quase todo dia, sem picos"
                                   : "Concentra o trabalho em poucos dias"}"
    >${e[12]}</span>`);
  if (e[10]) s.push(`<span class="chip"
    title="${e[10]} editor(es) apadrinhado(s)">mentor</span>`);
  if (e[13]) s.push(`<span class="chip"
    title="${e[13]} área(s) gerenciada(s)">AM</span>`);
  return s.join(" ");
}

function tend(t) {
  if (t === null || t === undefined) return '<span class="flat">—</span>';
  if (t >= 999) return '<span class="up">↑ novo</span>';
  if (t > 10) return `<span class="up">↑ ${t}%</span>`;
  if (t < -10) return `<span class="down">↓ ${Math.abs(t)}%</span>`;
  return '<span class="flat">→</span>';
}

function render() {
  const lista = linhas();
  const c = col();
  $("body").innerHTML = lista.map((e, n) => `<tr>
      <td class="pos">${n + 1}</td>
      <td class="name"><a href="${esc(perfil(e[0]))}" target="_blank"
         rel="noopener noreferrer" title="Ver perfil de ${esc(e[0])} no Waze"
         >${esc(e[0])}</a></td>
      <td><span class="chip">${e[1] || "--"}</span></td>
      <td>${e[2] ? `<span class="chip">N${e[2]}</span>` : ""}</td>
      <td>${selos(e)}</td>
      <td class="num">${NF.format(e[c])}</td>
      <td>${faisca(e[9])}</td>
      <td class="num">${e[7] || ""}</td>
      <td class="num">${tend(e[8])}</td>
      <td class="num">${NF.format(e[3])}</td>
    </tr>`).join("");
  $("empty").hidden = lista.length > 0;
  $("thJanela").textContent =
    aba === "tot" ? "Edições" : "Edições (" + ABAS.find((a) => a[0] === aba)[1] + ")";
}

function barras(itens, fmt) {
  const max = Math.max(...itens.map((i) => i[1])) || 1;
  return itens.map(([k, v]) => `<div class="barra">
      <span>${esc(k)}</span>
      <span class="t"><span class="f" style="width:${Math.max(1, (v / max) * 100)}%;display:block"></span></span>
      <span class="v">${fmt(v)}</span>
    </div>`).join("");
}

function link(u) {
  return `<a href="${esc(perfil(u))}" target="_blank" rel="noopener noreferrer"
     style="color:inherit">${esc(u)}</a>`;
}

function mapa(m) {
  if (!m.celulas.length) return "";
  const FAIXAS = [[5, 1, "5 ou mais"], [3, .72, "3 a 4"],
                  [2, .48, "2"], [1, .26, "1"]];
  const cor = (n) => (FAIXAS.find((f) => n >= f[0]) || FAIXAS[3])[1];
  const cells = m.celulas.map(([i, j, n]) =>
    `<rect x="${i}" y="${m.ny - 1 - j}" width="1" height="1"
       fill="var(--series)" fill-opacity="${cor(n)}"><title>${n} editor(es)</title></rect>`
  ).join("");
  // Retículas a cada 10° dão referência sem inventar geografia.
  let grade = "";
  for (let g = 10; g < m.nx; g += 20)
    grade += `<line x1="${g}" y1="0" x2="${g}" y2="${m.ny}"
      stroke="var(--grid)" stroke-width=".35"/>`;
  for (let g = 10; g < m.ny; g += 20)
    grade += `<line x1="0" y1="${g}" x2="${m.nx}" y2="${g}"
      stroke="var(--grid)" stroke-width=".35"/>`;
  const legenda = FAIXAS.slice().reverse().map(([n, o, rot]) =>
    `<span style="display:inline-flex;align-items:center;gap:5px;margin-right:12px">
       <span style="width:12px;height:12px;border-radius:3px;background:var(--series);
                    opacity:${o};display:inline-block"></span>${rot}</span>`).join("");

  return `<div class="painel" style="grid-column:1/-1">
    <h2>Cobertura de área gerenciada</h2>
    <svg viewBox="0 0 ${m.nx} ${m.ny}" style="width:100%;max-width:520px;
         height:auto;display:block;margin:0 auto" shape-rendering="crispEdges"
         role="img" aria-label="Mapa de cobertura de gerentes de área no Brasil">
      ${grade}${cells}
    </svg>
    <p style="margin:12px 0 0;font-size:.8rem;color:var(--muted)">${legenda}</p>
    <p style="color:var(--muted);font-size:.8rem;margin:8px 0 0">
      ${NF.format(m.editores)} dos editores ativos gerenciam
      ${NF.format(m.areas)} áreas. Cada quadrado tem meio grau (~55 km) e a cor
      diz quantos editores distintos o cobrem; onde não há quadrado, nenhum
      editor ativo gerencia. Projeção simples por latitude e longitude, sem
      contorno político — é um esboço de cobertura, não um mapa.
      ${m.fora ? NF.format(m.fora) + " editores gerenciam áreas fora do Brasil, não desenhadas." : ""}
    </p></div>`;
}

function paineis() {
  const p = D.paineis;
  const blocos = [];

  blocos.push(`<div class="painel largo"><h2>Estados — quem seguraria a queda</h2>
    <div class="rola"><table><thead><tr><th>UF</th><th class="num">Edições</th>
    <th class="num">Ativos</th><th class="num">Fator</th>
    <th>Maior editor</th></tr></thead><tbody>
    ${p.estados.slice(0, 14).map(([uf, ed, n, fator, topo, pct]) => `<tr>
       <td><span class="chip">${uf}</span></td>
       <td class="num">${NF.format(ed)}</td>
       <td class="num">${n}</td>
       <td class="num ${fator === 1 ? "down" : ""}">${fator}</td>
       <td class="quebra">${link(topo)}
         <span style="color:var(--muted)">${pct}%</span></td>
      </tr>`).join("")}
    </tbody></table></div>
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    <b>Fator</b> é quantos editores precisariam parar para o estado perder
    metade das edições. Fator 1 significa que um único editor responde por
    mais da metade — ${NF.format(D.resumo.fator1)} estados estão nessa
    situação.</p></div>`);

  blocos.push(`<div class="painel"><h2>Concentração — quem sustenta o mapa</h2>
    ${barras(p.concentracao.map(([n, pc]) => ["top " + n, pc]), (v) => v + "%")}
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    Fatia das edições dos últimos 90 dias.</p></div>`);

  blocos.push(`<div class="painel"><h2>Safras — entrada e sobrevivência</h2>
    ${p.entrada.map(([ano, n, viv]) => {
      const max = Math.max(...p.entrada.map((r) => r[1])) || 1;
      const pct = n ? Math.round(100 * viv / n) : 0;
      const poucos = n < 10;
      return `<div class="barra">
        <span>${ano}</span>
        <span class="t"><span class="f" style="width:${Math.max(1, (n / max) * 100)}%;display:block"></span></span>
        <span class="v" title="${viv} de ${n} ainda editam">${n}
          <span style="opacity:${poucos ? .4 : .8}">· ${pct}%${poucos ? "*" : ""}</span></span>
      </div>`;
    }).join("")}
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    Barra é quantos entraram no ano; o percentual é quanto dessa safra ainda
    edita hoje. Fica em torno de um sexto para quase todo ano, seja 2011 ou
    2021. <span style="opacity:.7">* menos de 10 pessoas — o percentual oscila
    demais para significar algo.</span></p></div>`);

  blocos.push(`<div class="painel"><h2>Vigília — produziam e emudeceram</h2>
    ${p.evasao.length ? `<div class="rola"><table><thead><tr><th>Editor</th>
    <th class="num">Antes</th><th class="num">Calado</th></tr></thead><tbody>
    ${p.evasao.map(([u, uf, prim, sil]) => `<tr>
       <td>${link(u)} <span class="chip">${uf || "--"}</span></td>
       <td class="num">${NF.format(prim)}</td>
       <td class="num down">${sil} d</td></tr>`).join("")}
    </tbody></table></div>` : `<p style="color:var(--muted)">Ninguém nessa situação.</p>`}
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    Editaram nos primeiros 45 dias da janela e estão em silêncio há três semanas
    ou mais. No mesmo período houve <b>${NF.format(p.retornos)}</b> retorno(s) —
    editor parado que voltou a produzir.</p></div>`);

  blocos.push(`<div class="painel"><h2>Gigantes parados</h2>
    <div class="rola"><table><thead><tr><th>#</th><th>Editor</th><th class="num">Total</th><th class="num">Parado</th></tr></thead><tbody>
    ${p.parados.map(([u, uf, tot, d90, pos, sil]) => `<tr>
        <td style="color:var(--muted)">${pos}</td>
        <td>${link(u)} <span class="chip">${uf || "--"}</span></td>
        <td class="num">${NF.format(tot)}</td>
        <td class="num">${sil === null ? "90+ d" : sil + " d"}</td></tr>`).join("")}
    </tbody></table></div>
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    Do top 60 histórico, os que praticamente não editam há 90 dias.</p></div>`);

  blocos.push(`<div class="painel"><h2>Ritmo semanal — 90 dias</h2>
    ${barras(p.semana, (v) => NF.format(v))}
    <p style="color:var(--muted);font-size:.8rem;margin:10px 0 0">
    Não há pico de fim de semana. Qual dia lidera muda de uma coleta para
    outra — é ruído, não padrão.</p></div>`);

  blocos.push(mapa(p.mapa));

  $("paineis").innerHTML = blocos.join("");
}

function montaUfs() {
  const keep = $("uf").value;
  const ufs = [...new Set(D.abas[aba].map((i) => D.editores[i][1]).filter(Boolean))].sort();
  $("uf").innerHTML = '<option value="">Todos os estados</option>' +
    ufs.map((u) => `<option${u === keep ? " selected" : ""}>${u}</option>`).join("");
}

function build() {
  const r = D.resumo;
  $("sub").textContent = `Brasil · atividade de ${D.janela[0]} a ${D.janela[1]}`
    + ` · gerado em ${D.gerado}`;

  $("kpis").innerHTML = [
    [NF.format(r.ativos30), "editores ativos nos últimos 30 dias"],
    [NF.format(r.edicoes90), "edições em 90 dias"],
    [r.top50 + "%", "das edições vêm de 50 pessoas"],
    [NF.format(r.fator1), "estados dependem de um único editor"],
  ].map(([v, k]) => `<div class="kpi"><b>${v}</b><span>${k}</span></div>`).join("");

  $("tabs").innerHTML = ABAS.map(([k, rot]) =>
    `<button class="tab" role="tab" data-k="${k}" aria-selected="${k === aba}">
       ${rot} <span style="opacity:.65">${NF.format(D.abas[k].length)}</span>
     </button>`).join("");
  $("tabs").onclick = (e) => {
    const b = e.target.closest(".tab");
    if (!b) return;
    aba = b.dataset.k;
    [...$("tabs").children].forEach((t) =>
      t.setAttribute("aria-selected", t.dataset.k === aba));
    montaUfs();
    render();
  };
  montaUfs();
  $("q").oninput = render;
  $("uf").onchange = render;
  render();
  paineis();
}

build();
</script>
"""


def build_html(dados: dict) -> str:
    data = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    # `</script>` dentro do JSON encerraria o bloco cedo demais.
    data = data.replace("</", "<\\/")
    return PAGE.replace("__DATA__", data)
