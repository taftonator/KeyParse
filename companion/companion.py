"""
KeyParse companion - fetches Warcraft Logs M+ parses for the KeyParse addon.

How it works:
  1. In game, the KeyParse addon saves "please look up Name-Realm" requests
     into its SavedVariables file (written by WoW on /reload or logout).
  2. This app watches that file, looks each player up on Warcraft Logs with
     YOUR free API key, and averages their same-key DPS/HPS parses per key level.
  3. Results go into Interface/AddOns/KeyParse/Data.lua, which the addon loads
     on the next /reload.

Usage:
  python companion.py                      watch for in-game requests (default)
  python companion.py lookup Name-Realm    look players up right now (testing)
  python companion.py setup                re-enter API key / WoW folder
  python companion.py autostart on|off     start (minimized) when you log in to Windows

Get an API key (client ID + secret) at https://www.warcraftlogs.com/api/clients
"""
import json
import re
import sys
import threading
import time
from pathlib import Path

import requests

ADDON = "KeyParse"
TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
API_URL = "https://www.warcraftlogs.com/api/v2/client"

HERE = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def _data_dir():
    """Where config/cache/log live: %LOCALAPPDATA%\\KeyParse. Not next to the program: a Microsoft Store app's
    install folder is read-only (and Windows quietly redirects this folder into the app's own storage)."""
    import os
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "KeyParse" if base else HERE


DATA_DIR = _data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
CACHE_PATH = DATA_DIR / "cache.json"
LOG_PATH = DATA_DIR / "companion_log.txt"
OLD_FILES = ("config.json", "cache.json", "companion_log.txt")  # kept next to the program up to 0.6.11

REGIONS = {"us": 1, "kr": 2, "eu": 3, "tw": 4, "cn": 5}
HEALER_SPECS = {"Restoration", "Holy", "Discipline", "Mistweaver", "Preservation"}
TANK_SPECS = {"Protection", "Blood", "Guardian", "Brewmaster", "Vengeance"}

SINGLE_INSTANCE_PORT = 47613  # local-only port held while the companion runs, so a second copy exits
POLL_SECONDS = 0.5        # how often to check the SavedVariables file
WORKERS = 2               # players looked up at the same time (more trips Warcraft Logs' load limit)
DATA_VERSION = 2           # 2 = includes per-dungeon parses for every key level
DB_LIMIT_RECHECK = 120     # while Warcraft Logs says "no database points remaining", check again this often
CACHE_MAX_AGE = 24 * 3600   # results are deleted after a day (Warcraft Logs' API terms limit keeping copies)
ERROR_RETRY_AFTER = 10 * 60  # retry a lookup that failed for a non-temporary reason after 10 minutes
ZONE_REFRESH = 24 * 3600  # re-check the current M+ season once a day
RATE_LIMIT_BUFFER = 25    # stop this many points short of the hourly cap


# ---------------------------------------------------------------- config / cache

_log_lock = threading.Lock()


def log(msg):
    """Print and append to companion_log.txt (kept small), so problems can be checked later."""
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    with _log_lock:
        print(line)
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            if LOG_PATH.exists() and LOG_PATH.stat().st_size > 200_000:
                LOG_PATH.replace(LOG_PATH.with_suffix(".old.txt"))
            with LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d ") + line + "\n")
        except OSError:
            pass


def log_exception(msg):
    """Log an unexpected error with its full traceback (so it can be diagnosed from companion_log.txt)."""
    import traceback
    log(msg)
    for line in traceback.format_exc().rstrip().splitlines():
        log("    " + line)


# Something the player has to fix (e.g. a rejected API key). Written into the data slots so the addon can
# say it in game; cleared again as soon as a lookup works.
PROBLEM = {"text": ""}
AUTH_RECHECK = 5 * 60  # with a rejected API key: check config.json for a new one this often


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    if isinstance(data, dict) and "players" in data and "prune_expired" in globals():
        prune_expired(data)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    replace_with_retry(tmp, path)


def replace_with_retry(tmp, target, tries=6):
    """Atomic rename; on Windows it fails while another program (antivirus, OneDrive, WoW) has the target
    open, so try again for a moment before giving up."""
    for attempt in range(tries):
        try:
            tmp.replace(target)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.25 * (attempt + 1))


