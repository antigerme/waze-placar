#!/usr/bin/env python3
"""Gera o placar dos editores de mapa do Waze no Brasil.

Sem banco, sem estado: lê tudo ao vivo da API do Waze e escreve um HTML
autocontido. As três janelas que a API oferece (histórico, mês, semana) viram
as três abas do placar.

Cada janela é varrida em 28 rankings — o nacional e os 27 estaduais — porque
cada ranking devolve no máximo 500 linhas. Os rankings estaduais são
mutuamente exclusivos, então a UF de cada editor sai de graça da varredura.

Uso:
    python3 scripts/placar.py                    # gera placar.html
    python3 scripts/placar.py --print            # tabela no terminal
    python3 scripts/placar.py --json dados.json  # dados crus
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import html
import http.cookiejar
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "https://www.waze.com/_user/api/leaderboard"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COOKIES = "/tmp/cookies.txt"

# As únicas três que o servidor honra. Qualquer outro valor volta como
# ALL_TIME com status 200, sem erro — por isso o enum é fixo aqui.
PERIODS = {
    "ALL_TIME": "Histórico",
    "PAST_MONTH": "Mês",
    "PAST_WEEK": "Semana",
}

UFS = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
    "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
    "SE", "SP", "TO",
]

WORKERS = 4
DELAY = 0.35

_throttle = threading.Lock()
_last_call = [0.0]


# --------------------------------------------------------------------------- rede

def load_opener(cookie_path: str) -> urllib.request.OpenerDirector:
    """Abre a sessão a partir de um arquivo de cookies no formato Netscape."""
    path = Path(cookie_path)
    if not path.exists():
        sys.exit(f"{cookie_path}: arquivo de cookies não encontrado.")

    jar = http.cookiejar.MozillaCookieJar()
    # MozillaCookieJar ignora as linhas "#HttpOnly_" que o curl escreve.
    cleaned = "\n".join(
        line[len("#HttpOnly_"):] if line.startswith("#HttpOnly_") else line
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
    )
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / f".waze-cookies-{os.getpid()}"
    try:
        tmp.write_text(cleaned + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        jar.load(str(tmp), ignore_discard=True, ignore_expires=True)
    finally:
        tmp.unlink(missing_ok=True)

    if not any(c.name == "_web_session" for c in jar):
        sys.exit(
            f"{cookie_path}: não achei o cookie _web_session de www.waze.com. "
            "Exporte os cookies com a sessão do waze.com aberta."
        )
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def fetch(opener, params: dict, attempts: int = 4) -> dict:
    """Um GET, com throttle e backoff exponencial."""
    url = f"{API}?{urllib.parse.urlencode(params)}"
    for attempt in range(attempts):
        with _throttle:
            gap = time.monotonic() - _last_call[0]
            if gap < DELAY:
                time.sleep(DELAY - gap)
            _last_call[0] = time.monotonic()

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "Referer": "https://www.waze.com/leaderboard",
            },
        )
        try:
            with opener.open(req, timeout=30) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                sys.exit(f"HTTP {exc.code} — sessão expirada. Atualize os cookies.")
            if attempt == attempts - 1:
                print(f"  ! desisti de {params}: {exc}", file=sys.stderr)
                return {"record": []}
            time.sleep((2 ** attempt) + random.random())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == attempts - 1:
                print(f"  ! desisti de {params}: {exc}", file=sys.stderr)
                return {"record": []}
            time.sleep((2 ** attempt) + random.random())
    return {"record": []}


# ------------------------------------------------------------------------ coleta

def collect(opener, period: str, quiet: bool = False) -> list[dict]:
    """Varre o ranking nacional e os 27 estaduais e devolve os editores."""
    boards = [None] + UFS  # None = nacional
    editors: dict[str, dict] = {}
    lock = threading.Lock()
    done = [0]

    def work(uf: str | None) -> None:
        params = {
            "lookbackPeriod": period,
            "countryCode": "BR",
            "show_editor_levels": "true",
        }
        if uf:
            params["stateCode"] = f"BR-{uf}"
        rows = fetch(opener, params).get("record") or []

        with lock:
            for raw in rows:
                uid = raw.get("userId")
                edits = int(raw.get("mapEditCount") or 0)
                # No modo período, mapEditCount são as edições da janela; zero
                # significa que a pessoa pontuou dirigindo, não editando.
                if not uid or edits <= 0:
                    continue
                cur = editors.setdefault(
                    uid,
                    {
                        "userId": uid,
                        "username": raw.get("username") or "?",
                        # `level` some do registro de quem nunca editou.
                        "level": int(raw["level"]) if raw.get("level") else None,
                        "edits": edits,
                        "points": int(raw.get("points") or 0),
                        "uf": None,
                    },
                )
                cur["edits"] = max(cur["edits"], edits)
                cur["points"] = max(cur["points"], int(raw.get("points") or 0))
                if uf:
                    cur["uf"] = uf
            done[0] += 1
            if not quiet:
                print(
                    f"  [{done[0]:2d}/{len(boards)}] {period:<10} "
                    f"{uf or 'BR':<3} linhas={len(rows):3d} editores={len(editors)}",
                    file=sys.stderr,
                )

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(work, boards))

    ranked = sorted(editors.values(), key=lambda r: -r["edits"])
    for i, row in enumerate(ranked, 1):
        row["rank"] = i
    return ranked


# ------------------------------------------------------------------------- saída

def print_table(rows: list[dict], period: str, top: int) -> None:
    print(f"\n{PERIODS[period]} — {len(rows)} editores")
    print(f"{'#':>4}  {'edições':>9}  {'nv':>2}  {'UF':<2}  editor")
    for r in rows[:top]:
        lvl = r["level"] if r["level"] is not None else "-"
        print(f"{r['rank']:>4}  {r['edits']:>9}  {lvl:>2}  {r['uf'] or '--':<2}  "
              f"{r['username']}")


PAGE = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Placar dos Editores do Waze — Brasil</title>
<style>
  :root {
    --bg:#f6f8fa; --card:#fff; --ink:#12212e; --muted:#5b6b7a; --line:#e3e9ef;
    --accent:#0b7fd4; --bar:#cfe8fa; --chip:#eef3f7;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0d1519; --card:#141f26; --ink:#e6eef4; --muted:#8ba3b4;
            --line:#22323d; --accent:#3ec6f5; --bar:#1b3f55; --chip:#1b2a33; }
  }
  :root[data-theme="light"] {
    --bg:#f6f8fa; --card:#fff; --ink:#12212e; --muted:#5b6b7a; --line:#e3e9ef;
    --accent:#0b7fd4; --bar:#cfe8fa; --chip:#eef3f7;
  }
  :root[data-theme="dark"] {
    --bg:#0d1519; --card:#141f26; --ink:#e6eef4; --muted:#8ba3b4;
    --line:#22323d; --accent:#3ec6f5; --bar:#1b3f55; --chip:#1b2a33;
  }
  * { box-sizing:border-box }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif }
  .wrap { max-width:1000px; margin:0 auto; padding:28px 18px 64px }
  h1 { font-size:1.6rem; margin:0 0 4px; letter-spacing:-.02em }
  .sub { color:var(--muted); font-size:.9rem; margin:0 0 22px }
  .tabs { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:16px }
  .tab { border:1px solid var(--line); background:var(--card); color:var(--muted);
         padding:8px 16px; border-radius:999px; cursor:pointer; font-size:.9rem;
         font-weight:600 }
  .tab[aria-selected="true"] { background:var(--accent); border-color:var(--accent);
                               color:#fff }
  .stats { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:16px }
  .stat { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:10px 14px; min-width:120px }
  .stat b { display:block; font-size:1.25rem; letter-spacing:-.02em }
  .stat span { color:var(--muted); font-size:.75rem; text-transform:uppercase;
               letter-spacing:.05em }
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
  .medal { font-size:1rem }
  .name { font-weight:600; width:99%; white-space:normal }
  .chip { background:var(--chip); border-radius:5px; padding:1px 7px;
          font-size:.75rem; color:var(--muted); font-weight:600 }
  .barcell { width:120px; min-width:120px; padding-left:0 }
  .bar { height:6px; border-radius:3px; background:var(--bar); min-width:2px }
  .empty { padding:28px; text-align:center; color:var(--muted) }
  footer { margin-top:22px; color:var(--muted); font-size:.8rem }
  footer p { margin:.45em 0 }
  code { background:var(--chip); padding:1px 5px; border-radius:4px; font-size:.9em }
</style>

<div class="wrap">
  <h1>Placar dos Editores do Waze</h1>
  <p class="sub">Brasil &middot; gerado em __STAMP__ a partir da API pública do Waze</p>

  <div class="tabs" id="tabs"></div>
  <div class="stats" id="stats"></div>

  <div class="controls">
    <input id="q" type="search" placeholder="Procurar editor…" autocomplete="off">
    <select id="uf"></select>
  </div>

  <div class="tablewrap">
    <table>
      <thead><tr>
        <th class="pos">#</th><th>Editor</th><th>UF</th><th>Nível</th>
        <th class="num">Edições</th><th class="barcell"></th>
        <th class="num">Pontos</th>
      </tr></thead>
      <tbody id="body"></tbody>
    </table>
    <div class="empty" id="empty" hidden>Nenhum editor encontrado.</div>
  </div>

  <footer>
    <p><b>Como é montado.</b> Cada janela é varrida em 28 rankings — o nacional e
    os 27 estaduais. A API entrega no máximo 500 linhas por ranking, então a
    varredura estadual é o que amplia a cobertura. Como os rankings estaduais não
    se sobrepõem, a UF de cada editor vem da varredura.</p>
    <p><b>O que fica de fora.</b> Os rankings do Waze ordenam por pontos —
    dirigir e editar somados — e não por edições. Em janelas curtas as 500 vagas
    enchem de motorista, então <i>Semana</i> e <i>Mês</i> mostram bem menos gente
    que <i>Histórico</i>. Quem editou pouco no período pode não aparecer.</p>
    <p>Dados de <code>www.waze.com/_user/api/leaderboard</code>. Página estática,
    sem servidor e sem banco.</p>
  </footer>
</div>

<script>
const DATA = __DATA__;
const NF = new Intl.NumberFormat("pt-BR");
const MEDALS = ["\\u{1F947}", "\\u{1F948}", "\\u{1F949}"];
let period = Object.keys(DATA.periods)[0];

const $ = (id) => document.getElementById(id);

function rows() {
  const q = $("q").value.trim().toLowerCase();
  const uf = $("uf").value;
  return DATA.periods[period].rows.filter(
    (r) => (!uf || r[4] === uf) && (!q || r[1].toLowerCase().includes(q))
  );
}

function render() {
  const list = rows();
  const max = list.length ? Math.max(...list.map((r) => r[2])) : 1;
  $("body").innerHTML = list
    .map((r) => {
      const [pos, name, edits, points, uf, level] = r;
      const medal = pos <= 3 ? `<span class="medal">${MEDALS[pos - 1]}</span> ` : "";
      const pct = Math.max(2, Math.round((edits / max) * 100));
      return `<tr>
        <td class="pos">${medal}${pos}</td>
        <td class="name">${name}</td>
        <td><span class="chip">${uf || "--"}</span></td>
        <td>${level ? `<span class="chip">N${level}</span>` : ""}</td>
        <td class="num">${NF.format(edits)}</td>
        <td class="barcell"><div class="bar" style="width:${pct}%"></div></td>
        <td class="num">${NF.format(points)}</td>
      </tr>`;
    })
    .join("");
  $("empty").hidden = list.length > 0;

  const total = list.reduce((a, r) => a + r[2], 0);
  const ufs = new Set(list.map((r) => r[4]).filter(Boolean));
  $("stats").innerHTML = [
    [NF.format(list.length), "editores"],
    [NF.format(total), "edições na janela"],
    [ufs.size, "estados"],
  ]
    .map(([v, k]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`)
    .join("");
}

function build() {
  $("tabs").innerHTML = Object.entries(DATA.periods)
    .map(
      ([k, v]) =>
        `<button class="tab" role="tab" data-k="${k}" aria-selected="${k === period}">
           ${v.label} <span style="opacity:.65">${NF.format(v.rows.length)}</span>
         </button>`
    )
    .join("");
  $("tabs").onclick = (e) => {
    const b = e.target.closest(".tab");
    if (!b) return;
    period = b.dataset.k;
    [...$("tabs").children].forEach((t) =>
      t.setAttribute("aria-selected", t.dataset.k === period)
    );
    fillUfs();
    render();
  };
  fillUfs();
  $("q").oninput = render;
  $("uf").onchange = render;
  render();
}

function fillUfs() {
  const keep = $("uf").value;
  const ufs = [...new Set(DATA.periods[period].rows.map((r) => r[4]).filter(Boolean))].sort();
  $("uf").innerHTML =
    `<option value="">Todos os estados</option>` +
    ufs.map((u) => `<option${u === keep ? " selected" : ""}>${u}</option>`).join("");
}

build();
</script>
"""


