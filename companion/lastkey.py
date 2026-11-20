"""
"Last key" review: reads the most recent Mythic+ key out of WoW's own combat log (Logs\\WoWCombatLog-*.txt, written while
/combatlog or the Warcraft Logs uploader is logging). Everything here is the player's own data on their own PC: no
Warcraft Logs lookups, no points, and it may be kept as long as they like.

Only the last key is read: the file is searched backwards for the last CHALLENGE_MODE_START, then read forwards from there
to its CHALLENGE_MODE_END (or to the end of the file if the key is still going / was abandoned).

Line format (COMBAT_LOG_VERSION 22, advanced logging on), fields after "date time-tz  ":
  0 event, 1-4 source GUID/name/flags/raidflags, 5-8 dest GUID/name/flags/raidflags,
  SPELL_*/RANGE_*/DAMAGE_SPLIT: 9-11 spell id/name/school; SWING_*: no spell fields;
  then 19 "advanced" fields (info unit GUID, owner GUID, hp, ..., x, y, map, facing, level), then the amounts.
  So for damage/heal events the amount is field 28 + 3 for spell events, 28 for swings.
"""
import datetime as _dt
import json
import time
from pathlib import Path

ADVANCED = 19                 # number of advanced-logging fields before the amounts
AFFIL_MINE = 0x1              # unit flags: this unit is the player who wrote the log
TYPE_PLAYER = 0x400
NO_GUID = "0000000000000000"

DAMAGE = {"SPELL_DAMAGE", "SPELL_PERIODIC_DAMAGE", "RANGE_DAMAGE", "SWING_DAMAGE"}  # not *_LANDED (duplicates)
HEALS = {"SPELL_HEAL", "SPELL_PERIODIC_HEAL"}
WANTED = DAMAGE | HEALS | {"SPELL_INTERRUPT", "UNIT_DIED", "SPELL_SUMMON", "COMBATANT_INFO", "ENCOUNTER_START",
                           "ENCOUNTER_END", "CHALLENGE_MODE_START", "CHALLENGE_MODE_END", "ENVIRONMENTAL_DAMAGE"}

# specID -> (spec, class colour). Midnight specs included; unknown ids just show as "Unknown".
SPECS = {
    71: ("Arms", "#c69b6d"), 72: ("Fury", "#c69b6d"), 73: ("Protection", "#c69b6d"),
    65: ("Holy", "#f48cba"), 66: ("Protection", "#f48cba"), 70: ("Retribution", "#f48cba"),
    253: ("Beast Mastery", "#aad372"), 254: ("Marksmanship", "#aad372"), 255: ("Survival", "#aad372"),
    259: ("Assassination", "#fff468"), 260: ("Outlaw", "#fff468"), 261: ("Subtlety", "#fff468"),
    256: ("Discipline", "#ffffff"), 257: ("Holy", "#ffffff"), 258: ("Shadow", "#ffffff"),
    250: ("Blood", "#c41e3a"), 251: ("Frost", "#c41e3a"), 252: ("Unholy", "#c41e3a"),
    262: ("Elemental", "#0070dd"), 263: ("Enhancement", "#0070dd"), 264: ("Restoration", "#0070dd"),
    62: ("Arcane", "#3fc7eb"), 63: ("Fire", "#3fc7eb"), 64: ("Frost", "#3fc7eb"),
    265: ("Affliction", "#8788ee"), 266: ("Demonology", "#8788ee"), 267: ("Destruction", "#8788ee"),
    268: ("Brewmaster", "#00ff98"), 269: ("Windwalker", "#00ff98"), 270: ("Mistweaver", "#00ff98"),
    102: ("Balance", "#ff7c0a"), 103: ("Feral", "#ff7c0a"), 104: ("Guardian", "#ff7c0a"), 105: ("Restoration", "#ff7c0a"),
    577: ("Havoc", "#a330c9"), 581: ("Vengeance", "#a330c9"), 1480: ("Devourer", "#a330c9"),
    1467: ("Devastation", "#33937f"), 1468: ("Preservation", "#33937f"), 1473: ("Augmentation", "#33937f"),
}
TANKS = {73, 66, 250, 268, 104, 581}
HEALERS = {65, 256, 257, 264, 270, 105, 1468}