def find_wow_retail():
    """Find the World of Warcraft _retail_ folder (registry first, then common spots)."""
    candidates = []
    try:
        import winreg
        for hive, key in [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Blizzard Entertainment\World of Warcraft"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Blizzard Entertainment\World of Warcraft"),
        ]:
            try:
                with winreg.OpenKey(hive, key) as k:
                    candidates.append(Path(winreg.QueryValueEx(k, "InstallPath")[0]))
            except OSError:
                pass
    except ImportError:
        pass  # not Windows
    for drive in "CDEFG":
        candidates += [
            Path(f"{drive}:/Program Files (x86)/World of Warcraft"),
            Path(f"{drive}:/Program Files/World of Warcraft"),
            Path(f"{drive}:/World of Warcraft"),
            Path(f"{drive}:/Games/World of Warcraft"),
        ]
    candidates.append(Path("/Applications/World of Warcraft"))
    for c in candidates:
        for p in (c, c / "_retail_"):
            if p.name == "_retail_" and (p / "Interface").exists() and (p / "WTF").exists():
                return p
    return None


def migrate_old_files(old_dir=None, new_dir=None):
    """Move config/cache/log from next to the program (up to 0.6.11) into DATA_DIR, once. Never overwrites."""
    import shutil
    old_dir, new_dir = old_dir or HERE, new_dir or DATA_DIR
    if old_dir.resolve() == new_dir.resolve():
        return []
    new_dir.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in OLD_FILES:
        old, new = old_dir / name, new_dir / name
        if old.exists() and not new.exists():
            try:
                shutil.move(str(old), str(new))
                moved.append(name)
            except OSError:
                pass  # e.g. read-only folder: the old copy just stays where it is
    return moved


def is_packaged():
    """True when running as the Microsoft Store (MSIX) app."""
    try:
        import ctypes
        length = ctypes.c_uint32(0)
        rc = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None)
        return rc != 15700  # APPMODEL_ERROR_NO_PACKAGE: a normal, unpackaged program
    except Exception:
        return False


STORE_STARTUP_HINT = ("The Store version of the KeyParse companion starts with Windows by itself. "
                      "Turn that on or off under Windows Settings > Apps > Startup.")


def startup_launcher_path():
    import os
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "KeyParse Companion.bat"


def set_autostart(enabled):
    """Add/remove a tiny launcher in the Windows Startup folder that opens the companion minimized at login."""
    if is_packaged():  # a Store app can't use the Startup folder; its package declares a startup task instead
        print(STORE_STARTUP_HINT)
        return
    path = startup_launcher_path()
    if path is None:
        print("Start with Windows is only available on Windows.")
        return
    if not enabled:
        if path.exists():
            path.unlink()
        print("KeyParse companion will no longer start with Windows.")
        return
    if getattr(sys, "frozen", False):        # the .exe build
        target = f'"{sys.executable}"'
    else:                                     # running from companion.py
        pyw = Path(sys.executable)
        target = f'"{pyw}" "{Path(__file__).resolve()}"'
    path.write_text("@echo off\r\n"
                    "rem Starts the KeyParse companion minimized when you log in. Delete this file to stop that.\r\n"
                    f'start "KeyParse Companion" /min {target}\r\n', encoding="utf-8")
    print(f"KeyParse companion will start (minimized) when you log in to Windows.\n  Launcher: {path}")


def setup(cfg):
    print("\n=== KeyParse companion setup ===")
    print("Create a free API client at https://www.warcraftlogs.com/api/clients")
    print("(any name, redirect URL http://localhost, leave 'Public Client' unchecked)\n")
    cid = input(f"Client ID [{cfg.get('client_id', '')}]: ").strip() or cfg.get("client_id", "")
    sec = input("Client secret [keep current]: ").strip() or cfg.get("client_secret", "")
    found = find_wow_retail()
    default = cfg.get("wow_retail_path") or (str(found) if found else "")
    path = input(f"WoW _retail_ folder [{default}]: ").strip().strip('"') or default
    cfg.update({"client_id": cid, "client_secret": sec, "wow_retail_path": path})
    save_json(CONFIG_PATH, cfg)
    print(f"Saved {CONFIG_PATH.name}.\n")
    if is_packaged():
        print(STORE_STARTUP_HINT + "\n")
    elif startup_launcher_path() and not startup_launcher_path().exists():
        if input("Start the companion automatically when you log in to Windows? [Y/n]: ").strip().lower() != "n":
            set_autostart(True)
    return cfg


def load_config(force_setup=False):
    cfg = load_json(CONFIG_PATH, {})
    if force_setup or not cfg.get("client_id") or not cfg.get("client_secret"):
        cfg = setup(cfg)
    if not cfg.get("wow_retail_path"):
        found = find_wow_retail()
        if found:
            cfg["wow_retail_path"] = str(found)
            save_json(CONFIG_PATH, cfg)
    return cfg


# ---------------------------------------------------------------- Warcraft Logs API

