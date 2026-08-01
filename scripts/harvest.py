#!/usr/bin/env python3
"""Harvest Waze editor leaderboards into dated snapshots.

The upstream API only serves cumulative all-time totals, 500 rows per board,
with no working date filter (see docs/api-recon.md). Two things follow:

  * coverage comes from sweeping many geographic shards and merging them;
  * "edits in a period" comes from diffing two snapshots taken days apart.

Usage:
    export WAZE_COOKIES=/path/to/cookies.txt        # Netscape format
    python3 scripts/harvest.py sweep --country BR
    python3 scripts/harvest.py sweep --all
    python3 scripts/harvest.py discover --country IT
    python3 scripts/harvest.py diff data/snapshots/2026-08-01.jsonl \
                                   data/snapshots/2026-08-08.jsonl
"""

from __future__ import annotations

import argparse
import datetime as dt
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

API = "https://www.waze.com/_user/api/leaderboard"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
ROOT = Path(__file__).resolve().parent.parent
SHARD_FILE = ROOT / "data" / "subdivisions.json"
SNAP_DIR = ROOT / "data" / "snapshots"

# Deliberate politeness. The API showed no rate limiting, but a global sweep is
# thousands of requests against infrastructure that is not ours.
WORKERS = 4
DELAY = 0.35

_throttle = threading.Lock()
_last_call = [0.0]


def load_opener(cookie_path: str) -> urllib.request.OpenerDirector:
    """Build an opener carrying the Waze session cookie."""
    jar = http.cookiejar.MozillaCookieJar()
    # MozillaCookieJar silently skips curl's "#HttpOnly_" lines; normalise first.
    cleaned = "\n".join(
        line[len("#HttpOnly_") :] if line.startswith("#HttpOnly_") else line
        for line in Path(cookie_path).read_text(encoding="utf-8").splitlines()
    )
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / f".waze-cookies-{os.getpid()}"
    tmp.write_text(cleaned + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
        jar.load(str(tmp), ignore_discard=True, ignore_expires=True)
    finally:
        tmp.unlink(missing_ok=True)

    if not any(c.name == "_web_session" for c in jar):
        sys.exit(
            f"{cookie_path}: no _web_session cookie for www.waze.com. "
            "Export cookies while logged in to waze.com."
        )
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def fetch(opener, params: dict, attempts: int = 4) -> dict:
    """GET one board, with throttling and exponential backoff."""
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
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403):
                sys.exit(f"HTTP {exc.code} — session cookie expired or invalid.")
            if attempt == attempts - 1:
                print(f"  ! giving up on {params}: {exc}", file=sys.stderr)
                return {"record": []}
            time.sleep((2**attempt) + random.random())
    return {"record": []}


def shard_params(shard: dict) -> dict:
    p = {"show_editor_levels": "true"}
    if shard.get("country"):
        p["countryCode"] = shard["country"]
    if shard.get("state"):
        p["stateCode"] = shard["state"]
    return p


def build_shards(spec: dict, countries: list[str] | None) -> list[dict]:
    """Global board + one board per country and per known subdivision."""
    shards = [{"country": None, "state": None, "label": "GLOBAL"}]
    for cc, subs in sorted(spec.items()):
        if countries and cc not in countries:
            continue
        shards.append({"country": cc, "state": None, "label": cc})
        for sub in subs:
            shards.append({"country": cc, "state": sub, "label": sub})
    if countries:
        shards = [s for s in shards if s["label"] != "GLOBAL"]
    return shards


