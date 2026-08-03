#!/usr/bin/env python3
"""Cliente da API do Waze: sessão, ritmo e as duas coletas.

Não tem CLI. É usado por placar.py (gera a página) e por perfis.py (coleta
avulsa para pesquisa).
"""

import gzip
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
# Anotações via typing, e não list[...]/X | Y, para rodar no Python 3.6 que vem
# de fábrica no RHEL 8 — lá /usr/bin/python3 ainda é o 3.6.
from typing import Dict, List, Optional, Tuple

LEADERBOARD = "https://www.waze.com/_user/api/leaderboard"
PROFILE = "https://www.waze.com/Descartes/app/UserProfile/Profile"
AREAS = "https://www.waze.com/Descartes/app/UserProfile/Areas"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

DEFAULT_COOKIES = "/tmp/cookies.txt"

# As únicas três janelas que o servidor honra. Qualquer outro valor volta como
# ALL_TIME com status 200, sem erro — por isso o enum é fixo aqui.
PERIODS = ("ALL_TIME", "PAST_MONTH", "PAST_WEEK")

UFS = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
    "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
    "SE", "SP", "TO",
]

WORKERS = 3
# Ritmo global com jitter: um pedido a cada 0,45–1,15 s no conjunto, e não por
# worker, para o tráfego agregado nunca virar cadência fixa.
GAP_MIN = 0.45
GAP_MAX = 1.15

_gate = threading.Lock()
_next_at = [0.0]


class SemPermissao(Exception):
    """401/403 — a sessão não vale para este endpoint.

    Não é a mesma coisa para todo mundo: o backend Descartes, que serve os
    perfis, expira antes do /_user/api que serve os rankings, e responde
    "This operation is not allowed by guest user". Dá para o placar continuar
    válido enquanto os perfis já não são acessíveis, então quem chama decide o
    que fazer.
    """


def wait_turn():
    with _gate:
        now = time.monotonic()
        start = max(now, _next_at[0])
        _next_at[0] = start + random.uniform(GAP_MIN, GAP_MAX)
    delay = start - now
    if delay > 0:
        time.sleep(delay)