class TransientError(Exception):
    """Warcraft Logs is busy, rate limited or unreachable: try the same lookup again later."""

    def __init__(self, msg, retry_in=20):
        super().__init__(msg)
        self.retry_in = retry_in


class PermanentError(Exception):
    """Something about this lookup itself is wrong; retrying right away won't help."""


class AuthError(PermanentError):
    """Warcraft Logs rejected the client ID/secret: nothing works until the player fixes it."""


AUTH_PROBLEM = "Warcraft Logs rejected your API key (client ID/secret). Run the companion's setup again."


TRANSIENT_HINTS = ("points remaining", "rate limit", "too many", "timeout", "timed out",
                   "try again", "temporarily", "unavailable", "overloaded")


def short_errors(errors):
    msgs = sorted({str(e.get("message", e)) for e in errors})
    return "; ".join(msgs)[:200]


class WCL:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None
        self.paused_until = 0  # set when the hourly points run out, or Warcraft Logs' database is busy
        self.pause_msg = "hourly API limit reached"
        self._token_lock = threading.Lock()

    def _get_token(self, stale=None):
        with self._token_lock:
            if self.token and self.token != stale:
                return  # another thread already refreshed it
            try:
                r = requests.post(TOKEN_URL, data={"grant_type": "client_credentials"},
                                  auth=(self.client_id, self.client_secret), timeout=30)
            except requests.RequestException as exc:
                raise TransientError(f"can't reach Warcraft Logs ({exc.__class__.__name__})", 30)
            if r.status_code in (400, 401):
                raise AuthError(AUTH_PROBLEM)
            if r.status_code >= 500 or r.status_code == 429:
                raise TransientError(f"Warcraft Logs login returned {r.status_code}", 30)
            r.raise_for_status()
            self.token = r.json()["access_token"]

    def query(self, q, variables=None):
        if time.time() < self.paused_until:
            raise TransientError(self.pause_msg, int(self.paused_until - time.time()) + 5)
        if not self.token:
            self._get_token()
        delays = [2, 5, 10]  # backoff between attempts when Warcraft Logs is busy
        last = "unknown error"
        db_limited = False
        for attempt in range(len(delays) + 1):
            if attempt:
                time.sleep(delays[attempt - 1])
            try:
                r = requests.post(API_URL, json={"query": q, "variables": variables or {}},
                                  headers={"Authorization": f"Bearer {self.token}"}, timeout=60)
            except requests.RequestException as exc:
                last = f"network error ({exc.__class__.__name__})"
                continue
            if r.status_code == 401:
                self._get_token(stale=self.token)
                last = "token expired"
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last = f"Warcraft Logs returned HTTP {r.status_code}"
                continue
            if r.status_code >= 400:
                raise PermanentError(f"HTTP {r.status_code}: {r.text[:150]}")
            try:
                body = r.json()
            except ValueError:
                last = "unreadable response"
                continue
            errors = body.get("errors") or []
            rl = (body.get("data") or {}).get("rateLimitData")
            if rl:
                self.reset_at = time.time() + int(rl.get("pointsResetIn", 0))
                note_points(rl)
            if errors:
                text = short_errors(errors)
                if "database points" in text.lower():
                    db_limited = True
                if any(h in text.lower() for h in TRANSIENT_HINTS):
                    last = text
                    continue
                raise PermanentError(text)
            data = body.get("data") or {}
            self._note_rate_limit(data.get("rateLimitData"))
            return data
        if db_limited:
            # Not tied to the hourly points: seen clearing within ~5 min (companion_log, Nov 17) while a
            # day with ~40 lookups/hour never hit it. Looks like a load limit on Warcraft Logs' side.
            self.paused_until = time.time() + DB_LIMIT_RECHECK
            self.db_reset_at = self.paused_until
            self.pause_msg = (f"Warcraft Logs' database is busy (\"no database points remaining\"); "
                              f"retrying every {DB_LIMIT_RECHECK // 60} min")
            raise TransientError(self.pause_msg, DB_LIMIT_RECHECK)
        raise TransientError(last)

    def _note_rate_limit(self, rl):
        if rl and rl["pointsSpentThisHour"] >= rl["limitPerHour"] - RATE_LIMIT_BUFFER:
            self.paused_until = time.time() + int(rl["pointsResetIn"]) + 5
            self.pause_msg = "hourly API limit reached"
            log(f"Hourly API limit nearly used ({rl['pointsSpentThisHour']:.0f}/{rl['limitPerHour']}). "
                f"New lookups wait {int(rl['pointsResetIn']) // 60 + 1} min; queued ones are kept.")


