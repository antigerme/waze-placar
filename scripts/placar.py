#!/usr/bin/env python3
"""Gera o placar dos editores de mapa do Waze no Brasil.

Sem banco, sem estado. Duas coletas ao vivo:

  1. os 28 rankings (nacional + 27 UFs) dizem quem são os editores e de onde;
  2. o perfil de cada um traz os últimos 91 dias de edições diárias.

A página resultante ordena por atividade recente, e não pelo acumulado desde
2011 — o acumulado premia quem já parou.

Uso:
    python3 scripts/placar.py --out /var/www/waze-placar/index.html
    python3 scripts/placar.py --sem-perfis        # rápido, só o acumulado
    python3 scripts/placar.py --perfis perfis.jsonl   # reaproveita uma coleta
"""

import argparse
import datetime as dt
import json
import atexit
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pagina  # noqa: E402
import waze  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def write_atomic(path: Path, text: str) -> None:
    """Publica a página de uma vez só, para nunca servir HTML pela metade.

    O temporário fica no mesmo diretório de propósito: um arquivo movido de
    /tmp carrega o rótulo SELinux de lá, e o httpd responderia 403 ao tentar
    servi-lo. O chmod é explícito porque a umask do cron pode ser restritiva.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        waze._unlink(tmp)
        raise


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cookies", default=os.environ.get(
        "WAZE_COOKIES", waze.DEFAULT_COOKIES),
        help="arquivo de cookies Netscape (padrão: {})".format(waze.DEFAULT_COOKIES))
    ap.add_argument("--out", default=str(ROOT / "placar.html"), help="HTML de saída")
    ap.add_argument("--perfis", help="JSONL de perfis já coletados, em vez de buscar")
    ap.add_argument("--sem-perfis", action="store_true", dest="sem_perfis",
                    help="pula os perfis; a página sai só com o acumulado")
    ap.add_argument("--salvar-perfis", dest="salvar",
                    help="grava os perfis coletados neste JSONL")
    ap.add_argument("--limit", type=int, help="usa só os N maiores (para teste)")
    ap.add_argument("--allow-partial", action="store_true",
                    help="publica mesmo se algum ranking falhar")
    ap.add_argument("--nao-salvar-cookies", action="store_true",
                    dest="nao_salvar_cookies",
                    help="não regrava o arquivo de cookies com a sessão renovada")
    ap.add_argument("--sem-areas", action="store_true", dest="sem_areas",
                    help="pula áreas gerenciadas e edições recentes "
                         "(~600 requisições a menos)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    inicio = time.time()
    opener = waze.load_opener(args.cookies)
    # A sessão é rolante: gravar o jar de volta é o que evita ter de reexportar
    # os cookies à mão. Vale mesmo se a coleta abortar no meio.
    if not args.nao_salvar_cookies:
        atexit.register(lambda: waze.salva_cookies(opener))

    if not args.quiet:
        print("varrendo os rankings (28 por janela, 3 janelas)…", file=sys.stderr)
    try:
        editores, falhas, estat = waze.universo(opener, quiet=args.quiet)
    except waze.SemPermissao as exc:
        sys.exit("{} — sessão expirada. Atualize {}.".format(exc, args.cookies))
    if falhas and not args.allow_partial:
        sys.exit(
            "{} ranking(s) não responderam: {}\nNada foi publicado — a página "
            "anterior continua no lugar. Use --allow-partial para publicar mesmo "
            "assim.".format(len(falhas), ", ".join(falhas)))
    if args.limit:
        editores = editores[:args.limit]

    ufs = {e["username"]: e["uf"] for e in editores}

    if args.perfis:
        perfis = [json.loads(l) for l in Path(args.perfis).open(encoding="utf-8")]
        perfis = [p for p in perfis if p["username"] in ufs]
        if not args.quiet:
            print("{} perfis lidos de {}".format(len(perfis), args.perfis),
                  file=sys.stderr)
    elif args.sem_perfis:
        # Sem atividade diária: a página mostra só o acumulado.
        perfis = [{"username": e["username"], "level": e["level"],
                   "edits": e["edits"], "activity": [], "firstEditDate": None,
                   "menteesCount": 0} for e in editores]
    else:
        if not args.quiet:
            print("buscando {} perfis (~{:.0f} min)…".format(
                len(editores),
                len(editores) * ((waze.GAP_MIN + waze.GAP_MAX) / 2) / 60),
                file=sys.stderr)
        salvar = Path(args.salvar).open("w", encoding="utf-8") if args.salvar else None

        def grava(p):
            if salvar:
                salvar.write(json.dumps(p, ensure_ascii=False) + "\n")
                salvar.flush()

        try:
            perfis, barrado = waze.coleta_perfis(
                opener, [e["username"] for e in editores],
                quiet=args.quiet, on_result=grava)
        finally:
            if salvar:
                salvar.close()

        # O Descartes expira antes do /_user/api: dá para varrer os rankings e
        # ainda assim não conseguir um perfil. Publicar assim trocaria a página
        # de ontem por uma sem as abas de atividade, que é o conteúdo principal.
        if barrado and len(perfis) < len(editores) * 0.9:
            sys.exit(
                "só {} de {} perfis coletados antes do Descartes recusar a "
                "sessão.\nNada foi publicado — a página anterior continua no "
                "lugar. Atualize {} (o backend de perfis expira antes do de "
                "rankings) ou rode com --sem-perfis.".format(
                    len(perfis), len(editores), args.cookies))

    # Quem não teve perfil coletado ainda entra na página, só sem atividade.
    vistos = {p["username"] for p in perfis}
    for e in editores:
        if e["username"] not in vistos:
            perfis.append({"username": e["username"], "level": e["level"],
                           "edits": e["edits"], "activity": [],
                           "firstEditDate": None, "menteesCount": 0})

    # Afilhados citados que não estão no universo do placar. Sem eles a
    # comparação de mentoria mede só quem já apareceu num ranking, que é
    # justamente quem produziu — viés que inverteria a conclusão.
    extras = {}
    if not args.sem_perfis:
        # Primeiro a lista completa de afilhados, que o perfil corta em 10.
        mentores = [(p["username"], p.get("userId")) for p in perfis
                    if p.get("menteesCount") and p.get("userId")]
        if mentores:
            if not args.quiet:
                print("buscando afilhados de {} mentores…".format(len(mentores)),
                      file=sys.stderr)
            completos = waze.coleta_mentees(opener, mentores, quiet=args.quiet)
            for p in perfis:
                if p["username"] in completos:
                    p["mentees"] = completos[p["username"]]

        vistos_n = {p["username"] for p in perfis}
        faltam = sorted({m["username"] for p in perfis
                         for m in (p.get("mentees") or [])
                         if m.get("username") and m["username"] not in vistos_n})
        if faltam:
            if not args.quiet:
                print("buscando {} afilhados fora do universo…".format(len(faltam)),
                      file=sys.stderr)
            achados, _ = waze.coleta_perfis(opener, faltam, quiet=args.quiet)
            extras = {a["username"]: a for a in achados}

    # Áreas só dos ativos: o mapa é sobre quem cuida da região hoje, e são
    # ~165 requisições em vez de 2.200.
    areas = {}
    if not args.sem_areas:
        ativos = [(p["username"], p.get("userId")) for p in perfis
                  if sum((p.get("activity") or [0])[:-1]) > 0 and p.get("userId")]
        if ativos:
            if not args.quiet:
                print("buscando áreas de {} editores ativos…".format(len(ativos)),
                      file=sys.stderr)
            areas = waze.coleta_areas(opener, ativos, quiet=args.quiet)

    transacoes = []
    if not args.sem_areas:
        alvos_tx = [(p["username"], p.get("userId")) for p in perfis
                    if sum((p.get("activity") or [0])[:-1]) > 0 and p.get("userId")]
        if alvos_tx:
            if not args.quiet:
                print("buscando edições recentes de {} editores…".format(len(alvos_tx)),
                      file=sys.stderr)
            transacoes = waze.coleta_transacoes(opener, alvos_tx, quiet=args.quiet)

    agora = dt.datetime.now().astimezone()
    dados = pagina.prepara(perfis, ufs, agora.strftime("%d/%m/%Y %H:%M %Z").strip(),
                           areas=areas, estat=estat, extras=extras,
                           transacoes=transacoes)

    out = Path(args.out)
    write_atomic(out, pagina.build_html(dados))

    r = dados["resumo"]
    print("\n{}  ({:.0f} KB, {:.0f} min)".format(
        out, out.stat().st_size / 1024, (time.time() - inicio) / 60),
        file=sys.stderr)
    print("  {} editores no histórico, {} ativos em 90 d, {} em 30 d".format(
        r["historico"], r["ativos90"], r["ativos30"]), file=sys.stderr)
    print("  {:,} edições em 90 dias, {}% concentradas em 50 pessoas".format(
        r["edicoes90"], r["top50"]).replace(",", "."), file=sys.stderr)


if __name__ == "__main__":
    main()
