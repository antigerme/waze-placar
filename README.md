# waze-placar

Reviving the Waze map editors' leaderboard.

Waze retired the public editors' board, but `https://www.waze.com/leaderboard`
was only de-linked — the page and its backing API are still live. This project
harvests that API and rebuilds the scoreboard the community lost.

## State of play

Recon on the live API is done, verified against a HAR capture of the real
client, and documented in [`docs/api-recon.md`](docs/api-recon.md). A working
harvester is in [`scripts/harvest.py`](scripts/harvest.py).

The HAR turned up no Champs-only data source — it drives the same public
`/_user/api/leaderboard` that the ordinary SPA does. So that endpoint is the
whole game for now.

## What the upstream API gives us, and what it hides

**Three time windows, plus a trap.** `ALL_TIME`, `PAST_WEEK` and `PAST_MONTH`
work. Every other value — `PAST_YEAR`, `LAST_7_DAYS`, or plain garbage — returns
the `ALL_TIME` payload with a `200` and no error. Probing the parameter with
invented values makes it look inert when it isn't; the harvester pins the enum
client-side so that cannot happen twice.

**Every board caps at 500 rows.** No pagination parameter works. The way around
it is geographic sharding: each country and each ISO 3166-2 subdivision is its
own 500-row board, and they overlap far less than you would expect. A Brazil
sweep — national plus 27 states, 28 requests — yields **13,498 distinct users,
2,179 with at least one map edit**, against a 500-row ceiling.

**Boards rank by points, not by edits.** `points` is Waze's combined
driving-and-editing score, so commuters compete with editors for the 500 slots.
241 of the global top 500 have fewer than 100 map edits. A real editors' board
re-sorts by `mapEditCount` and drops zero-edit rows.

**Short windows are mostly drivers.** That last problem gets much worse the
shorter the window: editors are 45% of the BR all-time board but only 8% of the
BR monthly one. Sweeping all 28 Brazil boards for `PAST_MONTH` surfaces just
**77** active editors, against 2,179 tracked all-time — roughly 3.5% of the
editor base.

So the built-in windows are a zero-latency convenience, not the product. The
authoritative period ranking comes from snapshotting `ALL_TIME` on a schedule
and diffing, which catches every editor who moved and works for windows the API
has no enum for.

## Usage

Requires Python 3.11+ and no third-party packages. Authentication is a logged-in
`waze.com` session cookie, exported in Netscape format.

```bash
export WAZE_COOKIES=/path/to/cookies.txt

# read one board live, no snapshot
python3 scripts/harvest.py board --period PAST_WEEK --country BR
python3 scripts/harvest.py board --period PAST_MONTH            # global

# harvest one country (national board + every known subdivision)
python3 scripts/harvest.py sweep --country BR

# harvest everything in data/subdivisions.json, plus the global board
python3 scripts/harvest.py sweep --all

# find which subdivision codes a country actually serves, and record them
python3 scripts/harvest.py discover --country IT

# derive a window from two all-time sweeps
python3 scripts/harvest.py diff data/snapshots/ALL_TIME/2026-08-01.jsonl \
                                data/snapshots/ALL_TIME/2026-08-08.jsonl --top 50
```

Snapshots land in `data/snapshots/<period>/<date>.jsonl` — one JSON object per
line, sorted by edit count, preceded by a `_meta` line. Two Brazil baselines
are committed so the first diff has something to compare against.

`diff` refuses anything but `ALL_TIME` snapshots: only cumulative totals can be
meaningfully subtracted.

`data/subdivisions.json` currently covers BR, US, CA and MX. Extend it by hand
or with `discover`.

## Notes

- Cookies are session credentials. `.gitignore` blocks `cookies*.txt`, `*.har`
  and `.env`; keep it that way.
- The harvester throttles to ~3 requests/second across 4 workers and backs off
  on failure. No rate limiting was observed upstream, but a global sweep is
  thousands of requests against infrastructure that isn't ours.
- `/_user/api/user` and `/il-UsersProfile/app/userInfo` return real PII for the
  *authenticated caller only* — full name, email, city, last known coordinates.
  Both ignore a `userId` parameter, so neither is a lookup for other users, and
  nothing from them belongs in a harvested dataset.
- `level` is absent from a record when the user has never edited. Don't assume
  the key exists.

## Next

- Start the scheduled `ALL_TIME` sweep — the diff-based rankings are worth
  nothing until two snapshots exist, so the clock should start early.
- Fill out `data/subdivisions.json` beyond BR/US/CA/MX with `discover`.
- Decide the storage model, then the public site.
- Still open: whether any Champs-only feed exists with per-user edit history or
  reach beyond the top 500. Nothing in the capture pointed at one.