def current_mplus_zone(api, cache):
    z = cache.get("zone")
    if z and time.time() - z["checked"] < ZONE_REFRESH:
        return z
    data = api.query("""query {
  worldData { expansions { id name zones { id name encounters { id name } } } }
  rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }
}""")
    for exp in sorted(data["worldData"]["expansions"], key=lambda e: e["id"], reverse=True):
        live = [x for x in exp["zones"]
                if "mythic+" in x["name"].lower()
                and "ptr" not in x["name"].lower()
                and "beta" not in x["name"].lower()]
        if live:
            zone = max(live, key=lambda x: x["id"])
            old = cache.get("zone") or {}
            if old.get("id") and old["id"] != zone["id"]:
                # New M+ season: last season's averages would be wrong, so forget them.
                before = len(cache.get("players", {}))
                cache["players"] = {k: v for k, v in cache.get("players", {}).items() if v.get("z") == zone["id"]}
                log(f"New M+ season ({zone['name']}): cleared {before - len(cache['players'])} cached players.")
            z = {"id": zone["id"], "name": zone["name"], "encounters": zone["encounters"],
                 "checked": time.time()}
            cache["zone"] = z
            return z
    raise RuntimeError("Couldn't find the current Mythic+ season on Warcraft Logs.")


_servers_lock = threading.Lock()


def realm_slug(api, cache, region, realm):
    """In-game realm ('Area52', "Zul'jin") -> Warcraft Logs slug ('area-52', 'zuljin')."""
    servers = cache.setdefault("servers", {})
    checked = cache.setdefault("servers_checked", {})
    key = realm.replace(" ", "").lower()
    with _servers_lock:
        # (Re)load the realm list if we don't have it, or if this realm is unknown and the list is a day old.
        stale = time.time() - checked.get(region, 0) > ZONE_REFRESH
        if region not in servers or (key not in servers[region] and key != "x" and stale):
            _load_servers(api, servers, region)
            checked[region] = time.time()
    return servers[region].get(key) or re.sub(r"[^a-z0-9-]", "", realm.lower().replace(" ", "-"))


def _load_servers(api, servers, region):
        mapping, page = {}, 1
        while True:
            data = api.query("""query($id: Int!, $page: Int!) {
  worldData { region(id: $id) { servers(limit: 100, page: $page) {
    has_more_pages data { name normalizedName slug } } } }
  rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }
}""", {"id": REGIONS[region], "page": page})
            block = data["worldData"]["region"]["servers"]
            for s in block["data"]:
                for n in (s["normalizedName"], s["name"]):
                    mapping[n.replace(" ", "").lower()] = s["slug"]
            if not block["has_more_pages"]:
                break
            page += 1
        servers[region] = mapping


def role_of(spec):
    if spec in HEALER_SPECS:
        return "heal"
    if spec in TANK_SPECS:
        return "tank"
    return "dps"


def fetch_runs(api, zone, name, slug, region, metric):
    lines = "\n".join(
        f"    d{e['id']}: encounterRankings(encounterID: {e['id']}, metric: {metric}, byBracket: true)"
        for e in zone["encounters"])
    data = api.query(f"""query($name: String!, $server: String!, $region: String!) {{
  characterData {{ character(name: $name, serverSlug: $server, serverRegion: $region) {{
{lines}
  }} }}
  rateLimitData {{ limitPerHour pointsSpentThisHour pointsResetIn }}
}}""", {"name": name, "server": slug, "region": region})
    char = data["characterData"]["character"]
    if char is None:
        return None
    runs = []
    for e in zone["encounters"]:
        for r in (char.get(f"d{e['id']}") or {}).get("ranks") or []:
            runs.append({"enc": e["id"], "key": r["bracketData"], "pct": r["rankPercent"],
                         "dur": r["duration"], "spec": r["spec"], "amount": r["amount"]})
    return runs


def dedupe(runs):
    """Same run uploaded by two group members: same dungeon, key and duration (to the second)."""
    seen, out = set(), []
    for r in runs:
        sig = (r["enc"], r["key"], round(r["dur"] / 1000))
        if sig not in seen:
            seen.add(sig)
            out.append(r)
    return out


