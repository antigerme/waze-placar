#!/usr/bin/env python3
"""Coleta o perfil de cada editor brasileiro do placar.

O perfil traz 91 dias de edições diárias por editor, o que o placar não dá:
os rankings de janela do Waze ordenam por pontos e cortam em 500, então a aba
Mês enxerga ~77 editores. Com os perfis dá para ranquear os 2.179 pela
atividade real.

São ~2.200 requisições por execução. O ritmo é deliberadamente lento e com
jitter — a infraestrutura é do Waze, não nossa.

Uso:
    python3 scripts/perfis.py                      # varre o placar e coleta
    python3 scripts/perfis.py --out perfis.jsonl
    python3 scripts/perfis.py --limit 50           # amostra, para testar
"""

import argparse
import datetime as dt
import gzip
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
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import placar  # noqa: E402  (reaproveita cookies, throttle e a varredura)

PROFILE = "https://www.waze.com/Descartes/app/UserProfile/Profile"
AREAS = "https://www.waze.com/Descartes/app/UserProfile/Areas"

# Ritmo global: um pedido a cada 0,45–1,15 s, distribuído entre os workers.
# Dá ~1,3 req/s, uns 28 min para 2.200 perfis.
WORKERS = 3
GAP_MIN = 0.45
GAP_MAX = 1.15

_gate = threading.Lock()
_next_at = [0.0]


def wait_turn() -> None:
    """Throttle global com jitter — nunca dois pedidos em cadência fixa."""
    with _gate:
        now = time.monotonic()
        start = max(now, _next_at[0])
        _next_at[0] = start + random.uniform(GAP_MIN, GAP_MAX)
    delay = start - now
    if delay > 0:
        time.sleep(delay)


def get_json(opener, url: str, params: dict, referer: str,
             attempts: int = 3) -> Optional[dict]:
    full = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(attempts):
        wait_turn()
        req = urllib.request.Request(full, headers={
            "User-Agent": placar.UA,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Referer": referer,
        })
        try:
            with opener.open(req, timeout=30) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                sys.exit("HTTP 403 — sessão expirada. Atualize os cookies.")
            # 500 é o que o Waze devolve para usuário inexistente; não insiste.
            if exc.code == 500:
                return None
            if attempt == attempts - 1:
                return None
            time.sleep((2 ** attempt) + random.random())
        except (OSError, json.JSONDecodeError):
            if attempt == attempts - 1:
                return None
            time.sleep((2 ** attempt) + random.random())
    return None


def slim(username: str, d: dict) -> dict:
    """Guarda só o que interessa, já normalizado."""
    act = d.get("editingActivity") or []
    return {
        "userId": d.get("userID"),
        "username": d.get("username") or username,
        # o perfil chama de rank o que o placar chama de level, menos 1
        "level": (d["rank"] + 1) if isinstance(d.get("rank"), int) else None,
        "edits": d.get("edits") or 0,
        "points": d.get("points") or 0,
        "firstEditDate": d.get("firstEditDate"),
        "forumPosts": d.get("forumPosts") or 0,
        "isMentor": bool(d.get("isMentor")),
        "menteesCount": d.get("menteesCount") or 0,
        "mentees": [
            {"userId": m.get("userId"), "username": m.get("userName"),
             "edits": m.get("edits"), "level": (m["rank"] + 1)
             if isinstance(m.get("rank"), int) else None,
             "menteeStartDate": m.get("menteeStartDate")}
            for m in (d.get("mentees") or [])
        ],
        "editsByType": {e["key"]: e["value"]["count"]
                        for e in (d.get("editsByType") or [])
                        if isinstance(e.get("value"), dict)},
        "lastEditEnv": d.get("lastEditEnv"),
        # índice 0 = 90 dias atrás, último = hoje (parcial)
        "activity": act,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cookies", default=os.environ.get(
        "WAZE_COOKIES", placar.DEFAULT_COOKIES))
    ap.add_argument("--out", default="perfis.jsonl")
    ap.add_argument("--from-json", help="lê a lista de editores de um JSON já coletado")
    ap.add_argument("--limit", type=int, help="coleta só os N primeiros")
    ap.add_argument("--areas", action="store_true",
                    help="busca também as áreas gerenciadas (dobra as requisições)")
    args = ap.parse_args()

    opener = placar.load_opener(args.cookies)

    if args.from_json:
        raw = json.load(open(args.from_json, encoding="utf-8"))
        rows = raw["periodos"]["ALL_TIME"] if "periodos" in raw else raw
        editores = [r["username"] for r in rows]
    else:
        print("varrendo o placar para listar os editores…", file=sys.stderr)
        rows, failed = placar.collect(opener, "ALL_TIME", quiet=True)
        if failed:
            print(f"  aviso: {len(failed)} ranking(s) falharam", file=sys.stderr)
        editores = [r["username"] for r in rows]

    if args.limit:
        editores = editores[:args.limit]

    # Ordem embaralhada: nada de varrer o ranking de cima para baixo.
    ordem = list(editores)
    random.shuffle(ordem)

    out = Path(args.out)
    feitos = set()
    if out.exists():
        with out.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    feitos.add(json.loads(line)["username"])
                except Exception:
                    pass
        print(f"retomando: {len(feitos)} já coletados", file=sys.stderr)
    pendentes = [u for u in ordem if u not in feitos]

    inicio = time.time()
    est = len(pendentes) * ((GAP_MIN + GAP_MAX) / 2)
    print(f"{len(pendentes)} perfis a coletar, {WORKERS} workers, "
          f"~{est/60:.0f} min estimados", file=sys.stderr)

    lock = threading.Lock()
    fh = out.open("a", encoding="utf-8")
    contas = {"ok": 0, "falha": 0}

    def work(username: str) -> None:
        ref = "https://www.waze.com/user/editor/" + urllib.parse.quote(username)
        d = get_json(opener, PROFILE, {"username": username}, ref)
        if d is None:
            with lock:
                contas["falha"] += 1
            return
        rec = slim(username, d)
        if args.areas and rec["userId"]:
            a = get_json(opener, AREAS, {"userID": rec["userId"]}, ref)
            rec["managedAreas"] = (a or {}).get("managedAreas") or []
        with lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            contas["ok"] += 1
            n = contas["ok"] + contas["falha"]
            if n % 25 == 0 or n == len(pendentes):
                dec = time.time() - inicio
                taxa = n / dec if dec else 0
                resta = (len(pendentes) - n) / taxa if taxa else 0
                print(f"  {n:5d}/{len(pendentes)}  ok={contas['ok']} "
                      f"falha={contas['falha']}  {taxa:.2f} req/s  "
                      f"faltam ~{resta/60:.0f} min", file=sys.stderr)

    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(work, pendentes))
    finally:
        fh.close()

    dur = time.time() - inicio
    print(f"\n{out}  {contas['ok']} perfis, {contas['falha']} falhas, "
          f"{dur/60:.1f} min", file=sys.stderr)


if __name__ == "__main__":
    main()