def split_fields(s):
    """Split a combat log line's fields on commas, keeping quoted names (which may contain commas) whole and
    keeping [...] / (...) lists in one field."""
    out, cur, quoted, depth = [], [], False, 0
    for ch in s:
        if quoted:
            if ch == '"':
                quoted = False
            else:
                cur.append(ch)
        elif ch == '"':
            quoted = True
        elif ch in "[(":
            depth += 1
            cur.append(ch)
        elif ch in ")]":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def parse_time(stamp):
    """'11/19/2026 19:48:48.668-8' -> seconds since 1970 (the -8 is the PC's UTC offset in hours)."""
    date, clock = stamp.split(" ")
    tz = 0
    for sign in "+-":
        if sign in clock:
            clock, off = clock.rsplit(sign, 1)
            tz = int(off) * (1 if sign == "+" else -1)
            break
    d = _dt.datetime.strptime(f"{date} {clock}", "%m/%d/%Y %H:%M:%S.%f")
    return (d - _dt.timedelta(hours=tz)).replace(tzinfo=_dt.timezone.utc).timestamp()


def split_line(line):
    """'date time  EVENT,a,b' -> (stamp, fields) or None."""
    i = line.find("  ")
    if i < 0:
        return None
    return line[:i], split_fields(line[i + 2:].rstrip("\r\n"))


def to_int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def short_name(full):
    """'Taftonator-Dalaran-US' -> ('Taftonator', 'Dalaran')."""
    parts = (full or "?").split("-")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-1].isupper():
        parts = parts[:-1]  # region
    return parts[0], "-".join(parts[1:])


def logs_folder(wow_retail_path):
    return Path(wow_retail_path or "") / "Logs"