def lookup(api, cache, full_name, region):
    """Look up one 'Name-Realm' and return its summary for Data.lua."""
    name, _, realm = full_name.partition("-")
    zone = current_mplus_zone(api, cache)
    slug = realm_slug(api, cache, region, realm)

    runs = fetch_runs(api, zone, name, slug, region, "dps")
    if runs is None:
        return {"t": int(time.time()), "missing": True, "z": zone["id"]}

    # KeyParse is a DPS tool: healer runs are dropped and never re-fetched as HPS (saves points).
    runs = [r for r in runs if role_of(r["spec"]) != "heal"]

    runs = dedupe(runs)
    roles = {}   # role -> key -> [parse, ...]
    per = {}     # role -> key -> dungeon id -> [parse, ...]
    fastest = {}  # (role, key, dungeon id) -> fastest run in seconds (the addon checks it against the timer)
    specs = {}   # role -> spec -> runs
    for r in runs:
        role = role_of(r["spec"])
        roles.setdefault(role, {}).setdefault(r["key"], []).append(r["pct"])
        per.setdefault(role, {}).setdefault(r["key"], {}).setdefault(r["enc"], []).append(r["pct"])
        sig = (role, r["key"], r["enc"])
        secs = int(round((r.get("dur") or 0) / 1000))
        if secs > 0 and (sig not in fastest or secs < fastest[sig]):
            fastest[sig] = secs
        if r.get("spec"):
            specs.setdefault(role, {})[r["spec"]] = specs.setdefault(role, {}).get(r["spec"], 0) + 1

    def avg(v):
        return round(sum(v) / len(v), 1)

    summary = {"t": int(time.time()), "v": DATA_VERSION, "z": zone["id"], "roles": {}}
    for role, by_key in roles.items():
        summary["roles"][role] = {
            k: [len(v), avg(v), {enc: [len(p), avg(p)] + ([fastest[(role, k, enc)]] if (role, k, enc) in fastest else [])
                                 for enc, p in per[role][k].items()}]
            for k, v in by_key.items()
        }
    spec_counts = {}
    for r in runs:
        spec_counts[r["spec"]] = spec_counts.get(r["spec"], 0) + 1
    summary["spec"] = max(spec_counts, key=spec_counts.get) if spec_counts else None
    summary["specs"] = specs
    return summary


# ---------------------------------------------------------------- Lua files

def lua_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


PAUSED = {"until": 0}  # Warcraft Logs' database busy ("no database points remaining"): next re-check
# Warcraft Logs' hourly API points, from the rateLimitData on every answer. Shown in the addon.
# (The "database points" limit isn't reported anywhere, so it can't be shown or counted down.)
POINTS = {}
_points_lock = threading.Lock()


def note_points(rl):
    try:
        spent = float(rl["pointsSpentThisHour"])
        limit = int(rl["limitPerHour"])
        reset = int(time.time() + int(rl["pointsResetIn"]))
    except (KeyError, TypeError, ValueError):
        return
    with _points_lock:
        # answers arrive out of order from the worker threads: within the same hour keep the highest
        if POINTS.get("reset") and abs(POINTS["reset"] - reset) < 120:
            spent = max(spent, POINTS.get("spent", 0))
        POINTS.update(spent=spent, limit=limit, reset=reset)

DATA_SLOTS = 3  # KeyParse_Data1..3: load-on-demand addons the main addon loads a few seconds after login


def player_lua(full, p):
    if p.get("missing"):
        err = ", error = true" if p.get("error") else ""
        return f"    [{lua_str(full)}] = {{ t = {p['t']}, missing = true{err} }},"
    role_parts = []
    for role, by_key in p["roles"].items():
        entries = []
        for k, vals in sorted(by_key.items(), key=lambda kv: int(kv[0])):
            n, avg = vals[0], vals[1]
            detail = ""
            if len(vals) > 2 and vals[2]:
                # { runs, average, fastest seconds } per dungeon (fastest missing in older cache entries)
                d = ", ".join(f"[{int(e)}] = {{ {', '.join(str(x) for x in dv)} }}" for e, dv in
                              sorted(vals[2].items(), key=lambda kv: int(kv[0])))
                detail = f", d = {{ {d} }}"
            entries.append(f"[{int(k)}] = {{ {n}, {avg}{detail} }}")
        role_parts.append(f"{role} = {{ {', '.join(entries)} }}")
    spec = f", spec = {lua_str(p['spec'])}" if p.get("spec") else ""
    if p.get("specs"):
        spec += ", specs = { " + ", ".join(
            f"{role} = {{ " + ", ".join(f"[{lua_str(sp)}] = {n}" for sp, n in sorted(by_spec.items())) + " }"
            for role, by_spec in sorted(p["specs"].items())) + " }"
    return (f"    [{lua_str(full)}] = {{ t = {p['t']}, v = {p.get('v', 1)}{spec}, "
            f"roles = {{ {', '.join(role_parts)} }} }},")


_warned_missing_slots = False


