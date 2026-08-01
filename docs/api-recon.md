# Waze Leaderboard API — recon notes

Reverse-engineered from the live SPA at <https://www.waze.com/leaderboard>
(bundle `https://web-assets.waze.com/orbit/leaderboard-*.js`), then corrected
against a HAR capture of the real client driving the UI.

The page was never deleted — only de-linked from Waze's navigation. It still
renders and its backing API still serves data.

## Endpoint

```
GET https://www.waze.com/_user/api/leaderboard
```

Authentication is by session cookie (`_web_session` on `www.waze.com`).
No `Authorization` header, no CSRF token needed for `GET`.

### Query parameters

| Param                    | Values                                      | Effect |
|--------------------------|---------------------------------------------|--------|
| `lookbackPeriod`         | `ALL_TIME`, `PAST_WEEK`, `PAST_MONTH`       | Time window. **Anything else silently falls back to `ALL_TIME`** |
| `countryCode`            | ISO 3166-1 alpha-2 (`BR`)                   | National board |
| `stateCode`              | **ISO 3166-2** (`BR-SP`)                    | Subdivision board; requires `countryCode` |
| `wazerCountryLeaderboard`| `true`                                      | National board for the *caller's own* country |
| `show_editor_levels`     | `true` / `false`                            | **No observable effect** — `level` is returned either way |

Omitting the geography parameters returns the global board.

The page itself takes matching parameters, so boards are deep-linkable:
`/leaderboard?region=BR&province=BR-BA&lookbackPeriod=PAST_MONTH`
(`region=GLOBAL` and `province=ALL` are the wildcards).

### Response

```jsonc
{
  "record": [
    {
      "userId":       "88679",
      "points":       "23753477",   // Waze points (driving + editing) in window
      "username":     "asterix06",
      "moodUrl":      "https://dexter.waze.com/4/2239/$mood.mood_id/x3_ui.png",
      "countryCode":  "IT",
      "mapEditCount": "6500610",    // map edits in window
      "level":        "6"           // editor level 1-6; ABSENT for non-editors
    }
    // ... up to 500
  ],
  "wazerDetails": { /* same shape, for the authenticated caller */ },
  "rank": 3                          // caller's rank; absent on subdivision boards
}
```

All numeric fields are **strings**. `moodUrl` contains a literal
`$mood.mood_id` placeholder that the client substitutes.

**`level` is optional per record**, not per response — it appears only for users
who have actually edited. In the global `ALL_TIME` board, exactly the 355 users
with `mapEditCount > 0` carry a `level`; the other 145 omit the key entirely.
Parsers must not assume it exists.

## Findings that shape the design

### 1. Three real windows, and a silent-fallback trap

`ALL_TIME`, `PAST_WEEK` and `PAST_MONTH` return genuinely different data. Every
other value — `PAST_YEAR`, `PAST_DAY`, `TODAY`, `LAST_7_DAYS`, or outright
garbage — returns the `ALL_TIME` payload with a `200`, no error, no warning.

That fallback is the single easiest way to draw a wrong conclusion from this
API: probing it with invented enum values makes the parameter look inert. The
harvester enforces the enum client-side for exactly this reason.

### 2. Hard cap of 500 rows, no pagination

`offset`, `page`, `limit`, `count`, and `start` are all ignored; every board
returns exactly 500 rows (or 0 for an unknown code).

### 3. Boards rank by `points`, not by edits

`points` is the unified Waze score, earned from driving *and* editing, and it
is the sort key on every board. So the 500 slots are contested by commuters as
well as editors. On the global `ALL_TIME` board 241 of the 500 have fewer than
100 map edits, and the #500 slot belongs to a user with **2**.

A real editors' board therefore has to re-sort by `mapEditCount` and discard
zero-edit rows.

### 4. Geographic sharding defeats the 500 cap

Each subdivision is its own 500-row board with heavy non-overlap:

| Board        | rows | new vs. national |
|--------------|------|------------------|
| BR national  | 500  | —                |
| BR-SP        | 500  | 208              |
| BR-RJ        | 500  | 435              |
| BR-MG        | 500  | 481              |
| BR-BA        | 500  | 488              |
| BR-RS        | 500  | 467              |
| BR-PR        | 500  | 482              |

A full Brazil sweep — national plus all 27 subdivisions, 28 requests — yields
**13,498 distinct users, 2,179 of them with at least one edit**.

Subdivision codes must be full ISO 3166-2 — `BR-SP` works, bare `SP` returns 0
rows, as do `California` and numeric codes.

### 5. Editor density collapses on short windows — the reason to still snapshot

Because boards sort by points, a short window fills up with drivers. Measured
editor share of the 500 rows:

| Board                 | ALL_TIME | PAST_WEEK | PAST_MONTH |
|-----------------------|----------|-----------|------------|
| Global                | 71.0%    | 61.6%     | 60.0%      |
| BR national           | 45.0%    | 10.4%     | 8.2%       |
| BR-SP                 | —        | 2.0%      | —          |
| BR-BA                 | —        | —         | 1.0%       |

The effect compounds across a sweep. The same 28-board Brazil sweep returns:

- `ALL_TIME` → **2,179** editors
- `PAST_MONTH` → **77** active editors

So Waze's own monthly board surfaces roughly 3.5% of Brazil's tracked editor
base. Diffing two `ALL_TIME` snapshots a month apart instead reveals every one
of the 2,179 who edited in between.

**Design consequence:** `PAST_WEEK`/`PAST_MONTH` are a zero-latency convenience
worth exposing, but the authoritative period ranking comes from snapshot
diffing. Diffing also unlocks windows the API has no enum for.

### 6. No rate limiting observed

12 back-to-back requests all returned `200`. The harvester still throttles
deliberately — this is someone else's infrastructure and a global sweep is
thousands of requests.

## Sibling endpoints

- `/_user/api/user` and `/il-UsersProfile/app/userInfo` — the caller's own
  profile. Both **ignore a `userId` param**, so neither is an arbitrary-user
  lookup. Both return real PII for the caller: full name, email, city, last
  known coordinates, last login. Nothing from them belongs in a dataset.
- `/web_api/request_info?source=cookie_consent` — geo-IP for the caller;
  returns `region` (`BR`) and `regionSubdivision` (`BRBA`, note: no hyphen,
  so it needs reformatting before use as a `stateCode`). Useful for defaulting
  a visitor to their local board.
- `/_user/api/trip`, `/_user/api/notifications/preferences` — not explored.

## Assets

- Mood icons: `https://dexter.waze.com/4/<moodId>/$mood.mood_id/x3_ui.png` —
  the `$mood.mood_id` segment is sent literally by the browser.
- Profile photos: `https://profileimages.waze.co.il/SocialMediaServer/images/profile/<uuid>`,
  available only via the caller's own profile payload.

## Still unknown

No Champs-only data source appeared in the capture — the HAR is the same public
`/_user/api/leaderboard` the anonymous SPA uses. Nothing observed exposes
per-user edit *history*, nor any editor outside a board's top 500. If a
separate Champs feed exists it lives somewhere this capture didn't touch.