def build_html(collected: dict[str, list[dict]], stamp: str) -> str:
    payload = {
        "periods": {
            period: {
                "label": PERIODS[period],
                # Compacto de propósito: posição, nome, edições, pontos, UF, nível.
                "rows": [
                    [r["rank"], r["username"], r["edits"], r["points"],
                     r["uf"], r["level"]]
                    for r in rows
                ],
            }
            for period, rows in collected.items()
        }
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # `</script>` dentro do JSON encerraria o bloco cedo demais.
    data = data.replace("</", "<\\/")
    return PAGE.replace("__DATA__", data).replace("__STAMP__", html.escape(stamp))


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--cookies",
        default=os.environ.get("WAZE_COOKIES", DEFAULT_COOKIES),
        help=f"arquivo de cookies Netscape (padrão: {DEFAULT_COOKIES})",
    )
    ap.add_argument(
        "--period",
        choices=list(PERIODS),
        action="append",
        help="limita as janelas coletadas (repetível; padrão: todas)",
    )
    ap.add_argument("--out", default=str(ROOT / "placar.html"), help="HTML de saída")
    ap.add_argument("--json", dest="json_out", help="grava também os dados crus")
    ap.add_argument("--print", action="store_true", help="tabela no terminal")
    ap.add_argument("--top", type=int, default=25, help="linhas com --print")
    ap.add_argument("--quiet", action="store_true", help="sem progresso")
    args = ap.parse_args()

    opener = load_opener(args.cookies)
    periods = args.period or list(PERIODS)

    collected: dict[str, list[dict]] = {}
    for period in periods:
        collected[period] = collect(opener, period, quiet=args.quiet)

    if args.print:
        for period in periods:
            print_table(collected[period], period, args.top)
        return

    now = dt.datetime.now().astimezone()
    stamp = now.strftime("%d/%m/%Y %H:%M %Z").strip()

    out = Path(args.out)
    out.write_text(build_html(collected, stamp), encoding="utf-8")
    size = out.stat().st_size / 1024

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(
                {"gerado_em": now.isoformat(timespec="seconds"), "periodos": collected},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    print(f"\n{out}  ({size:.0f} KB)", file=sys.stderr)
    for period in periods:
        rows = collected[period]
        edits = sum(r["edits"] for r in rows)
        print(
            f"  {PERIODS[period]:<10} {len(rows):5d} editores  "
            f"{edits:>12,} edições".replace(",", "."),
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