def _unlink(path):
    """Path.unlink(missing_ok=...) só chegou no 3.8."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def load_opener(cookie_path: str) -> urllib.request.OpenerDirector:
    """Abre a sessão a partir de um arquivo de cookies no formato Netscape."""
    path = Path(cookie_path)
    if not path.exists():
        sys.exit("{}: arquivo de cookies não encontrado.".format(cookie_path))

    jar = http.cookiejar.MozillaCookieJar()
    # MozillaCookieJar ignora as linhas "#HttpOnly_" que o curl escreve.
    cleaned = "\n".join(
        line[len("#HttpOnly_"):] if line.startswith("#HttpOnly_") else line
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
    )
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / ".waze-cookies-{}".format(os.getpid())
    try:
        tmp.write_text(cleaned + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        jar.load(str(tmp), ignore_discard=True, ignore_expires=True)
    finally:
        _unlink(tmp)

    if not any(c.name == "_web_session" for c in jar):
        sys.exit(
            "{}: não achei o cookie _web_session de www.waze.com. "
            "Exporte os cookies com a sessão do waze.com aberta.".format(cookie_path)
        )
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.waze_jar = jar
    op.waze_cookies = Path(cookie_path)
    op.waze_sessao = _sessao(jar)
    return op


def _sessao(jar) -> Optional[str]:
    for c in jar:
        if c.name == "_web_session":
            return c.value
    return None


def salva_cookies(opener) -> bool:
    """Grava o jar de volta no arquivo, para a sessão renovada sobreviver.

    O Waze responde os perfis com Set-Cookie de _web_session: a sessão é
    rolante. Sem gravar, toda execução parte do cookie exportado à mão e a
    sessão envelhece até morrer — que é o motivo de precisar reexportar.

    Escreve num temporário e renomeia por cima, com modo 0600: uma queda no
    meio da gravação não pode deixar o arquivo de credencial pela metade.
    """
    jar = getattr(opener, "waze_jar", None)
    destino = getattr(opener, "waze_cookies", None)
    if jar is None or destino is None:
        return False
    if _sessao(jar) == getattr(opener, "waze_sessao", None):
        return False                      # nada renovou; não mexe no arquivo

    tmp = destino.with_name("." + destino.name + ".tmp")
    try:
        jar.save(str(tmp), ignore_discard=True, ignore_expires=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, destino)
        return True
    except OSError as exc:
        # Cookie não gravado não invalida a coleta — só avisa e segue.
        print("  aviso: não consegui gravar {}: {}".format(destino, exc),
              file=sys.stderr)
        _unlink(tmp)
        return False


def fetch(opener, url: str, params: dict, referer: str,
          attempts: int = 3) -> Optional[dict]:
    """Um GET com throttle, jitter e backoff. None = desistiu."""
    full = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(attempts):
        wait_turn()
        req = urllib.request.Request(full, headers={
            "User-Agent": UA,
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
            if exc.code in (401, 403):
                raise SemPermissao("HTTP {} em {}".format(exc.code, url))
            # 500 é o que o Waze devolve para usuário inexistente; não insiste.
            if exc.code == 500:
                return None
            if attempt == attempts - 1:
                return None
            time.sleep((2 ** attempt) + random.random())
        # OSError cobre URLError, socket.timeout e queda de conexão. No 3.6
        # socket.timeout ainda não é TimeoutError, então OSError é o que
        # funciona em todas as versões.
        except (OSError, json.JSONDecodeError):
            if attempt == attempts - 1:
                return None
            time.sleep((2 ** attempt) + random.random())
    return None


# ------------------------------------------------------------------- placar

def coleta_placar(opener, period="ALL_TIME",
                  quiet=False) -> Tuple[List[dict], List[str]]:
    """Varre o ranking nacional e os 27 estaduais.

    Os rankings estaduais são mutuamente exclusivos, então a UF de cada editor
    sai de graça. Devolve os editores e os rankings que não responderam.
    """
    boards = [None] + UFS
    editores = {}       # type: Dict[str, dict]
    falhas = []         # type: List[str]
    lock = threading.Lock()
    feitos = [0]

    def work(uf):
        params = {"lookbackPeriod": period, "countryCode": "BR",
                  "show_editor_levels": "true"}
        if uf:
            params["stateCode"] = "BR-" + uf
        data = fetch(opener, LEADERBOARD, params,
                     "https://www.waze.com/leaderboard")
        if data is None:
            with lock:
                falhas.append("{}/{}".format(period, uf or "BR"))
                feitos[0] += 1
            return
        rows = data.get("record") or []
        with lock:
            for raw in rows:
                uid = raw.get("userId")
                edits = int(raw.get("mapEditCount") or 0)
                if not uid or edits <= 0:
                    continue
                cur = editores.setdefault(uid, {
                    "userId": uid,
                    "username": raw.get("username") or "?",
                    # `level` some do registro de quem nunca editou.
                    "level": int(raw["level"]) if raw.get("level") else None,
                    "edits": edits,
                    "points": int(raw.get("points") or 0),
                    "uf": None,
                })
                cur["edits"] = max(cur["edits"], edits)
                if uf:
                    cur["uf"] = uf
            feitos[0] += 1
            if not quiet:
                print("  [{:2d}/{}] {:<10} {:<3} linhas={:3d} editores={}".format(
                    feitos[0], len(boards), period, uf or "BR", len(rows),
                    len(editores)), file=sys.stderr)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(work, boards))

    ranked = sorted(editores.values(), key=lambda r: -r["edits"])
    return ranked, falhas


# ------------------------------------------------------------------- perfis

def normaliza_perfil(username: str, d: dict) -> dict:
    """Achata o perfil. `count` de editsByType vem nulo com frequência."""
    tipos = {}
    for e in (d.get("editsByType") or []):
        v = e.get("value") or {}
        if isinstance(v.get("count"), int):
            tipos[e["key"]] = v["count"]
    return {
        "userId": d.get("userID"),
        "username": d.get("username") or username,
        # o perfil chama de rank o que o placar chama de level, menos 1
        "level": (d["rank"] + 1) if isinstance(d.get("rank"), int) else None,
        "edits": d.get("edits") or 0,
        "points": d.get("points") or 0,
        "firstEditDate": d.get("firstEditDate"),
        "isMentor": bool(d.get("isMentor")),
        "menteesCount": d.get("menteesCount") or 0,
        "editsByType": tipos,
        # índice 0 = 90 dias atrás, último = hoje (parcial)
        "activity": d.get("editingActivity") or [],
    }


def coleta_perfil(opener, username: str) -> Optional[dict]:
    ref = "https://www.waze.com/user/editor/" + urllib.parse.quote(username)
    d = fetch(opener, PROFILE, {"username": username}, ref)
    return normaliza_perfil(username, d) if d else None


def coleta_perfis(opener, usernames, quiet=False,
                  on_result=None) -> Tuple[List[dict], bool]:
    """Busca os perfis em ordem embaralhada, para não varrer o ranking em
    sequência. `on_result` recebe cada perfil assim que chega.

    Devolve (perfis, sem_permissao). Se a sessão perder acesso ao Descartes no
    meio, para de emitir pedidos em vez de insistir 2.000 vezes contra um 403.
    """
    ordem = list(usernames)
    random.shuffle(ordem)

    out = []
    lock = threading.Lock()
    contas = {"ok": 0, "falha": 0}
    barrado = threading.Event()
    inicio = time.time()

    def work(u):
        if barrado.is_set():
            return
        try:
            p = coleta_perfil(opener, u)
        except SemPermissao:
            if not barrado.is_set():
                barrado.set()
                print("  ! o Descartes passou a responder 403 — parando os "
                      "perfis aqui", file=sys.stderr)
            return
        with lock:
            if p is None:
                contas["falha"] += 1
            else:
                out.append(p)
                contas["ok"] += 1
                if on_result:
                    on_result(p)
            n = contas["ok"] + contas["falha"]
            if not quiet and (n % 50 == 0 or n == len(ordem)):
                dec = time.time() - inicio
                taxa = n / dec if dec else 0
                resta = (len(ordem) - n) / taxa if taxa else 0
                print("  perfis {:5d}/{}  ok={} falha={}  {:.2f} req/s  "
                      "faltam ~{:.0f} min".format(n, len(ordem), contas["ok"],
                                                  contas["falha"], taxa,
                                                  resta / 60), file=sys.stderr)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(work, ordem))
    return out, barrado.is_set()