def prune_expired(cache):
    """Drop results older than CACHE_MAX_AGE so we never keep long-term copies of Warcraft Logs data."""
    cutoff = time.time() - CACHE_MAX_AGE
    players = cache.get("players", {})
    for full in [k for k, p in players.items() if p.get("t", 0) < cutoff]:
        del players[full]


def points_lua(cache):
    """The points line for the data file. Kept in cache.json so a companion restart still knows them."""
    with _points_lock:
        if POINTS:
            cache["points"] = dict(POINTS)
    pts = cache.get("points") or {}
    if not pts.get("limit"):
        return "  points = nil,"
    return (f"  points = {{ spent = {int(round(pts.get('spent', 0)))}, limit = {int(pts['limit'])}, "
            f"reset = {int(pts.get('reset', 0))} }},")


def write_data_lua(cfg, cache, done=True):
    """Write the full results into every data slot. done=False while a batch is still being fetched."""
    global _warned_missing_slots
    prune_expired(cache)
    addons = Path(cfg.get("wow_retail_path") or "") / "Interface" / "AddOns"
    lines = ["-- Generated by the KeyParse companion. Do not edit; it is rewritten on every update.",
             "KeyParse_Slot = {",
             f"  done = {'true' if done else 'false'},",
             f"  generated = {int(time.time())},",
             f"  paused = {int(PAUSED['until'])},",
             f"  problem = {lua_str(PROBLEM['text'])},",
             points_lua(cache),
             f"  season = {lua_str(cache.get('zone', {}).get('name', ''))},",
             # Dungeons in Warcraft Logs' order (the order the zone lists them in).
             "  dungeons = { " + ", ".join(f"{{ {e['id']}, {lua_str(e['name'])} }}"
                                           for e in cache.get("zone", {}).get("encounters", [])) + " },",
             "  players = {"]
    lines += [player_lua(full, p) for full, p in sorted(cache.get("players", {}).items())]
    lines += ["  },", "}", ""]
    text = "\n".join(lines)
    wrote = 0
    for i in range(1, DATA_SLOTS + 1):
        slot = addons / f"{ADDON}_Data{i}"
        if not slot.exists():
            continue
        tmp = slot / "Data.tmp"
        try:
            tmp.write_text(text, encoding="utf-8")
            replace_with_retry(tmp, slot / "Data.lua")  # atomic, so WoW never reads a half-written file
            wrote += 1
        except OSError as exc:  # locked for longer than a moment: skip this slot, the next write fixes it
            log(f"  Couldn't write {slot.name}\\Data.lua ({exc.__class__.__name__}); will try again.")
    if not wrote and not _warned_missing_slots:
        _warned_missing_slots = True
        print(f"  (No {ADDON}_Data folders in {addons}; results kept in cache.json only.)")
    return wrote > 0


class LuaReader:
    """Minimal reader for the tables WoW writes into SavedVariables files."""
    TOKEN = re.compile(r'\s*(?:(--[^\n]*)|("(?:\\.|[^"\\])*")|(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)'
                       r'|(true|false|nil)|([A-Za-z_][A-Za-z0-9_]*)|(.))', re.S)

    def __init__(self, text):
        self.toks = []
        for m in self.TOKEN.finditer(text):
            com, s, num, kw, ident, ch = m.groups()
            if com:
                continue
            if s is not None:
                self.toks.append(("v", self.unescape(s[1:-1])))
            elif num is not None:
                self.toks.append(("v", float(num) if "." in num or "e" in num.lower() else int(num)))
            elif kw is not None:
                self.toks.append(("v", {"true": True, "false": False, "nil": None}[kw]))
            elif ident is not None:
                self.toks.append(("id", ident))
            elif ch and not ch.isspace():
                self.toks.append(("p", ch))
        self.i = 0

    @staticmethod
    def unescape(body):
        def rep(m):
            e = m.group(1)
            if e.isdigit():
                return chr(int(e))
            return {"n": "\n", "t": "\t", "r": "\r"}.get(e, e)
        raw = re.sub(r"\\(\d{1,3}|.)", rep, body, flags=re.S)
        if not re.search(r"\\\d", body):
            return raw
        try:  # decimal escapes produce raw bytes; re-decode them as UTF-8
            return raw.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return raw

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def value(self):
        kind, v = self.take()
        if kind == "v":
            return v
        if (kind, v) == ("p", "{"):
            return self.table()
        raise ValueError(f"unexpected token {v!r}")

    def table(self):
        out, idx = {}, 1
        while True:
            kind, v = self.peek()
            if (kind, v) == ("p", "}"):
                self.take()
                return out
            if (kind, v) == ("p", "["):
                self.take()
                k = self.value()
                self.take()  # ]
                self.take()  # =
                out[k] = self.value()
            elif kind == "id" and self.toks[self.i + 1] == ("p", "="):
                self.take()
                self.take()
                out[v] = self.value()
            else:
                out[idx] = self.value()
                idx += 1
            if self.peek() in (("p", ","), ("p", ";")):
                self.take()

    def globals(self):
        out = {}
        while self.i < len(self.toks):
            kind, name = self.take()
            if kind == "id" and self.peek() == ("p", "="):
                self.take()
                out[name] = self.value()
        return out


