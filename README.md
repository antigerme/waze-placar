# waze-placar

Reviving the Waze map editors' leaderboard.

Waze retired the public editors' board, but `https://www.waze.com/leaderboard`
was only de-linked — the page and its backing API are still live. This project
harvests that API and rebuilds the scoreboard the community lost.

## State of play

Recon on the live API is done and documented in
[`docs/api-recon.md`](docs/api-recon.md). A working harvester is in
[`scripts/harvest.py`](scripts/harvest.py). What is *not* settled yet is the
Champs-facing data source — that is pending a HAR capture.

## Two problems the upstream API hands us

**It only knows all-time totals.** `lookbackPeriod` is accepted and then
ignored; `LAST_7_DAYS` and `ALL_TIME` return byte-identical payloads. So
"most edits this month" cannot be asked for — it has to be *derived*, by
snapshotting on a schedule and diffing. That is why this repo stores dated
snapshots rather than just proxying the API.

**It caps every board at 500 rows.** No pagination parameter works. The way
around it is geographic sharding: each country and each ISO 3166-2 subdivision
is its own 500-row board, and they overlap far less than you would expect. A
Brazil sweep — national plus 27 states, 28 requests — yields **13,498 distinct
users, 2,179 of them with at least one map edit**, against a 500-row ceiling.

One more trap: the boards rank by `points`, Waze's combined driving-and-editing
score, not by edits. 241 of the global top 500 have fewer than 100 map edits.
A real editors' board has to re-sort by `mapEditCount`.

## Usage

Requires Python 3.11+ and no third-party packages. Authentication is a logged-in
`waze.com` session cookie, exported in Netscape format.

```bash
export WAZE_COOKIES=/path/to/cookies.txt

# harvest one country (national board + every known subdivision)
python3 scripts/harvest.py sweep --country BR

# harvest everything in data/subdivisions.json, plus the global board
python3 scripts/harvest.py sweep --all

# find which subdivision codes a country actually serves, and record them
python3 scripts/harvest.py discover --country IT

# build the period leaderboard the API won't give us
python3 scripts/harvest.py diff data/snapshots/2026-08-01.jsonl \
                                data/snapshots/2026-08-08.jsonl --top 50
```

Snapshots land in `data/snapshots/<date>.jsonl` — one JSON object per line,
sorted by edit count, preceded by a `_meta` line. `data/snapshots/2026-08-01.jsonl`
is the Brazil baseline, committed so the first diff has something to compare to.

`data/subdivisions.json` currently covers BR, US, CA and MX. Extend it by hand
or with `discover`.

## Notes

- Cookies are session credentials. `.gitignore` blocks `cookies*.txt`, `*.har`
  and `.env`; keep it that way.
- The harvester throttles to ~3 requests/second across 4 workers and backs off
  on failure. No rate limiting was observed upstream, but a global sweep is
  thousands of requests against infrastructure that isn't ours.
- `/_user/api/user` returns real PII for the *authenticated caller only* —
  surname, city, last known coordinates. It ignores a `userId` parameter, so it
  is not a lookup for other users, and nothing from it belongs in a harvested
  dataset.

## Next

- Confirm what the Champs data source offers once the HAR lands — specifically
  whether it carries per-user edit *history* (which would make snapshot diffing
  unnecessary) and whether it reaches editors outside any board's top 500.
- Decide the storage model, then the scheduled sweep, then the public site.
