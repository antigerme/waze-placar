#!/usr/bin/env python3
"""Coleta avulsa de perfis, para pesquisa.

O placar já busca os perfis por conta própria; isto aqui existe para coletar
uma vez e reaproveitar (placar.py --perfis), ou para analisar os dados crus.
Retomável: relendo o JSONL, pula quem já foi coletado.

Uso:
    python3 scripts/perfis.py --out perfis.jsonl
    python3 scripts/perfis.py --out perfis.jsonl --limit 50
    python3 scripts/perfis.py --usuario antigerme --usuario JohnyGrasel
"""

import argparse
import atexit
import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import waze  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cookies", default=os.environ.get(
        "WAZE_COOKIES", waze.DEFAULT_COOKIES))
    ap.add_argument("--out", default="perfis.jsonl")
    ap.add_argument("--usuario", action="append",
                    help="coleta só estes (repetível); sem isso, varre o placar")
    ap.add_argument("--limit", type=int, help="coleta só os N maiores")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    opener = waze.load_opener(args.cookies)
    atexit.register(lambda: waze.salva_cookies(opener))

    if args.usuario:
        alvos = args.usuario
    else:
        if not args.quiet:
            print("varrendo o placar para listar os editores…", file=sys.stderr)
        try:
            editores, falhas = waze.universo(opener, quiet=True)
        except waze.SemPermissao as exc:
            sys.exit("{} — sessão expirada. Atualize {}.".format(exc, args.cookies))
        if falhas:
            print("  aviso: {} ranking(s) falharam".format(len(falhas)),
                  file=sys.stderr)
        alvos = [e["username"] for e in editores]
    if args.limit:
        alvos = alvos[:args.limit]

    out = Path(args.out)
    feitos = set()
    if out.exists():
        with out.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    feitos.add(json.loads(line)["username"])
                except Exception:
                    pass
        print("retomando: {} já coletados".format(len(feitos)), file=sys.stderr)
    pendentes = [u for u in alvos if u not in feitos]

    fh = out.open("a", encoding="utf-8")
    lock = threading.Lock()

    def grava(p):
        with lock:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
            fh.flush()

    try:
        perfis, barrado = waze.coleta_perfis(opener, pendentes,
                                             quiet=args.quiet, on_result=grava)
    finally:
        fh.close()

    if barrado:
        print("  ! interrompido: o Descartes recusou a sessão. Atualize os "
              "cookies e rode de novo — a coleta retoma de onde parou.",
              file=sys.stderr)
    print("\n{}  {} perfis novos, {} no total".format(
        out, len(perfis), len(feitos) + len(perfis)), file=sys.stderr)


if __name__ == "__main__":
    main()