def log_files(folder):
    """Combat log files, newest first."""
    try:
        files = list(Path(folder).glob("WoWCombatLog*.txt"))
    except OSError:
        return []
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def find_last_start(path, chunk=8 << 20):
    """Byte offset of the start of the line with the last CHALLENGE_MODE_START, or None. Reads backwards so a
    1 GB log doesn't have to be read whole."""
    needle = b"CHALLENGE_MODE_START"
    with open(path, "rb") as f:
        f.seek(0, 2)
        pos = f.tell()
        tail = b""
        while pos > 0:
            step = min(chunk, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + tail
            i = buf.rfind(needle)
            if i >= 0:
                line_start = buf.rfind(b"\n", 0, i) + 1
                if line_start == 0 and pos > 0:  # the line starts in the previous chunk
                    tail = buf
                    continue
                return pos + line_start
            tail = buf[:len(needle) + 512]  # keep a little overlap so a split needle is still found
    return None


def read_key(path, start):
    """Read one key from `start` (offset of its CHALLENGE_MODE_START line) and summarise it."""
    owner = {}           # pet GUID -> player GUID
    names = {}           # GUID -> "Name-Realm-US"
    flags = {}           # player GUID -> unit flags (to find "you")
    dmg, heal, taken, kicks, deaths_n = {}, {}, {}, {}, {}
    spells = {}          # (GUID, spell name) -> damage, for the logging player's breakdown
    last_hits = {}       # player GUID -> last few hits taken [(t, spell, source, amount)]
    deaths, bosses, open_boss = [], [], {}
    group, specs = [], {}
    key = None
    t0 = t_end = t_last = None
    result_end = None
    advanced = True

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(start)
        for line in f:
            sp = line.find("  ")
            if sp < 0:
                continue
            comma = line.find(",", sp)
            event = line[sp + 2:comma]
            if event not in WANTED:
                continue
            stamp, fl = line[:sp], split_fields(line[sp + 2:].rstrip("\r\n"))
            if event == "CHALLENGE_MODE_START":
                if key is not None:
                    break  # a newer key started (shouldn't happen: we start at the last one)
                t0 = parse_time(stamp)
                key = {"dungeon": fl[1], "instance": to_int(fl[2]), "map": to_int(fl[3]), "level": to_int(fl[4]),
                       "started": t0}
                continue
            if key is None:
                continue
            t_last = stamp
            t = parse_time(stamp) if event in ("UNIT_DIED", "ENCOUNTER_START", "ENCOUNTER_END",
                                               "CHALLENGE_MODE_END") else None
            if event == "CHALLENGE_MODE_END":
                if to_int(fl[3]) == 0 and to_int(fl[4]) == 0:
                    continue  # the empty END WoW writes right before a START
                result_end = {"success": fl[2] == "1", "ms": to_int(fl[4])}
                t_end = t
                break
            if event == "COMBATANT_INFO":
                guid = fl[1]
                if guid not in specs:
                    group.append(guid)
                specs[guid] = to_int(fl[25]) if len(fl) > 25 else 0
                continue
            if event == "ENCOUNTER_START":
                open_boss[fl[1]] = {"name": fl[2], "start": t}
                continue
            if event == "ENCOUNTER_END":
                b = open_boss.pop(fl[1], {"name": fl[2], "start": t})
                bosses.append({"name": fl[2], "killed": fl[5] == "1", "at": t - t0, "fight": to_int(fl[6]) / 1000})
                continue
            if event == "SPELL_SUMMON":
                owner[fl[5]] = fl[1]
                continue

            src, dst = fl[1], fl[5]
            if src.startswith("Player-"):
                names[src] = fl[2]
                flags[src] = int(fl[3], 16) if fl[3].startswith("0x") else 0
            if dst.startswith("Player-"):
                names[dst] = fl[6]
            if event == "UNIT_DIED":
                if dst in specs:
                    hits = last_hits.get(dst) or []
                    blow = hits[-1] if hits else None
                    deaths.append({"guid": dst, "at": t - t0,
                                   "spell": blow[1] if blow else "", "by": blow[2] if blow else "",
                                   "amount": blow[3] if blow else 0})
                    deaths_n[dst] = deaths_n.get(dst, 0) + 1
                continue
            if event == "SPELL_INTERRUPT":
                who = owner.get(src, src)
                kicks[who] = kicks.get(who, 0) + 1
                continue
            if event == "ENVIRONMENTAL_DAMAGE":
                continue

            p = 0 if event.startswith("SWING") else 3
            i = 9 + p + ADVANCED
            if len(fl) <= i + 2:
                advanced = False
                continue
            # the advanced unit is sometimes the pet itself: its owner GUID is then right there
            info, own = fl[9 + p], fl[10 + p]
            if own != NO_GUID and own.startswith("Player-") and info == src:
                owner[src] = own
            amount = to_int(fl[i])
            if event in DAMAGE:
                over = to_int(fl[i + 2])
                amount -= max(0, over)
                who = owner.get(src, src)
                if who in specs and not dst.startswith(("Player-", "Pet-")):
                    dmg[who] = dmg.get(who, 0) + amount
                    if p:
                        k = (who, fl[10])
                        spells[k] = spells.get(k, 0) + amount
                    else:
                        k = (who, "Melee")
                        spells[k] = spells.get(k, 0) + amount
                if dst in specs:
                    taken[dst] = taken.get(dst, 0) + amount
                    hits = last_hits.setdefault(dst, [])
                    hits.append((0, fl[10] if p else "Melee", fl[2], amount))
                    del hits[:-3]
            else:  # heals
                over = to_int(fl[i + 2])
                who = owner.get(src, src)
                if who in specs:
                    heal[who] = heal.get(who, 0) + max(0, amount - max(0, over))

    if key is None:
        return None
    if t_end is None and t_last:
        t_end = parse_time(t_last)
    duration = (result_end["ms"] / 1000) if result_end and result_end["ms"] else max(1.0, (t_end or t0) - t0)
    me = next((g for g in group if flags.get(g, 0) & AFFIL_MINE), None)
    players = []
    for g in group:
        spec_id = specs.get(g, 0)
        spec, colour = SPECS.get(spec_id, ("Unknown", "#a35bff"))
        name, realm = short_name(names.get(g, "?"))
        role = "Tank" if spec_id in TANKS else "Healer" if spec_id in HEALERS else "DPS"
        players.append({"guid": g, "name": name, "realm": realm, "spec": spec, "colour": colour, "role": role,
                        "me": g == me, "damage": dmg.get(g, 0), "dps": dmg.get(g, 0) / duration,
                        "healing": heal.get(g, 0), "hps": heal.get(g, 0) / duration, "interrupts": kicks.get(g, 0),
                        "deaths": deaths_n.get(g, 0), "taken": taken.get(g, 0)})
    players.sort(key=lambda x: -x["damage"])
    for d in deaths:
        d["name"] = short_name(names.get(d.pop("guid"), "?"))[0]
    mine = sorted(((s, v) for (g, s), v in spells.items() if g == me and v > 0), key=lambda kv: -kv[1])
    total_mine = sum(v for _, v in mine) or 1
    if result_end:
        state = "finished" if result_end["success"] else "abandoned"
    else:
        state = "in progress"
    return dict(key, state=state, duration=duration, ended=t_end, players=players, deaths=deaths, bosses=bosses,
                my_spells=[{"spell": s, "damage": v, "share": v / total_mine} for s, v in mine[:8]],
                advanced=advanced, me=bool(me))


def timed_from_history(key, history):
    """Was this key in time? Only the addon knows (WoW tells it when the key ends); it keeps that in its played-with
    history in SavedVariables. Returns True/False, or None when it isn't there (yet: saved on the next reload)."""
    if not key or key.get("state") != "finished":
        return None
    end = key.get("ended") or 0
    for p in ((history or {}).get("players") or {}).values():
        runs = p.get("runs") or {}
        for r in (runs.values() if isinstance(runs, dict) else runs):
            if (isinstance(r, dict) and to_int(r.get("map")) == key["map"] and to_int(r.get("lvl")) == key["level"]
                    and abs(to_int(r.get("t")) - end) < 900):
                return bool(r.get("timed"))
    return None


def last_key(wow_retail_path, cache_path=None, tries=3):
    """The newest key in the newest combat logs. Returns {"state": "none"|"ready", ...}. A finished key is cached in
    cache_path (lastkey.json) so it isn't re-read every time the page opens."""
    folder = logs_folder(wow_retail_path)
    files = log_files(folder)
    if not files:
        return {"state": "none", "reason": "nolog", "folder": str(folder)}
    cached = {}
    if cache_path:
        try:
            cached = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = {}
    for path in files[:tries]:
        try:
            start = find_last_start(path)
        except OSError:
            continue
        if start is None:
            continue
        if (cached.get("file") == str(path) and cached.get("offset") == start
                and cached.get("key", {}).get("state") == "finished"):
            return {"state": "ready", "key": cached["key"], "file": path.name}
        try:
            key = read_key(path, start)
        except OSError as exc:
            return {"state": "none", "reason": "unreadable", "text": str(exc)}
        if key is None:
            continue
        if cache_path and key["state"] == "finished":
            try:
                Path(cache_path).write_text(json.dumps({"file": str(path), "offset": start, "key": key}),
                                            encoding="utf-8")
            except OSError:
                pass
        return {"state": "ready", "key": key, "file": path.name}
    return {"state": "none", "reason": "nokey", "folder": str(folder)}