def read_requests(cfg):
    """Collect pending lookup requests from every WoW account's SavedVariables."""
    retail = Path(cfg.get("wow_retail_path") or "")
    found = {}
    for sv in (retail / "WTF" / "Account").glob(f"*/SavedVariables/{ADDON}.lua"):
        try:
            db = LuaReader(sv.read_text(encoding="utf-8", errors="replace")).globals().get("KeyParseDB") or {}
        except OSError:
            continue  # WoW is rewriting it right now; the next change is picked up anyway
        except (ValueError, IndexError) as exc:
            print(f"  Couldn't read {sv}: {exc}")
            continue
        region = str(db.get("region") or "us").lower()
        for full, ts in (db.get("requests") or {}).items():
            if isinstance(full, str) and "-" in full:
                found[full] = (max(int(ts or 0), found.get(full, (0, region))[0]), region)
    return found


def sv_mtime(cfg):
    retail = Path(cfg.get("wow_retail_path") or "")
    times = []
    for p in (retail / "WTF" / "Account").glob(f"*/SavedVariables/{ADDON}.lua"):
        try:
            times.append(p.stat().st_mtime)
        except OSError:
            pass  # WoW swaps the file on /reload: it can vanish for a moment
    return max(times, default=0)


def refresh_credentials(api):
    """Pick up a new client ID/secret from config.json (e.g. after setup ran in another window)."""
    cfg = load_json(CONFIG_PATH, {})
    cid, sec = cfg.get("client_id"), cfg.get("client_secret")
    if cid and sec and (cid, sec) != (api.client_id, api.client_secret):
        api.client_id, api.client_secret, api.token = cid, sec, None
        log("Using the new API key from config.json.")


# ---------------------------------------------------------------- main loops

def print_result(full, p):
    if p.get("error"):
        log(f"  {full}: lookup failed ({p.get('reason', 'unknown')}) - will retry in 10 min")
    elif p.get("missing"):
        log(f"  {full}: no public M+ logs this season (or logs hidden / name changed)")
    else:
        for role, by_key in p["roles"].items():
            summary = ", ".join(f"+{k}: {vals[1]} ({vals[0]})" for k, vals in
                                sorted(by_key.items(), key=lambda kv: int(kv[0])))
            log(f"  {full} {role}: {summary}")


