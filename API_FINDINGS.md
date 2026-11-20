# Warcraft Logs API findings (Nov 17, 2026)

Tested live against Taftonator-Dalaran (US) with the "M+ Parse Average" API client.

## Zone and dungeons
- Live M+ zone: **55 = "Mythic+ Season 2"** (Midnight). Zone 56 is the PTR copy and 49 is Beta, so skip zones with "PTR"/"Beta" in the name.
- Season 2 dungeon encounter IDs: 12993 Altar of Fangs, 12825 Den of Nalorakk, 61762 Kings' Rest,
  12813 Murder Row, 112521 Ruby Life Pools, 61877 Temple of Sethraliss, 12859 The Blinding Vale, 12923 Voidscar Arena.

## The right query
`character(name, serverSlug, serverRegion) { encounterRankings(encounterID: X, metric: dps, byBracket: true) }`
- Returns **every logged run** (not just the best) in `ranks[]`.
- `ranks[].bracketData` = **keystone level** of that run.
- `ranks[].rankPercent` = DPS parse vs. the same spec **at that same key level** (when byBracket: true).
- Also per run: `amount` (DPS), `duration` (ms), `startTime`, `spec`, `report.code`, `report.fightID`.

## Gotchas
1. **Default metric for M+ is `playerscore`** (M+ score), not DPS. Always pass `metric: dps` (healers: `hps`).
2. **Without `byBracket: true`, the percentile mostly tracks key level**: every +15 lands at ~80, every +14 at ~75,
   +13 at ~70, +11 at ~40, regardless of DPS. Useless for comparing players. With byBracket the same runs read
   82 / 52 / 52 / 71 / 57 / 89 = real performance.
3. **Duplicate runs**: the same run can appear twice when two group members upload it (e.g. Murder Row +15:
   255,280 vs 255,259 DPS, identical 2075s duration, different report codes). Dedupe by dungeon + key + duration
   (± a few seconds) + start time.
4. Private/hidden characters return `character: null`.

## Cost
- Free client limit: **1000 points/hour**.
- One full character lookup (8 dungeons) costs ~10 points, so ~100 player lookups/hour per user key. Plenty.

## Taftonator sample (same-key DPS parse average)
| Key | Runs | Avg |
|---|---|---|
| +10 | 6 | 64.4 |
| +11 | 3 | 74.2 |
| +12 | 7 | 56.4 |
| +13 | 5 | 60.5 |
| +14 | 6 | 53.3 |
| +15 | 9 (one is a duplicate) | 55.2 |
| +16 | 1 | 4.4 |
| +17 | 1 | 45.4 |
