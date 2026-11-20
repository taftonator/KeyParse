"""
wcl_probe.py - Step 1 test for the M+ parse-average addon companion.

What it does:
  1. Gets a Warcraft Logs API token using your client ID + secret.
  2. Finds the current Mythic+ zone and its dungeons.
  3. Pulls one character's M+ rankings and saves the raw JSON,
     so we can see whether per-run key levels come back.

Usage:
  python wcl_probe.py <CharacterName> <realm-slug> <region>
  e.g. python wcl_probe.py Taftonator area-52 us

First run creates config.json - paste your client_id and client_secret in it.
Never upload config.json anywhere (it's your private key).
"""
import json
import sys
from pathlib import Path

import requests

TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
API_URL = "https://www.warcraftlogs.com/api/v2/client"
HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.json"
OUTPUT = HERE / "probe_output.json"


def load_creds():
    if not CONFIG.exists():
        CONFIG.write_text(json.dumps({"client_id": "", "client_secret": ""}, indent=2))
        sys.exit(f"Created {CONFIG.name}. Paste your client_id and client_secret into it, then run again.")
    cfg = json.loads(CONFIG.read_text())
    if not cfg.get("client_id") or not cfg.get("client_secret"):
        sys.exit(f"Fill in client_id and client_secret in {CONFIG.name}, then run again.")
    return cfg["client_id"], cfg["client_secret"]


def get_token(client_id, client_secret):
    r = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def gql(token, query, variables=None):
    r = requests.post(
        API_URL,
        json={"query": query, "variables": variables or {}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise RuntimeError("API returned errors:\n" + json.dumps(body["errors"], indent=2))
    return body["data"]


ZONES_QUERY = """
query {
  worldData {
    expansions {
      id
      name
      zones { id name encounters { id name } }
    }
  }
  rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }
}
"""

# %s gets replaced with one encounterRankings line per dungeon
CHARACTER_QUERY = """
query($name: String!, $server: String!, $region: String!, $zone: Int!) {
  characterData {
    character(name: $name, serverSlug: $server, serverRegion: $region) {
      name
      classID
      zoneRankings(zoneID: $zone)
%s
    }
  }
  rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }
}
"""


def find_mplus_zone(world):
    """Newest expansion's highest-ID live 'Mythic+' zone (skips PTR and Beta zones)."""
    expansions = sorted(world["expansions"], key=lambda e: e["id"], reverse=True)
    for exp in expansions:
        mplus = [
            z for z in exp["zones"]
            if "mythic+" in z["name"].lower()
            and "ptr" not in z["name"].lower()
            and "beta" not in z["name"].lower()
        ]
        if mplus:
            return exp["name"], max(mplus, key=lambda z: z["id"])
    return None, None


def main():
    if len(sys.argv) != 4:
        sys.exit("Usage: python wcl_probe.py <CharacterName> <realm-slug> <region>")
    name, server, region = sys.argv[1], sys.argv[2].lower(), sys.argv[3].lower()

    client_id, client_secret = load_creds()
    token = get_token(client_id, client_secret)
    print("Got API token.")

    zones = gql(token, ZONES_QUERY)
    exp_name, zone = find_mplus_zone(zones["worldData"])
    if not zone:
        sys.exit("Couldn't find a Mythic+ zone. Zone list saved for inspection.")
    print(f"M+ zone: {zone['name']} (id {zone['id']}, {exp_name})")
    for enc in zone["encounters"]:
        print(f"  dungeon {enc['id']}: {enc['name']}")

    # metric: dps + byBracket: true = DPS percentile vs. the same spec at the SAME key level.
    # Without byBracket, M+ percentiles mostly just track key level (every 15 lands near 80).
    enc_lines = "\n".join(
        f"      d{enc['id']}: encounterRankings(encounterID: {enc['id']}, metric: dps, byBracket: true)"
        for enc in zone["encounters"]
    )
    data = gql(
        token,
        CHARACTER_QUERY % enc_lines,
        {"name": name, "server": server, "region": region, "zone": zone["id"]},
    )

    OUTPUT.write_text(json.dumps({"zones": zones, "zone_used": zone, "character": data}, indent=2))
    print(f"\nSaved raw results to {OUTPUT.name}")

    char = data["characterData"]["character"]
    if char is None:
        print("Character not found (wrong name/realm/region, or their logs are hidden).")
    else:
        print(f"\nCharacter: {char['name']}")
        by_key = {}
        for enc in zone["encounters"]:
            block = char.get(f"d{enc['id']}") or {}
            ranks = block.get("ranks") or []
            print(f"  {enc['name']}: {len(ranks)} ranked runs")
            for run in ranks:
                by_key.setdefault(run["bracketData"], []).append(run["rankPercent"])
        print("\nKey level  runs  avg DPS parse (same-key bracket)")
        for key in sorted(by_key):
            vals = by_key[key]
            print(f"  +{key:<7} {len(vals):>4}  {sum(vals) / len(vals):5.1f}")

    rl = data["rateLimitData"]
    print(f"\nAPI points used this hour: {rl['pointsSpentThisHour']} / {rl['limitPerHour']}"
          f" (resets in {rl['pointsResetIn']}s)")


if __name__ == "__main__":
    main()