def process(api, cfg, cache, names_with_region):
    """Look players up in parallel, updating the data slots as each one finishes.
    Returns the lookups that hit a temporary problem, and how long to wait before retrying them."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    players = cache.setdefault("players", {})
    log(f"Looking up {len(names_with_region)} player(s)...")
    retry, retry_in = [], 0
    try:
        # Warm the shared lookups once so the worker threads don't all fetch them at the same time.
        current_mplus_zone(api, cache)
        for region in {r for _, r in names_with_region}:
            realm_slug(api, cache, region, "x")
    except TransientError as exc:
        log(f"  Warcraft Logs isn't answering right now ({exc}). Will retry in {exc.retry_in}s.")
        write_data_lua(cfg, cache, done=True)
        return list(names_with_region), exc.retry_in
    except AuthError:
        PROBLEM["text"] = AUTH_PROBLEM
        log(f"  {AUTH_PROBLEM} Lookups wait until then (checked every {AUTH_RECHECK // 60} min).")
        write_data_lua(cfg, cache, done=True)
        return list(names_with_region), AUTH_RECHECK

    remaining = len(names_with_region)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(lookup, api, cache, full, region): (full, region)
                   for full, region in names_with_region}
        for fut in as_completed(futures):
            full, region = futures[fut]
            try:
                players[full] = fut.result()
                PAUSED["until"] = 0
                PROBLEM["text"] = ""
                print_result(full, players[full])
            except TransientError as exc:
                retry.append((full, region))
                retry_in = max(retry_in, exc.retry_in)
                PAUSED["until"] = getattr(api, "db_reset_at", 0) if "database" in str(exc) else 0
                log(f"  {full}: Warcraft Logs is busy ({exc}) - will retry automatically")
            except AuthError:  # the key stopped working mid-batch: keep the request, don't mark the player failed
                retry.append((full, region))
                retry_in = max(retry_in, AUTH_RECHECK)
                PROBLEM["text"] = AUTH_PROBLEM
                log(f"  {full}: {AUTH_PROBLEM}")
            except Exception as exc:  # anything else: record it so the addon can say so, retry later
                players[full] = {"t": int(time.time()), "missing": True, "error": True,
                                 "reason": str(exc)[:120]}
                print_result(full, players[full])
            remaining -= 1
            write_data_lua(cfg, cache, done=remaining == 0 and not retry)
    try:
        save_json(CACHE_PATH, cache)
    except OSError as exc:  # results are already in the data slots; the cache is only a speed-up
        log(f"  Couldn't save cache.json ({exc}); will try again after the next lookup.")
    if retry:
        log(f"{len(retry)} lookup(s) will be retried in {retry_in}s.")
    else:
        log("Done. KeyParse picks this up automatically a few seconds after a /reload.")
    write_data_lua(cfg, cache, done=not retry)
    return retry, retry_in


def pending_requests(cfg, cache):
    todo = []
    now = time.time()
    for full, (ts, region) in read_requests(cfg).items():
        have = cache.get("players", {}).get(full)
        if not have:
            todo.append((full, region))
        elif have.get("error"):
            if now - have["t"] > ERROR_RETRY_AFTER:
                todo.append((full, region))
        elif not have.get("missing") and have.get("v", 1) < DATA_VERSION:
            todo.append((full, region))  # saved before per-dungeon detail existed
        elif have["t"] <= ts:
            todo.append((full, region))  # asked for again after the last fetch ("Refresh parses")
    return todo


def watch(api, cfg, cache):
    log(f"Watching for {ADDON} requests in {cfg.get('wow_retail_path')}\\WTF ... (Ctrl+C to stop)")
    write_data_lua(cfg, cache, done=True)  # restore data in case the addon was reinstalled/updated
    last = None  # None: check for requests straight away
    retry_at = 0
    failures = 0
    while True:
        # Nothing in here may stop the companion: it often runs minimized from Windows startup, where a
        # crash would go unseen. Unexpected errors are logged with a traceback and retried with a backoff.
        try:
            m = sv_mtime(cfg)
            due = retry_at and time.time() >= retry_at
            if m != last or due:
                if last is not None and m != last:
                    time.sleep(0.2)  # let WoW finish writing the file
                last = m
                if due:
                    refresh_credentials(api)
                todo = pending_requests(cfg, cache)
                if todo:
                    write_data_lua(cfg, cache, done=False)
                    retry, wait = process(api, cfg, cache, todo)
                    retry_at = time.time() + wait if retry else 0
                else:
                    retry_at = 0
            failures = 0
        except Exception:
            failures += 1
            wait = min(300, 15 * failures)
            log_exception(f"Something went wrong; the companion keeps running and tries again in {wait}s:")
            retry_at = time.time() + wait
        time.sleep(POLL_SECONDS)


def main():
    args = sys.argv[1:]
    moved = migrate_old_files()
    if moved:
        log(f"Moved {', '.join(moved)} to {DATA_DIR} (where the companion keeps its files from now on).")
    if args and args[0] == "autostart":
        set_autostart(len(args) < 2 or args[1].lower() != "off")
        return
    cfg = load_config(force_setup=bool(args) and args[0] == "setup")
    if args and args[0] == "setup":
        return
    if not cfg.get("wow_retail_path"):
        print("Couldn't find your WoW folder. Run: python companion.py setup")
    api = WCL(cfg["client_id"], cfg["client_secret"])
    cache = load_json(CACHE_PATH, {})

    if args and args[0] == "lookup":
        region = "us"
        names = []
        for a in args[1:]:
            if a.lower().startswith("--region="):
                region = a.split("=", 1)[1].lower()
            else:
                names.append(a)
        if not names:
            sys.exit("Usage: python companion.py lookup Name-Realm [Name-Realm ...] [--region=us]")
        process(api, cfg, cache, [(n, region) for n in names])
        return

    # Only one companion at a time (it may already be running from Windows startup).
    import socket
    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        guard.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
    except OSError:
        print("The KeyParse companion is already running (check your taskbar). This window will close.")
        time.sleep(5)
        return
    try:
        watch(api, cfg, cache)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        # Couldn't even start (e.g. config.json unreadable). Log why and keep the window open so it can be read:
        # the .exe's console would otherwise close instantly.
        log_exception("The KeyParse companion stopped because of an error:")
        try:
            input("\nPress Enter to close this window.")
        except EOFError:
            pass
        sys.exit(1)