def cmd_sweep(args) -> None:
    opener = load_opener(args.cookies)
    spec = json.loads(SHARD_FILE.read_text(encoding="utf-8"))
    countries = None if args.all else [c.upper() for c in (args.country or [])]
    if not args.all and not countries:
        sys.exit("pass --country BR (repeatable) or --all")

    shards = build_shards(spec, countries)
    print(f"sweeping {len(shards)} boards with {WORKERS} workers", file=sys.stderr)

    # userId -> best row seen. Boards disagree only by staleness, so keep the
    # row with the highest edit count.
    merged: dict[str, dict] = {}
    lock = threading.Lock()
    done = [0]

    def work(shard: dict) -> None:
        data = fetch(opener, shard_params(shard))
        rows = data.get("record") or []
        with lock:
            fresh = 0
            for row in rows:
                uid = row.get("userId")
                if not uid:
                    continue
                prev = merged.get(uid)
                if prev is None:
                    fresh += 1
                if prev is None or int(row["mapEditCount"]) > int(prev["mapEditCount"]):
                    merged[uid] = row
            done[0] += 1
            print(
                f"  [{done[0]:4d}/{len(shards)}] {shard['label']:<8} "
                f"rows={len(rows):3d} new={fresh:3d} total={len(merged)}",
                file=sys.stderr,
            )

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(work, shards))

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else SNAP_DIR / f"{stamp}.jsonl"
    captured = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    editors = [r for r in merged.values() if int(r["mapEditCount"]) > 0]
    editors.sort(key=lambda r: -int(r["mapEditCount"]))

    with out.open("w", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "_meta": {
                        "captured_at": captured,
                        "boards": len(shards),
                        "users_seen": len(merged),
                        "editors": len(editors),
                    }
                }
            )
            + "\n"
        )
        for rank, row in enumerate(editors, 1):
            fh.write(
                json.dumps(
                    {
                        "rank": rank,
                        "userId": row["userId"],
                        "username": row["username"],
                        "countryCode": row["countryCode"],
                        "level": int(row["level"]),
                        "mapEditCount": int(row["mapEditCount"]),
                        "points": int(row["points"]),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    print(
        f"\n{out}\n  {len(merged)} users seen, {len(editors)} with >0 edits",
        file=sys.stderr,
    )
    for row in editors[:10]:
        print(
            f"  {row['mapEditCount']:>9}  {row['username']} ({row['countryCode']})",
            file=sys.stderr,
        )


def cmd_discover(args) -> None:
    """Brute-force which ISO 3166-2 subdivision codes a country actually serves."""
    opener = load_opener(args.cookies)
    cc = args.country[0].upper()
    alphabet = [
        f"{a}{b}"
        for a in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for b in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    ] + [f"{n:02d}" for n in range(1, 100)]

    found: list[str] = []
    lock = threading.Lock()

    def probe(sfx: str) -> None:
        code = f"{cc}-{sfx}"
        data = fetch(opener, {"countryCode": cc, "stateCode": code,
                              "show_editor_levels": "true"})
        if data.get("record"):
            with lock:
                found.append(code)
                print(f"  {code}  rows={len(data['record'])}", file=sys.stderr)

    print(f"probing {len(alphabet)} candidate codes for {cc}", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(probe, alphabet))

    spec = json.loads(SHARD_FILE.read_text(encoding="utf-8"))
    spec[cc] = sorted(found)
    SHARD_FILE.write_text(
        json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(found)} codes for {cc} to {SHARD_FILE}", file=sys.stderr)


def read_snapshot(path: str) -> tuple[dict, dict[str, dict]]:
    meta: dict = {}
    rows: dict[str, dict] = {}
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            obj = json.loads(line)
            if "_meta" in obj:
                meta = obj["_meta"]
            else:
                rows[obj["userId"]] = obj
    return meta, rows


def cmd_diff(args) -> None:
    """The time-windowed board the API refuses to give us."""
    old_meta, old = read_snapshot(args.old)
    new_meta, new = read_snapshot(args.new)

    deltas = []
    for uid, row in new.items():
        before = old.get(uid)
        if before is None:
            continue  # new to the dataset; no baseline, so no honest delta
        gained = row["mapEditCount"] - before["mapEditCount"]
        if gained > 0:
            deltas.append({**row, "gained": gained})
    deltas.sort(key=lambda r: -r["gained"])

    print(f"{old_meta.get('captured_at','?')}  ->  {new_meta.get('captured_at','?')}")
    print(f"{len(old)} -> {len(new)} editors tracked, {len(deltas)} active\n")
    print(f"{'#':>4}  {'edits':>9}  {'total':>10}  {'cc':<3} user")
    for i, row in enumerate(deltas[: args.top], 1):
        print(
            f"{i:>4}  {row['gained']:>9}  {row['mapEditCount']:>10}  "
            f"{row['countryCode']:<3} {row['username']}"
        )

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "from": old_meta.get("captured_at"),
                    "to": new_meta.get("captured_at"),
                    "leaderboard": deltas,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {args.out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--cookies",
        default=os.environ.get("WAZE_COOKIES", ""),
        help="Netscape cookie file (or set WAZE_COOKIES)",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sw = sub.add_parser("sweep", help="harvest boards into a dated snapshot")
    sw.add_argument("--country", action="append", help="ISO alpha-2, repeatable")
    sw.add_argument("--all", action="store_true", help="every known country")
    sw.add_argument("--out", help="output path (default data/snapshots/<date>.jsonl)")
    sw.set_defaults(func=cmd_sweep)

    dc = sub.add_parser("discover", help="find valid subdivision codes")
    dc.add_argument("--country", action="append", required=True)
    dc.set_defaults(func=cmd_discover)

    df = sub.add_parser("diff", help="build a period leaderboard from two snapshots")
    df.add_argument("old")
    df.add_argument("new")
    df.add_argument("--top", type=int, default=50)
    df.add_argument("--out")
    df.set_defaults(func=cmd_diff)

    args = ap.parse_args()
    if args.cmd in ("sweep", "discover") and not args.cookies:
        sys.exit("set --cookies or WAZE_COOKIES")
    args.func(args)


if __name__ == "__main__":
    main()
