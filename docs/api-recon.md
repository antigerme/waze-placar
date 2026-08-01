# Waze Leaderboard API — recon notes

Reverse-engineered from the live SPA at <https://www.waze.com/leaderboard>
(bundle `https://web-assets.waze.com/orbit/leaderboard-*.js`).

The page was never deleted — only de-linked from Waze's navigation. It still
renders and its backing API still serves data.

## Endpoint

```
GET https://www.waze.com/_user/api/leaderboard
```

Authentication is by session cookie (`_web_session` on `www.waze.com`).
No `Authorization` header, no CSRF token needed for `GET`.

### Query parameters

| Param                    | Values                        | Effect |
|--------------------------|-------------------------------|--------|
| `countryCode`            | ISO 3166-1 alpha-2 (`BR`)     | National board |
| `stateCode`              | **ISO 3166-2** (`BR-SP`)      | Subdivision board; requires `countryCode` |
| `wazerCountryLeaderboard`| `true`                        | National board for the *caller's own* country |
| `show_editor_levels`     | `true` / `false`              | **No observable effect** — `level` is always returned |
| `lookbackPeriod`         | any string                    | **Ignored** — see below |

Omitting all of them returns the global board.

### Response

```jsonc
{
  "record": [
    {
      "userId":       "88679",
      "points":       "23753477",   // cumulative Waze points (driving + editing)
      "username":     "asterix06",
      "moodUrl":      "https://dexter.waze.com/4/2239/$mood.mood_id/x3_ui.png",
      "countryCode":  "IT",
      "mapEditCount": "6500610",
      "level":        "6"           // editor level 1-6
    }
    // ... up to 500
  ],
  "wazerDetails": { /* same shape, for the authenticated caller */ },
  "rank": 3                          // caller's rank within this board
}
```

All numeric fields are **strings**. `moodUrl` contains a literal
`$mood.mood_id` placeholder that the client substitutes.

## Findings that shape the design

### 1. `lookbackPeriod` is dead

`LAST_7_DAYS`, `LAST_30_DAYS`, `ALL_TIME`, `WEEK`, and even `bogus` all return
byte-identical payloads. The client still sends it, but the server ignores it.

**Consequence:** the API only exposes *cumulative all-time* totals. Any
"edits this week/month" view has to be derived by **snapshotting over time and
diffing** — that is the core reason this project needs its own datastore.

### 2. Hard cap of 500 rows, no pagination

`offset`, `page`, `limit`, `count`, and `start` are all ignored; every board
returns exactly 500 rows (or 0 for an unknown code).

### 3. Boards are ranked by `points`, not by edits

`points` is the unified Waze score (driving *and* editing). The global top 500
therefore mixes mega-editors with heavy commuters — 241 of the global 500 have
fewer than 100 map edits, and the #500 slot belongs to a user with **2** edits.

**Consequence:** a genuine *editors* board must re-sort by `mapEditCount`, and
must not treat the global board as a representative sample of editors.

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

National + 6 states = **3061 distinct editors** instead of 500. All 27 BR
subdivisions should yield ~12–13k, and a global sweep across every country and
subdivision is the path to six-figure coverage.

Subdivision codes must be full ISO 3166-2 — `BR-SP` works, bare `SP` returns 0
rows, as do `California` and numeric codes.

### 5. No rate limiting observed

12 back-to-back requests all returned `200`. The harvester still throttles
deliberately — this is someone else's infrastructure and a full global sweep is
thousands of requests.

## Sibling endpoints

Also referenced by the bundle:

- `/_user/api/user` — the caller's own profile. **Ignores a `userId` param**,
  so it is not an arbitrary-user lookup. Returns real PII for the caller
  (surname, city, last known lat/lon, last login), so keep it out of any
  harvested dataset.
- `/_user/api/trip`
- `/_user/api/notifications/preferences`

## Open questions for the HAR capture

The Champs-facing data source is not part of this SPA. Worth looking for in the
capture: a per-user edit *history* (which would remove the need for snapshot
diffing), anything with a working date range, and whether it exposes editors
outside the top 500 of any board.
