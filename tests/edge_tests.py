import json, sys, time, traceback
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Game, new_wow, FakeWCL, companion, ENC

import tempfile
TMP = Path(tempfile.gettempdir()) / 'kp_tests'
results = []

def case(title):
    def wrap(fn):
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, "CRASH: " + "".join(traceback.format_exception_only(type(exc), exc)).strip()
        results.append((title, ok, detail))
        return fn
    return wrap

def write_sv(wow, game):
    (wow / 'WTF/Account/ACC1/SavedVariables/KeyParse.lua').write_text(game.sv(), encoding='utf-8')

def dps_runs(*keys):  # one Altar run per key, distinct durations
    return {12993: [(k, 60.0, 1_000_000 + i * 1000, "Fire") for i, k in enumerate(keys)]}

# ---------------------------------------------------------------------------------------------
@case("1. Right-click a player whose realm has a dash (Azjol-Nerub)")
def _():
    wow = new_wow(TMP / 't1'); g = Game(wow)
    menu = g.right_click("Bob", "Azjol-Nerub")
    g.run('LASTBTN["Get M+ parses"]()')
    req = g.requests()
    return req == ["Bob-AzjolNerub"], f"queued as {req} (applicants from that realm show up as Bob-AzjolNerub)"

@case("2. Applicant from your own realm (Blizzard gives no realm)")
def _():
    wow = new_wow(TMP / 't2'); g = Game(wow)
    g.applicants([[("Sameguy", "DAMAGER")]])
    req = g.requests()
    return req == ["Sameguy-Dalaran"], f"queued as {req}"

@case("3. Listing title mentions another number ('LF +2 dps for 15'), your key is a 15")
def _():
    wow = new_wow(TMP / 't3')
    fake = FakeWCL({("Pusher", "dalaran"): dps_runs(14, 14, 14, 15, 15, 15)})
    c, cfg, api = companion(wow, fake, TMP / 't3'); cache = {}
    c.process(api, cfg, cache, [("Pusher-Dalaran", "us")])
    g = Game(wow, pre='LISTING = { name = "LF +2 dps for 15" } OWNED_KEY = 15')
    g.applicants([[("Pusher-Dalaran", "DAMAGER")]])
    lab = g.labels()[0]
    g.run('TIP = {} M = FRAMES[1].Members[1] M._h_OnEnter(M)')
    tip = " ".join(g.L.eval('TIP').values())
    ok = lab == "|cff0070ff60|r" and "avg of 6 DPS runs on +13 to +15" in tip   # range from the 15, not the 2
    return ok, f"label: {lab!r} tip={tip!r} (should average +13 to +15 when you're pushing a 15)"

@case("4. /kp key 5 but the player only has +10 and higher")
def _():
    wow = new_wow(TMP / 't4')
    fake = FakeWCL({("Highguy", "dalaran"): dps_runs(10, 11, 12)})
    c, cfg, api = companion(wow, fake, TMP / 't4'); cache = {}
    c.process(api, cfg, cache, [("Highguy-Dalaran", "us")])
    g = Game(wow)
    g.run('SlashCmdList.KEYPARSE("key 5")')
    g.applicants([[("Highguy-Dalaran", "DAMAGER")]])
    lab = g.labels()[0]
    return "no logs" not in lab, f"label: {lab!r} (they DO have logs, just none below +5)"

@case("5. Applied as tank but only has DPS logs")
def _():
    wow = new_wow(TMP / 't5')
    fake = FakeWCL({("Swapper", "dalaran"): dps_runs(15, 15, 15)})
    c, cfg, api = companion(wow, fake, TMP / 't5'); cache = {}
    c.process(api, cfg, cache, [("Swapper-Dalaran", "us")])
    g = Game(wow)
    g.applicants([[("Swapper-Dalaran", "TANK")]])
    lab = g.labels()[0]
    g.run('TIP = {} M = FRAMES[1].Members[1] M._h_OnEnter(M)')
    tip = " ".join(g.L.eval('TIP').values())
    ok = lab.endswith("|cffff9933!|r") and "DPS runs" in tip
    return ok, f"label: {lab!r} tip={tip!r} (! on the row, tooltip says the number is their DPS parse)"

@case("6. 'Refresh parses' right after a fetch (within 30 min)")
def _():
    wow = new_wow(TMP / 't6')
    fake = FakeWCL({("Fresh", "dalaran"): dps_runs(15)})
    c, cfg, api = companion(wow, fake, TMP / 't6'); cache = {}
    c.process(api, cfg, cache, [("Fresh-Dalaran", "us")])
    g = Game(wow)
    g.right_click("Fresh", "Dalaran"); g.run('LASTBTN["Refresh parses"]()')
    write_sv(wow, g)
    todo = c.pending_requests(cfg, cache)
    return todo == [("Fresh-Dalaran", "us")], f"companion would fetch: {todo} (otherwise it stays 'queued' forever)"

@case("7. New M+ season (different zone) with old players cached")
def _():
    wow = new_wow(TMP / 't7')
    fake = FakeWCL({("Oldguy", "dalaran"): dps_runs(15)}, zone_id=60)
    c, cfg, api = companion(wow, fake, TMP / 't7')
    cache = {"zone": {"id": 55, "name": "Mythic+ Season 2", "encounters": ENC, "checked": 0},
             "players": {"Oldguy-Dalaran": {"t": int(time.time()) - 60, "v": 2, "roles": {"dps": {"20": [5, 99.0, {}]}}}}}
    c.process(api, cfg, cache, [("Newguy-Dalaran", "us")])
    old = cache["players"].get("Oldguy-Dalaran")
    return old is None or old.get("z") == 60, f"last-season entry still cached as current: {old}"

@case("8. Companion reads a real SavedVariables file (settings, flags, accents)")
def _():
    wow = new_wow(TMP / 't8'); g = Game(wow)
    g.applicants([[("Dègenerate-Anvilmar", "DAMAGER"), ("Kel'thas-Mal'Ganis", "DAMAGER")]])
    g.run('KeyParseDB.reopenAt = os.time() SlashCmdList.KEYPARSE("key 16")')
    write_sv(wow, g)
    c, cfg, api = companion(wow, FakeWCL({}), TMP / 't8')
    req = sorted(c.read_requests(cfg))
    return req == sorted(["Dègenerate-Anvilmar", "Kel'thas-Mal'Ganis"]), f"read: {req}"

@case("9. Premade group of 5 applies together")
def _():
    wow = new_wow(TMP / 't9'); g = Game(wow)
    g.applicants([[(f"P{i}-Area52", "DAMAGER") for i in range(5)]])
    txt, en = g.button()
    return len(g.requests()) == 5 and txt == "KeyParse: fetch 5 (reload)" and en, f"button {txt!r} enabled={en}, queued {len(g.requests())}"

@case("10. Accented name end to end (companion -> data file -> applicant label)")
def _():
    wow = new_wow(TMP / 't10')
    fake = FakeWCL({("Dègenerate", "anvilmar"): dps_runs(15, 15, 15)})
    c, cfg, api = companion(wow, fake, TMP / 't10'); cache = {}
    c.process(api, cfg, cache, [("Dègenerate-Anvilmar", "us")])
    g = Game(wow)
    g.applicants([[("Dègenerate-Anvilmar", "DAMAGER")]])
    lab = g.labels()[0]
    return "60" in lab, f"label: {lab!r}"

@case("11. A KeyParse Data addon is disabled in the AddOns list")
def _():
    wow = new_wow(TMP / 't11')
    g = Game(wow, db_lua='KeyParseDB = { requests = { ["X-Dalaran"] = os.time() } }', pre='LOAD_FAIL = true')
    g.applicants([[("Y-Dalaran", "DAMAGER")]])
    msgs = " ".join(g.printed())
    return "enabled" in msgs and g.labels()[0] != "", f"chat: {msgs[-120:]!r}, label {g.labels()[0]!r}"

@case("12. Player exists on Warcraft Logs but has 0 runs this season")
def _():
    wow = new_wow(TMP / 't12')
    fake = FakeWCL({("Raider", "dalaran"): {}})
    c, cfg, api = companion(wow, fake, TMP / 't12'); cache = {}
    c.process(api, cfg, cache, [("Raider-Dalaran", "us")])
    g = Game(wow)
    g.applicants([[("Raider-Dalaran", "DAMAGER")]])
    lab = g.labels()[0]; menu = g.right_click("Raider", "Dalaran")
    return "no logs" in lab and any("No public M+ logs" in m for m in menu), f"label {lab!r}, menu {menu[-1]!r}"

@case("13. Fetch button clicked while nothing is queued (greyed)")
def _():
    wow = new_wow(TMP / 't13'); g = Game(wow)
    g.applicants([])
    txt, en = g.button()
    return en is False and "nothing" in txt, f"button {txt!r} enabled={en}"

@case("14. Regression: Warcraft Logs busy twice, then answers (group applying together)")
def _():
    wow = new_wow(TMP / 't14')
    fake = FakeWCL({("A", "dalaran"): dps_runs(15), ("B", "dalaran"): dps_runs(15)})
    fake.busy = {"A": 2, "B": 9}
    c, cfg, api = companion(wow, fake, TMP / 't14'); cache = {}
    retry, wait = c.process(api, cfg, cache, [("A-Dalaran", "us"), ("B-Dalaran", "us")])
    a = cache["players"].get("A-Dalaran", {})
    return "roles" in a and retry == [("B-Dalaran", "us")] and "B-Dalaran" not in cache["players"], \
        f"A={a}, retry={retry}, B cached={cache['players'].get('B-Dalaran')}"

@case("15. Regression: applicant withdraws -> button greys out, lookup dropped")
def _():
    wow = new_wow(TMP / 't15'); g = Game(wow)
    g.applicants([[("Leaver-Thrall", "DAMAGER")]])
    first = g.button()
    g.run('STATUS[101] = "cancelled"'); g.ev("LFG_LIST_APPLICANT_UPDATED")
    txt, en = g.button()
    return first[1] and not en and g.requests() == [], f"before {first}, after {(txt, en)}, queued {g.requests()}"

@case("16. Regression: fetch button reloads and Group Finder reopens after")
def _():
    wow = new_wow(TMP / 't16'); g = Game(wow)
    g.applicants([[("Someone-Thrall", "DAMAGER")]])
    g.run('FETCH._s_OnClick(FETCH)')
    reloaded = g.L.eval('RELOADED'); sv = g.sv()
    g2 = Game(wow, db_lua=sv, pre='PVEFrame._shown = false OPENED = false function PVEFrame_ShowFrame() OPENED = true end')
    g2.run('RunTimers()')
    return bool(reloaded) and bool(g2.L.eval('OPENED')), f"reloaded={reloaded}, reopened={g2.L.eval('OPENED')}"

@case("17. Warcraft Logs' database busy (no database points): re-check in 2 min, tell the player")
def _():
    wow = new_wow(TMP / 't17')
    fake = FakeWCL({("Late", "dalaran"): dps_runs(15)}); fake.busy = {"Late": 99}
    c, cfg, api = companion(wow, fake, TMP / 't17'); cache = {}
    calls_before = len(fake.calls)
    retry, wait = c.process(api, cfg, cache, [("Late-Dalaran", "us")])
    first_calls = len(fake.calls) - calls_before
    retry2, wait2 = c.process(api, cfg, cache, [("Late-Dalaran", "us")])   # a re-check while still paused
    extra_calls = len(fake.calls) - calls_before - first_calls
    g = Game(wow, db_lua='KeyParseDB = { requests = { ["Late-Dalaran"] = os.time() } }')
    g.run('RunTimers() RunTimers()')
    said = " ".join(g.printed())
    ok = retry and wait == 120 and extra_calls == 0 and "Warcraft Logs is busy (its database limit, not your points)" in said
    return ok, f"wait={wait}s, calls while paused={extra_calls}, chat={said[-140:]!r}"

@case("18. Results older than 24h are deleted (Warcraft Logs terms)")
def _():
    wow = new_wow(TMP / 't18')
    c, cfg, api = companion(wow, FakeWCL({}), TMP / 't18')
    now = int(time.time())
    cache = {"players": {"Old-Dalaran": {"t": now - 25 * 3600, "v": 2, "roles": {"dps": {"15": [3, 50.0, {}]}}},
                         "New-Dalaran": {"t": now - 3600, "v": 2, "roles": {"dps": {"15": [3, 70.0, {}]}}}}}
    c.write_data_lua(cfg, cache)
    slot = (wow / 'Interface/AddOns/KeyParse_Data1/Data.lua').read_text(encoding='utf-8')
    return "Old-Dalaran" not in slot and "New-Dalaran" in slot and "Old-Dalaran" not in cache["players"], \
        f"old in slot={'Old-Dalaran' in slot}, new in slot={'New-Dalaran' in slot}"

@case("19. Right-click > Get M+ parses queues them and reloads right away (not in combat)")
def _():
    wow = new_wow(TMP / 't19'); g = Game(wow)
    g.right_click("Stranger", "Area 52"); g.run('LASTBTN["Get M+ parses"]()')
    reloaded, req = g.L.eval('RELOADED'), g.requests()
    g2 = Game(wow, pre='function InCombatLockdown() return true end')
    g2.right_click("Fighter", "Thrall"); g2.run('LASTBTN["Get M+ parses"]()')
    reloaded2, req2 = g2.L.eval('RELOADED'), g2.requests()
    ok = reloaded and req == ["Stranger-Area52"] and not reloaded2 and req2 == ["Fighter-Thrall"]
    return ok, f"out of combat: reloaded={reloaded} queued={req}; in combat: reloaded={reloaded2} queued={req2}"

def party_setup(g):
    g.run('PARTY = { {"Tankguy", "Thrall", "TANK", "WARRIOR"}, {"Healguy", "Area52", "HEALER", "PRIEST"}, {"Dpsguy", "Illidan", "DAMAGER", "MAGE"} }')

def click_btn(g, text):
    g.run('for k, f in pairs(LASTBTN) do if k:find(%r, 1, true) then f() break end end' % text)

@case("20. Right-click yourself in a party > Show group parses (no cost note), healers skipped, then members > keys > dungeons")
def _():
    wow = new_wow(TMP / 't20'); g = Game(wow); party_setup(g)
    menu = g.right_click("Taftonator", "Dalaran")
    entry = [m for m in menu if "Show group parses" in m]
    other = g.right_click("Dpsguy", "Illidan")  # someone else: no group entry
    g.right_click("Taftonator", "Dalaran")
    click_btn(g, "Show group parses")
    req, reloaded = g.requests(), g.L.eval('RELOADED')
    fake = FakeWCL({("Tankguy", "thrall"): {12993: [(15, 55.0, 1000000, "Protection")]},
                    ("Healguy", "area-52"): {12993: [(15, 88.0, 1000000, "Holy")]},
                    ("Dpsguy", "illidan"): dps_runs(15, 15),
                    ("Taftonator", "dalaran"): dps_runs(14)})
    c, cfg, api = companion(wow, fake, TMP / 't20'); cache = {}
    write_sv(wow, g); c.process(api, cfg, cache, c.pending_requests(cfg, cache))
    g2 = Game(wow, db_lua=g.sv()); party_setup(g2)
    menu2 = g2.right_click("Taftonator", "Dalaran")
    text = "\n".join(menu2)
    ok = len(entry) == 1 and entry[0] == "Show group parses" \
        and not any("group parses" in m for m in other) and reloaded \
        and req == sorted(["Taftonator-Dalaran", "Tankguy-Thrall", "Dpsguy-Illidan"]) \
        and "Show group parses (3/3)" in text and "healer, not looked up" in text and "Altar of Fangs" in text \
        and ("Healguy", "area-52") not in fake.calls
    return ok, f"entry={entry} queued={req} reloaded={reloaded}\n" + text[-700:]

@case("21. Right-click a listed group > Show leader parse (only the leader, with realm), then ▼ on the listing")
def _():
    wow = new_wow(TMP / 't21'); g = Game(wow)
    res = 'RESULTS[7] = { leaderName = "Lead-Thrall", members = { {name="Lead", role="TANK", class="WARRIOR", leader=true}, {name="Two", role="DAMAGER", class="DRUID"}, {name="Three", role="DAMAGER", class="ROGUE"} } }'
    g.run(res)
    menu = g.right_click_listing(7)
    g.run('LASTBTN["Show leader parse"]()')
    req = g.requests()
    fake = FakeWCL({("Lead", "thrall"): dps_runs(15)})
    c, cfg, api = companion(wow, fake, TMP / 't21'); cache = {}
    write_sv(wow, g); c.process(api, cfg, cache, c.pending_requests(cfg, cache))
    g2 = Game(wow, db_lua=g.sv()); g2.run(res)
    menu2 = g2.right_click_listing(7)
    g2.run('ROW = NewW({ resultID = 7 }) SEARCHFRAMES = { ROW }')
    g2.run('MAIN._s_OnEvent(nil, "ADDON_LOADED", "Blizzard_GroupFinder")')
    g2.run('if SEARCHCB then SEARCHCB() end')
    shown = g2.L.eval('ROW._arrow ~= nil and ROW._arrow._shown')
    g2.run('ROW._arrow._s_OnClick(ROW._arrow)')
    drop = "\n".join(g2.L.eval('MENU').values())
    ok = "Show leader parse" in menu and not any("group" in m.lower() for m in menu) and req == ["Lead-Thrall"] \
        and any(m.startswith("Leader parse") for m in menu2) and shown and "Leader parse" in drop and "Altar of Fangs" in drop
    return ok, f"menu={menu} queued={req} menu2={menu2} arrow={shown}\n{drop}"

@case("22. Listed group led by a healer: nothing is looked up")
def _():
    wow = new_wow(TMP / 't22'); g = Game(wow)
    g.run('RESULTS[8] = { leaderName = "Boss-Thrall", members = { {name="Boss", role="HEALER", class="PRIEST", leader=true}, {role="DAMAGER", class="MAGE"} } }')
    menu = g.right_click_listing(8)
    return any("Leader is a healer" in m for m in menu) and g.requests() == [], f"menu={menu} queued={g.requests()}"

@case("23. In a raid: no Show group parses option (could be 20+ lookups)")
def _():
    wow = new_wow(TMP / 't23'); g = Game(wow); party_setup(g); g.run('IN_RAID = true')
    menu = g.right_click("Taftonator", "Dalaran")
    return not any("group parses" in m.lower() for m in menu), f"menu={menu}"

@case("24. Fetch while applied to someone else's group: reopens Group Finder + one hint to get the list back")
def _():
    wow = new_wow(TMP / 't24')
    pre = 'LISTING = nil MYAPPS = { 101, 102 } PVEFrame._shown = false OPENED = false function PVEFrame_ShowFrame() OPENED = true end'
    g = Game(wow, db_lua='KeyParseDB = { reopenAt = os.time() }', pre=pre)
    g.run('RunTimers() RunTimers()')
    said = [s for s in g.printed() if "still active" in s]
    # your own listing: no hint
    g2 = Game(wow, db_lua='KeyParseDB = { reopenAt = os.time() }', pre=pre.replace("LISTING = nil", 'LISTING = { name = "+16" }'))
    g2.run('RunTimers() RunTimers()')
    said2 = [s for s in g2.printed() if "still active" in s]
    return bool(g.L.eval('OPENED')) and len(said) == 1 and "Find Group" in said[0] and not said2, f"{said} / own={said2}"

SEARCH_PRE = """
rawset(SEARCHPANEL, "categoryID", 2) rawset(SEARCHPANEL, "filters", 0) rawset(SEARCHPANEL, "searching", false)
SEARCHBOX = NewW({ _text = "18-18" }) rawset(SEARCHPANEL, "SearchBox", SEARCHBOX)
RESULTS[7] = { leaderName = "Lead-Thrall", guid = "Party-1-AAA", members = { {name="Lead-Thrall", role="TANK", class="WARRIOR", leader=true}, {name="Two-Illidan", role="DAMAGER", class="MAGE"} } }
RESULTS[9] = { leaderName = "Other-Thrall", guid = "Party-1-BBB", members = { {name="Other-Thrall", role="TANK", class="WARRIOR", leader=true} } }
RESULTS[11] = { leaderName = "Third-Thrall", guid = "Party-1-CCC", members = { {name="Third-Thrall", role="TANK", class="WARRIOR", leader=true} } }
"""

@case("25. Show a leader parse while browsing an 18-18 Dungeons search: state saved before the reload")
def _():
    wow = new_wow(TMP / 't25')
    g = Game(wow, db_lua='KeyParseDB = nil', pre='LISTING = nil' + SEARCH_PRE)
    g.right_click_listing(7)
    g.run('LASTBTN["Show leader parse"]()')
    rt = g.L.eval('KeyParseDB.returnTo')
    ok = bool(g.L.eval('RELOADED')) and rt is not None and rt['categoryID'] == 2 and rt['text'] == "18-18" \
        and rt['focus']['guid'] == "Party-1-AAA" and rt['focus']['leader'] == "Lead-Thrall" and g.L.eval('KeyParseDB.reopenAt') is not None
    return ok, g.sv()

def after_reload(tmp, own_listing=False, extra=''):
    wow = new_wow(TMP / tmp)
    pre = ('LISTING = { name = "+16" }' if own_listing else 'LISTING = nil MYAPPS = { 7 }') + SEARCH_PRE + \
          ' PVEFrame._shown = false OPENED = false function PVEFrame_ShowFrame() OPENED = true PVEFrame._shown = true end' + extra
    db = ('KeyParseDB = { reopenAt = os.time(), returnTo = { at = os.time(), categoryID = 2, filters = 0, text = "18-18", '
          'focus = { guid = "Party-1-AAA", leader = "Lead-Thrall" } } }')
    g = Game(wow, db_lua=db, pre=pre)
    g.run('RunTimers() RunTimers() RunTimers()')
    return g

@case("26. After the reload: Group Finder reopens with a secure 'back to your Dungeons search' button")
def _():
    g = after_reload('t26')
    shown = g.L.eval('KeyParseReturnButton and KeyParseReturnButton._shown')
    text = g.L.eval('KeyParseReturnButton and KeyParseReturnButton._text')
    macro = g.L.eval('KeyParseReturnButton._a_macrotext')
    cat = g.L.eval('KeyParseReturnCategory._a_clickbutton == CATBUTTONS[2]')
    find = g.L.eval('KeyParseReturnFind._a_clickbutton == CATSEL.FindGroupButton')
    hint = [x for x in g.printed() if "still active" in x or "couldn't" in x]
    g.run('KeyParseReturnButton._s_PostClick(KeyParseReturnButton)')
    hidden = not g.L.eval('KeyParseReturnButton._shown')
    g.run('CATSEL._h_OnShow(CATSEL)')  # back on the category list later: button stays gone
    still_hidden = not g.L.eval('KeyParseReturnButton._shown')
    ok = g.L.eval('OPENED') and shown and "Dungeons" in text and macro == "/click KeyParseReturnCategory\n/click KeyParseReturnFind" \
        and cat and find and not hint and hidden and still_hidden and g.L.eval('KeyParseDB.returnTo') is None
    return ok, f"shown={shown} text={text} macro={macro!r} cat={cat} find={find} hint={hint} hidden={hidden},{still_hidden} out={g.printed()}"

@case("27. Search list after going back: '18-18' reminder, then the parsed group is highlighted")
def _():
    g = after_reload('t27')
    g.run('SEARCHBOX._text = "" ROW1 = NewW({ resultID = 9 }) ROW2 = NewW({ resultID = 7 }) SEARCHFRAMES = { ROW1 } '
          'rawset(SEARCHPANEL, "results", { 9, 11, 7 }) rawset(SEARCHPANEL, "applications", { 7 }) SEARCHCB()')
    hint1 = g.L.eval('SEARCHPANEL._label._text')
    g.run('SEARCHBOX._text = "18-18" SEARCHCB()')   # typed it again and searched; the group is scrolled off
    hint2 = g.L.eval('SEARCHPANEL._label._text')
    g.run('SEARCHFRAMES = { ROW1, ROW2 } SEARCHCB()')
    hint3 = g.L.eval('SEARCHPANEL._label._shown')
    glow2 = g.L.eval('ROW2._texs and ROW2._texs[1]._shown')
    glow1 = g.L.eval('ROW1._texs and ROW1._texs[1] and ROW1._texs[1]._shown')
    ok = "18-18" in hint1 and "#3" in hint2 and hint3 is False and glow2 is True and not glow1
    return ok, f"hint1={hint1!r} hint2={hint2!r} hint3={hint3} glow2={glow2} glow1={glow1}"

@case("32. Parsed group is pinned to the top of the search results (and /kp pin off leaves the order alone)")
def _():
    g = after_reload('t32', extra=' function LFGListUtil_SortSearchResults() end')
    hooked = g.L.eval('GHOOKS.LFGListUtil_SortSearchResults ~= nil')
    g.run('SEARCHBOX._text = "18-18" rawset(SEARCHPANEL, "searching", true) rawset(SEARCHPANEL, "results", { 9, 11, 7 }) '
          'GHOOKS.LFGListUtil_SortSearchResults(SEARCHPANEL)')
    while_searching = list(g.L.eval('SEARCHPANEL.results').values())
    g.run('rawset(SEARCHPANEL, "searching", false) GHOOKS.LFGListUtil_SortSearchResults(SEARCHPANEL)')
    pinned = list(g.L.eval('SEARCHPANEL.results').values())
    g.run('ROW = NewW({ resultID = 7 }) SEARCHFRAMES = { ROW } SEARCHCB()')
    hint = g.L.eval('SEARCHPANEL._label._text')
    g.run('SlashCmdList.KEYPARSE("pin off") rawset(SEARCHPANEL, "results", { 9, 11, 7 }) '
          'GHOOKS.LFGListUtil_SortSearchResults(SEARCHPANEL)')
    off = list(g.L.eval('SEARCHPANEL.results').values())
    ok = hooked and while_searching == [9, 11, 7] and pinned == [7, 9, 11] and "pinned" in (hint or "") and off == [9, 11, 7]
    return ok, f"hooked={hooked} searching={while_searching} pinned={pinned} hint={hint!r} off={off}"

@case("33. Companion passes Warcraft Logs points to the addon; 'Parses updated' says how many are left")
def _():
    wow = new_wow(TMP / 't33')
    fake = FakeWCL({("Pts", "dalaran"): dps_runs(15)}); fake.spent = 312
    c, cfg, api = companion(wow, fake, TMP / 't33'); cache = {}
    c.process(api, cfg, cache, [("Pts-Dalaran", "us")])
    data = (wow / 'Interface/AddOns/KeyParse_Data1/Data.lua').read_text(encoding='utf-8')
    g = Game(wow, db_lua='KeyParseDB = { requests = { ["Pts-Dalaran"] = os.time() - 5 } }')
    g.run('RunTimers() RunTimers()')
    said = " ".join(g.printed())
    status_before = len(g.printed()); g.run('SlashCmdList.KEYPARSE("status")')
    status = " ".join(g.printed()[status_before:])
    ok = ("spent = 312, limit = 1000" in data and "Parses updated. WCL points: |cff39d739688|r/1000 (resets in 2 min)" in said
          and "688|r/1000" in status and "unreported database limit" in status)
    return ok, f"data has points={'spent = 312' in data} chat={said[-120:]!r} status={status!r}"

@case("34. Search list: WCL points on a 2nd line under a KeyParse hint, or alone (no 'KeyParse:'); green to grey")
def _():
    g = after_reload('t34')
    g.run('KeyParse_Data.points = { spent = 1000, limit = 1000, reset = os.time() + 600 } '
          'SEARCHBOX._text = "" SEARCHFRAMES = {} SEARCHCB()')
    two = g.L.eval('SEARCHPANEL._label._text')
    wow = new_wow(TMP / 't34b'); g2 = Game(wow)
    g2.run('RunTimers() RunTimers() RunTimers() KeyParse_Data.points = { spent = 0, limit = 1000, reset = os.time() + 600 } '
           'SEARCHFRAMES = {} SEARCHCB()')
    one = g2.L.eval('SEARCHPANEL._label._text')
    g2.run('KeyParse_Data.points.reset = os.time() - 1 SEARCHCB()')
    after_reset = g2.L.eval('SEARCHPANEL._label._text')
    g2.run('KeyParse_Data.paused = os.time() + 1200 SEARCHCB()')
    paused = g2.L.eval('SEARCHPANEL._label._text')
    ok = (two == "KeyParse: type |cffffff0018-18|r + Enter\nWCL points: |cff8080800|r/1000 (resets in 10 min)"
          and one == "WCL points: |cff19ff191000|r/1000 (resets in 10 min)"
          and after_reset == "WCL points: |cff19ff191000|r/1000"
          and paused == "|cff808080WCL busy (database limit), retrying every 2 min|r")
    return ok, f"two={two!r} one={one!r} reset={after_reset!r} paused={paused!r}"

@case("35. Your own listing: WCL points in the corner of the dungeon picture")
def _():
    wow = new_wow(TMP / 't35'); g = Game(wow)
    g.run('RunTimers() RunTimers() RunTimers() KeyParse_Data.points = { spent = 312, limit = 1000, reset = os.time() + 600 } '
          'VIEWER._h_OnShow(VIEWER)')
    text = g.L.eval('VIEWER._label and VIEWER._label._text')
    shown = g.L.eval('VIEWER._label and VIEWER._label._shown')
    ok = text == "WCL points: |cff39d739688|r/1000 (resets in 10 min)" and shown is True
    return ok, f"text={text!r} shown={shown}"

@case("36. Raider.IO's copy-group button moves off Delist on your listing, and back afterwards")
def _():
    wow = new_wow(TMP / 't36')
    g = Game(wow, pre='VIEWER.RemoveEntryButton = NewW() RaiderIO_ExportButton = NewW({ ClearAllPoints = function(s) s._pts = {} end, '
                      'SetPoint = function(s, ...) table.insert(s._pts, { ... }) end })')
    g.run('RunTimers() RunTimers() RunTimers() VIEWER._h_OnShow(VIEWER)')
    on = g.L.eval('RaiderIO_ExportButton._pts[1][2] == VIEWER.RemoveEntryButton and RaiderIO_ExportButton._pts[1][1]')
    g.run('VIEWER._h_OnHide(VIEWER)')
    off = g.L.eval('RaiderIO_ExportButton._pts[1][2] == LFGListFrame and RaiderIO_ExportButton._pts[1][3]')
    wow2 = new_wow(TMP / 't36b'); g2 = Game(wow2)   # no Raider.IO installed: nothing breaks
    g2.run('RunTimers() RunTimers() RunTimers() VIEWER._h_OnShow(VIEWER) VIEWER._h_OnHide(VIEWER)')
    return on == "LEFT" and off == "BOTTOM", f"on={on} off={off}"

@case("37. Companion: fastest time per dungeon and logged specs go to the addon")
def _():
    wow = new_wow(TMP / 't37')
    fake = FakeWCL({("Speedy", "dalaran"): {12993: [(15, 60.0, 1_700_000, "Fire"), (15, 70.0, 1_900_000, "Fire"),
                                                    (15, 50.0, 1_650_000, "Frost")]}})
    c, cfg, api = companion(wow, fake, TMP / 't37'); cache = {}
    c.process(api, cfg, cache, [("Speedy-Dalaran", "us")])
    data = (wow / 'Interface/AddOns/KeyParse_Data1/Data.lua').read_text(encoding='utf-8')
    ok = "[12993] = { 3, 60.0, 1650 }" in data and 'specs = { dps = { ["Fire"] = 2, ["Frost"] = 1 } }' in data
    return ok, data[data.find('"Speedy'):][:260]

DUNGEON_DATA = (
    'KeyParse_Data.dungeons = { { 12993, "Altar of Fangs" }, { 12825, "Den of Nalorakk" } } '
    'KeyParse_Data.players["Ana-Thrall"] = { t = os.time(), v = 2, roles = { dps = { [15] = { 4, 70.0, d = { '
    '[12993] = { 2, 50.0, 1700 }, [12825] = { 2, 90.0, 1600 } } } } }, specs = { dps = { Fire = 4 } } } '
    'KeyParse_Data.players["Bo-Thrall"] = { t = os.time(), v = 2, roles = { dps = { [15] = { 3, 80.0, d = { '
    '[12993] = { 3, 80.0, 1700 } } }, [16] = { 1, 60.0, d = { [12993] = { 1, 60.0, 1700 } } } } }, specs = { dps = { Fire = 4 } } } '
    'KeyParse_Data.players["Cy-Thrall"] = { t = os.time(), v = 2, roles = { dps = { [15] = { 3, 40.0, d = { '
    '[12993] = { 3, 40.0, 1700 } } }, [16] = { 1, 30.0, d = { [12993] = { 1, 30.0, 2000 } } } } }, specs = { dps = { Fire = 4 } } } '
    'LISTING = { name = "+16 chill", activityIDs = { 7 } } '
    'ACTIVITIES = { [7] = { fullName = "Altar of Fangs (Mythic Keystone)", mapID = 2001 } } ')

@case("38. Applicant row is one number (avg of all runs +14 to +16 for a +16); ! for new, never timed, or spec without logs")
def _():
    wow = new_wow(TMP / 't38'); g = Game(wow)
    g.run('RunTimers() RunTimers() RunTimers() ' + DUNGEON_DATA +
          'SetApplicants({ { { "Ana-Thrall", "DAMAGER", 64 } }, { { "Bo-Thrall", "DAMAGER", 63 } }, '
          '{ { "Cy-Thrall", "DAMAGER", 63 } } }) VIEWER._h_OnShow(VIEWER)')
    ana, bo, cy = g.labels()
    want_ana = "|cff0070ff70|r|cffff9933!|r"   # 4 runs of 70 on +15; new to +16, and Frost (logs: Fire)
    want_bo = "|cffa335ee75|r"                 # (3x80 on +15 + 1x60 on +16) / 4 = 75; timed a +16 on Fire: no !
    want_cy = "|cff1eff0038|r|cffff9933!|r"    # (3x40 + 1x30) / 4 = 37.5; +16 but over the timer
    return (ana, bo, cy) == (want_ana, want_bo, want_cy), f"ana={ana!r} | bo={bo!r} | cy={cy!r}"

@case("39. Applicants sorted: healers first, then best parse, then no logs; /kp sort off leaves Blizzard's order")
def _():
    wow = new_wow(TMP / 't39'); g = Game(wow, pre='function LFGListUtil_SortApplicants() end')
    said = " ".join(g.printed())
    g.run('RunTimers() RunTimers() RunTimers() ' + DUNGEON_DATA +
          'SetApplicants({ { { "Ana-Thrall", "DAMAGER" } }, { { "Heals-Thrall", "HEALER" } }, { { "Bo-Thrall", "DAMAGER" } }, '
          '{ { "Nolog-Thrall", "DAMAGER" } } }) LIST = { 101, 102, 103, 104 } GHOOKS.LFGListUtil_SortApplicants(LIST)')
    on = list(g.L.eval('LIST').values())
    g.run('SlashCmdList.KEYPARSE("sort off") LIST = { 101, 102, 103, 104 } GHOOKS.LFGListUtil_SortApplicants(LIST)')
    off = list(g.L.eval('LIST').values())
    ok = on == [102, 103, 101, 104] and off == [101, 102, 103, 104] and "sorted: healers first" in said
    return ok, f"on={on} off={off} said={said[-200:]!r}"

@case("28. Your own listing: no back-to-search button (applicants show as before)")
def _():
    g = after_reload('t28', own_listing=True)
    shown = g.L.eval('KeyParseReturnButton and KeyParseReturnButton._shown')
    return g.L.eval('OPENED') and not shown, f"shown={shown}"

@case("29. Fetch button on your own applicant list still works (no search state, no crash)")
def _():
    wow = new_wow(TMP / 't29'); g = Game(wow)
    g.applicants([[("Bob-Thrall", "DAMAGER")]])
    g.run('FETCH._s_OnClick(FETCH, "LeftButton", false)')
    return bool(g.L.eval('RELOADED')) and g.L.eval('KeyParseDB.reopenAt') is not None, g.sv()


@case("30. Healer applicants are never auto-queued; their row says healer")
def _():
    wow = new_wow(TMP / 't30'); g = Game(wow)
    g.applicants([[("Healz-Thrall", "HEALER")], [("Pewpew-Thrall", "DAMAGER")], [("Shield-Thrall", "TANK")]])
    return g.requests() == ["Pewpew-Thrall", "Shield-Thrall"], f"queued={g.requests()}"

@case("31. Companion: healer runs dropped, no extra HPS query")
def _():
    wow = new_wow(TMP / 't31'); g = Game(wow)
    g.right_click("Hybrid", "Thrall"); g.run('LASTBTN["Get M+ parses"]()')
    fake = FakeWCL({("Hybrid", "thrall"): {12993: [(15, 90.0, 1000000, "Restoration"), (15, 40.0, 2000000, "Balance")]}})
    c, cfg, api = companion(wow, fake, TMP / 't31'); cache = {}
    write_sv(wow, g); c.process(api, cfg, cache, c.pending_requests(cfg, cache))
    roles = cache["players"]["Hybrid-Thrall"].get("roles", {})
    return len(fake.calls) == 1 and "heal" not in roles and "dps" in roles, f"calls={fake.calls} roles={roles}"

@case("40. Group checklist: Lust/Brez top-right above KeyParse notice and WCL points; +BL/+BR on applicants who fill a gap")
def _():
    wow = new_wow(TMP / 't40')   # VFS = the viewer's own text lines in creation order (notice, points)
    g = Game(wow, pre='VIEWER.CreateFontString = function() local fs = NewW() VFS = VFS or {} VFS[#VFS + 1] = fs return fs end')   # solo Paladin: brez yes, lust no
    g.run('SetApplicants({ { { "Sham-Thrall", "DAMAGER", nil, "SHAMAN" } }, { { "Tree-Thrall", "DAMAGER", nil, "DRUID" } }, '
          '{ { "Bob-Thrall", "DAMAGER", nil, "WARRIOR" } } }) VIEWER._h_OnShow(VIEWER)')
    g.ev("LFG_LIST_APPLICANT_LIST_UPDATED")
    check1 = g.L.eval('KeyParseGroupChecklist.text._text')
    shown1 = g.L.eval('KeyParseGroupChecklist._shown')
    sham, tree, bob = g.labels()
    want1 = ("|cffff5555Lust|r |TInterface\\RaidFrame\\ReadyCheck-NotReady:12|t  "
             "|cff33ff99Brez|r |TInterface\\RaidFrame\\ReadyCheck-Ready:12|t")
    tags_ok = sham.startswith("|cff33ff99+BL|r ") and "+B" not in tree and "+B" not in bob
    # top-right stack: checklist (at the picture's corner) > KeyParse notice > WCL points
    stack = g.L.eval('(function() local notice = VFS[1] '
                     'return KeyParseGroupChecklist._pt[2] == VIEWER.InfoBackground and notice._pt[2] == KeyParseGroupChecklist '
                     'and notice._text end)()')
    tags_ok = tags_ok and stack == "KeyParse: 3 lookups waiting (reload to fetch)"
    party_setup(g); g.ev("GROUP_ROSTER_UPDATE")   # a Mage joins: lust covered, the Shaman's tag goes away
    check2 = g.L.eval('KeyParseGroupChecklist.text._text')
    sham2 = g.labels()[0]
    g.run('IN_RAID = true'); g.ev("GROUP_ROSTER_UPDATE")
    hidden = g.L.eval('KeyParseGroupChecklist._shown') is False
    ok = check1 == want1 and shown1 is not False and tags_ok and "NotReady" not in check2         and "+BL" not in sham2 and hidden
    return ok, f"check1={check1!r} labels={(sham, tree, bob)} check2={check2!r} sham2={sham2!r} hidden={hidden} stack={stack!r}"

@case("41. Played-with history: finished keys remembered per player, shown in tooltips, kept over reload, cleared next season")
def _():
    wow = new_wow(TMP / 't41'); g = Game(wow)
    g.run('GUIDS["Player-1-A"] = { "Ally", "Area52" } GUIDS["Player-1-B"] = { "Bud", "" } '
          'COMPLETION = { mapChallengeModeID = 501, level = 16, time = 1700000, onTime = true, practiceRun = false, members = { '
          '{ memberGUID = "Player-0-SELF", name = "Taftonator" }, { memberGUID = "Player-1-A", name = "Ally" }, '
          '{ memberGUID = "Player-1-B", name = "Bud" } } }')
    g.ev("CHALLENGE_MODE_COMPLETED"); g.ev("CHALLENGE_MODE_COMPLETED")        # same run twice: counted once
    g.run('COMPLETION = { mapChallengeModeID = 502, level = 17, time = 2500000, onTime = false, practiceRun = false, members = { '
          '{ memberGUID = "Player-1-A", name = "Ally" } } }')
    g.ev("CHALLENGE_MODE_COMPLETED")
    g.run('COMPLETION = { mapChallengeModeID = 502, level = 2, time = 1, onTime = true, practiceRun = true, members = { '
          '{ memberGUID = "Player-1-B", name = "Bud" } } }')
    g.ev("CHALLENGE_MODE_COMPLETED")                                          # practice run: ignored
    said = [x for x in g.printed() if "remembered" in x]
    me = g.L.eval('KeyParseDB.history.players["Taftonator-Dalaran"]')
    g2 = Game(wow, db_lua=g.sv())                                             # /reload: still there
    g2.run('GUIDS["Player-1-A"] = { "Ally", "Area52" } TIP = {} TIPFN(GameTooltip, { guid = "Player-1-A" })')
    tip =list(g2.L.eval('TIP').values())
    bud_n = g2.L.eval('KeyParseDB.history.players["Bud-Dalaran"].n')
    g2.run('SEASON = 16 TIP = {} TIPFN(GameTooltip, { guid = "Player-1-A" })')  # new season: history cleared
    tip2 = [x for x in g2.L.eval('TIP').values() if "Played with" in x]
    ok = (len(said) == 2 and me is None and bud_n == 1
          and "Played with you | 2 keys, 1 timed" in tip
          and tip.index("   +17 Den of Nalorakk | |cffff5555depleted|r, 0m ago") < tip.index("   +16 Altar of Fangs | |cff33ff99timed|r, 0m ago")
          and not tip2)
    return ok, f"said={said} me={me} bud_n={bud_n} tip={tip} tip2={tip2}"

@case("42. Strong applicant: row number (avg +16 to +18 for a +18) 80+ -> star, tooltip, one chat line + taskbar flash")
def _():
    wow = new_wow(TMP / 't42')
    def runs(key, pct, n):
        return {12993: [(key, pct, 1_000_000 + i * 1000, "Fire") for i in range(n)]}
    fake = FakeWCL({("Star", "thrall"): runs(17, 95.0, 3),     # +17 (inside +16 to +18): strong
                    ("Old", "thrall"): runs(15, 97.0, 3),      # only +15: outside the range, row shows -
                    ("Thin", "thrall"): runs(17, 96.0, 1),     # 1 run < min runs 3
                    ("Mid", "thrall"): runs(16, 80.0, 3)})     # exactly 80: strong
    c, cfg, api = companion(wow, fake, TMP / 't42'); cache = {}
    names = ["Star-Thrall", "Old-Thrall", "Thin-Thrall", "Mid-Thrall"]
    c.process(api, cfg, cache, [(n, "us") for n in names])
    reqs = ", ".join(f'["{n}"] = os.time() - 5' for n in names)
    apps = ", ".join(f'{{ {{ "{n}", "DAMAGER" }} }}' for n in names)
    g = Game(wow, db_lua=f'KeyParseDB = {{ requests = {{ {reqs} }} }}',
             pre=f'LISTING = {{ name = "+18" }} SetApplicants({{ {apps} }}) function FlashClientIcon() FLASHED = (FLASHED or 0) + 1 end')
    g.run('RunTimers() RunTimers() RunTimers()')
    said = [x for x in g.printed() if "strong applicant" in x]
    labels = g.labels()
    star = "|TInterface\\TargetingFrame\\UI-RaidTargetingIcon_1:12|t"
    starred = [n for n, l in zip(names, labels) if l.startswith(star)]
    g.run('TIP = {} STAR = FRAMES[1].Members[1] STAR._h_OnEnter(STAR)')
    tip = [x for x in g.L.eval('TIP').values() if "strong applicant" in x]
    flashed = g.L.eval('FLASHED')
    g.run('SlashCmdList.KEYPARSE("min 1")')                    # Thin's single +17 run now counts
    starred2 = [n for n, l in zip(names, g.labels()) if l.startswith(star)]
    ok = (len(said) == 1 and "2 strong applicants (80+ avg on +16 to +18)" in said[0] and "Star-Thrall" in said[0]
          and said[0].index("Star-Thrall") < said[0].index("Mid-Thrall")
          and flashed == 1 and starred == ["Star-Thrall", "Mid-Thrall"] and len(tip) == 1 and "(80+ avg)" in tip[0]
          and labels[1] == "|cff888888-|r|cffff9933!|r"
          and starred2 == ["Star-Thrall", "Thin-Thrall", "Mid-Thrall"])
    return ok, f"said={said} flashed={flashed} starred={starred} tip={tip} starred2={starred2} labels={labels}"

SETTINGS_STUB = ('SETS = {} Settings = { VarType = { Boolean = "boolean", Number = "number" }, '
    'RegisterVerticalLayoutCategory = function() return { GetID = function() return 77 end }, { AddInitializer = function() end } end, '
    'RegisterProxySetting = function(_, var, t, name, def, get, set) local st = { get = get, set = set, def = def } SETS[var] = st return st end, '
    'CreateCheckbox = function() end, CreateSlider = function() end, CreateSliderOptions = function() return {} end, '
    'RegisterAddOnCategory = function(c) REGISTERED = c end, OpenToCategory = function(id) OPENEDCAT = id end } ')

@case("43. Options panel: every setting registered, changes apply, /kp options opens it; quiet chat skips info lines")
def _():
    wow = new_wow(TMP / 't43'); g = Game(wow, pre=SETTINGS_STUB)
    keys = sorted(k.replace("KeyParse_", "") for k in g.L.eval('SETS').keys())
    g.run('SETS.KeyParse_targetKey.set(17)'); key17 = g.L.eval('KeyParseDB.settings.targetKey')
    g.run('SETS.KeyParse_targetKey.set(0)'); auto = g.L.eval('KeyParseDB.settings.targetKey'), g.L.eval('SETS.KeyParse_targetKey.get()')
    g.run('VIEWER._h_OnShow(VIEWER) SETS.KeyParse_showChecklist.set(false)')
    hidden = g.L.eval('KeyParseGroupChecklist._shown') is False
    g.run('SlashCmdList.KEYPARSE("options")'); opened = g.L.eval('OPENEDCAT')
    g2 = Game(new_wow(TMP / 't43b'), db_lua='KeyParseDB = { settings = { quietChat = true }, requests = { ["X-Thrall"] = os.time() } }')
    quiet_said = " ".join(g2.printed())
    g3 = Game(new_wow(TMP / 't43c'), db_lua='KeyParseDB = { settings = { strongParse = 90 } }')   # saved by 0.11.0
    migrated = g3.L.eval('KeyParseDB.settings.strongParse')
    g4 = Game(new_wow(TMP / 't43d'), db_lua='KeyParseDB = { settings = { strongParse = 90, strongRangeAvg = true } }')
    kept = g4.L.eval('KeyParseDB.settings.strongParse')                                              # chosen later: kept
    want = sorted(["targetKey", "minRuns", "showInCombat", "wideGroupFinder", "sortApplicants", "showChecklist",
                   "autoQueueApplicants", "reloadOnLookup", "reopenGroupFinder", "pinParsedGroup", "alertStrong",
                   "strongIcon", "strongParse", "weakIcon", "showHistory", "quietChat"])
    ok = (keys == want and key17 == 17 and auto == (None, 0) and hidden and opened == 77
          and "Fetching" not in quiet_said and "sorted: healers first" not in quiet_said and migrated == 80 and kept == 90)
    return ok, f"keys={keys} key17={key17} auto={auto} hidden={hidden} opened={opened} quiet={quiet_said[-160:]!r} migrated={migrated} kept={kept}"

@case("44. Weak applicant: row number below 25 -> skull + tooltip line, only for keys up to +19")
def _():
    wow = new_wow(TMP / 't44')
    def runs(key, pct, n):
        return {12993: [(key, pct, 1_000_000 + i * 1000, "Fire") for i in range(n)]}
    fake = FakeWCL({("Weak", "thrall"): runs(18, 20.0, 3),     # grey, 3 runs: skull
                    ("Once", "thrall"): runs(18, 10.0, 1),     # 1 run < min runs 3: no skull
                    ("Okay", "thrall"): runs(18, 30.0, 3)})    # green: no skull
    c, cfg, api = companion(wow, fake, TMP / 't44'); cache = {}
    names = ["Weak-Thrall", "Once-Thrall", "Okay-Thrall"]
    c.process(api, cfg, cache, [(n, "us") for n in names])
    reqs = ", ".join(f'["{n}"] = os.time() - 5' for n in names)
    apps = ", ".join(f'{{ {{ "{n}", "DAMAGER" }} }}' for n in names)
    g = Game(wow, db_lua=f'KeyParseDB = {{ requests = {{ {reqs} }} }}',
             pre=f'LISTING = {{ name = "+18" }} SetApplicants({{ {apps} }})')
    g.run('RunTimers() RunTimers() RunTimers()')
    skull = "|TInterface\\TargetingFrame\\UI-RaidTargetingIcon_8:12|t"
    marked = [n for n, l in zip(names, g.labels()) if l.startswith(skull)]
    g.run('TIP = {} M = FRAMES[1].Members[1] M._h_OnEnter(M)')
    tip = [x for x in g.L.eval('TIP').values() if "weak applicant" in x]
    g.run('LISTING = { name = "+20" } VIEWER._h_OnShow(VIEWER)')        # pushing 20s: nobody is weak
    marked20 = [n for n, l in zip(names, g.labels()) if l.startswith(skull)]
    said = [x for x in g.printed() if "strong applicant" in x]
    ok = marked == ["Weak-Thrall"] and len(tip) == 1 and marked20 == [] and not said
    return ok, f"marked={marked} tip={tip} marked20={marked20} said={said} labels={g.labels()}"

@case("45. Release package: icon texture ships in media/ and every .toc's IconTexture points at it (no zip written)")
def _():
    import importlib, zipfile
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import build_release as b
    importlib.reload(b)
    written = {}
    class Fake:
        def __init__(s, path, *a, **k): s.path = path; written[Path(path).name] = []
        def __enter__(s): return s
        def __exit__(s, *a): pass
        def write(s, src, arc): written[Path(s.path).name].append(arc)
    real = b.zipfile.ZipFile
    b.zipfile.ZipFile = Fake
    try:
        b.main()
    finally:
        b.zipfile.ZipFile = real
    addon = next((v for k, v in written.items() if k.startswith("KeyParse-")), [])
    tocs = [(Path(__file__).resolve().parent.parent / f"addon/{d}/{d}.toc").read_text(encoding="utf-8")
            for d in ["KeyParse", "KeyParse_Data1", "KeyParse_Data2", "KeyParse_Data3"]]
    icon_ok = all("## IconTexture: Interface\AddOns\KeyParse\media\icon" in t for t in tocs)
    ok = "KeyParse/media/icon.tga" in addon and "KeyParse/media/logo.tga" in addon and icon_ok
    return ok, f"addon zip={addon} icon_ok={icon_ok}"

@case("46. Companion keeps running: rejected API key (warns in game, picks up a new key), locked Data.lua, unexpected errors")
def _():
    import json as js
    wow = new_wow(TMP / 't46')
    fake = FakeWCL({("Bob", "thrall"): dps_runs(15)})
    good_post = fake.post
    state = {"bad_key": True}
    def post(url, **kw):
        if "oauth" in url and state["bad_key"]:
            class R: status_code = 401; text = "invalid_client"
            return R()
        return good_post(url, **kw)
    fake.post = post
    c, cfg, api = companion(wow, fake, TMP / 't46'); cache = {}
    c.CONFIG_PATH = TMP / 't46' / 'config.json'
    c.CONFIG_PATH.write_text(js.dumps({"client_id": "id", "client_secret": "secret"}), encoding="utf-8")
    # 1) rejected key: no crash, request kept, problem written for the addon
    retry, wait = c.process(api, cfg, cache, [("Bob-Thrall", "us")])
    data = (wow / 'Interface/AddOns/KeyParse_Data1/Data.lua').read_text(encoding='utf-8')
    g = Game(wow, db_lua='KeyParseDB = { requests = { ["Bob-Thrall"] = os.time() - 5 } }')
    g.run('RunTimers() RunTimers() RunTimers()')
    said = [x for x in g.printed() if "companion:" in x]
    # 2) the player runs setup with a new key: picked up from config.json, lookup works, problem cleared
    state["bad_key"] = False
    c.CONFIG_PATH.write_text(js.dumps({"client_id": "id2", "client_secret": "secret2"}), encoding="utf-8")
    c.refresh_credentials(api)
    retry2, _ = c.process(api, cfg, cache, [("Bob-Thrall", "us")])
    data2 = (wow / 'Interface/AddOns/KeyParse_Data1/Data.lua').read_text(encoding='utf-8')
    # 3) Data.lua locked for a moment (antivirus/OneDrive): retried; locked for good: logged, no crash
    orig = Path.replace
    calls = {"n": 0}
    def flaky(self, target):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(13, "in use")
        return orig(self, target)
    Path.replace = flaky
    try:
        brief_ok = c.write_data_lua(cfg, cache) is True
        Path.replace = lambda self, target: (_ for _ in ()).throw(PermissionError(13, "in use"))
        locked_ok = c.write_data_lua(cfg, cache) is False
    finally:
        Path.replace = orig
    # 4) the watch loop survives an unexpected error and logs it with a traceback
    class Stop(BaseException): pass
    boom = {"n": 0}
    real_pending, real_sleep = c.pending_requests, c.time.sleep
    def pending(*a):
        boom["n"] += 1
        if boom["n"] == 1:
            raise KeyError("surprise")
        raise Stop()
    c.pending_requests = pending
    ticks = {"n": 0}
    def sleep(sec):
        ticks["n"] += 1
        if ticks["n"] > 50:
            raise Stop()
    c.time.sleep = sleep
    c.time_real = c.time.time
    t0 = c.time.time()
    c.time.time = lambda: t0 + ticks["n"] * 100   # each tick jumps 100 s, so the 15 s backoff passes
    try:
        c.watch(api, cfg, cache)
    except Stop:
        pass
    finally:
        c.pending_requests, c.time.sleep, c.time.time = real_pending, real_sleep, c.time_real
    logtxt = (TMP / 't46' / 'log.txt').read_text(encoding='utf-8')
    survived = boom["n"] == 2 and "keeps running" in logtxt and "KeyError: 'surprise'" in logtxt
    ok = (retry == [("Bob-Thrall", "us")] and wait == c.AUTH_RECHECK and 'problem = "Warcraft Logs rejected' in data
          and len(said) == 1 and not retry2 and 'problem = "",' in data2 and "Bob-Thrall" in data2
          and brief_ok and locked_ok and survived)
    return ok, (f"retry={retry} wait={wait} said={said} retry2={retry2} problem2={'problem = \"\",' in data2} "
                f"brief={brief_ok} locked={locked_ok} survived={survived} pending_calls={boom['n']}")

@case("47. Store prep: companion files move to %LOCALAPPDATA%\KeyParse once (never overwriting); Store app skips the Startup folder")
def _():
    import importlib, io, contextlib, shutil
    import companion as c
    importlib.reload(c)
    base = TMP / 't47'
    if base.exists():
        shutil.rmtree(base)
    old, new = base / 'old', base / 'new'
    old.mkdir(parents=True); new.mkdir(parents=True)
    (old / 'config.json').write_text('{"client_id": "old"}', encoding='utf-8')
    (old / 'cache.json').write_text('{"players": {}}', encoding='utf-8')
    (new / 'cache.json').write_text('{"players": {"Keep-Me": 1}}', encoding='utf-8')   # newer: must not be replaced
    moved = c.migrate_old_files(old, new)
    again = c.migrate_old_files(old, new)
    cfg_moved = (new / 'config.json').exists() and not (old / 'config.json').exists()
    cache_kept = "Keep-Me" in (new / 'cache.json').read_text(encoding='utf-8') and (old / 'cache.json').exists()
    data_dir_ok = c.DATA_DIR.name == "KeyParse" and c.CONFIG_PATH.parent == c.DATA_DIR
    not_packaged = c.is_packaged() is False          # tests run as plain Python
    launcher = base / 'Startup' / 'KeyParse Companion.bat'
    c.startup_launcher_path = lambda: launcher
    c.is_packaged = lambda: True
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        c.set_autostart(True)
    store_ok = "Settings > Apps > Startup" in out.getvalue() and not launcher.exists()
    importlib.reload(c)
    ok = moved == ["config.json"] and again == [] and cfg_moved and cache_kept and data_dir_ok and not_packaged and store_ok
    return ok, f"moved={moved} again={again} cfg_moved={cfg_moved} cache_kept={cache_kept} dir={c.DATA_DIR} packaged={not not_packaged} store={out.getvalue()!r}"

@case("48. Store package: manifest gets the identity + reserved name, 0.6.13 -> 0.6.13.0, placeholders refused, logos sized and transparent")
def _():
    import importlib, re as _re, shutil
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'store'))
    import build_store as b
    importlib.reload(b)
    real = {"display_name": "M+ KeyParse Companion", "name": "12345Taft.MKeyParseCompanion",
            "publisher": "CN=ABCD1234-0000-1111-2222-333344445555", "publisher_display_name": "Taft & Co"}
    placeholder = json.loads(b.IDENTITY.read_text(encoding='utf-8')) | {"name": "PASTE Package/Identity/Name"}
    m = b.render_manifest(real, "0.6.13")
    local = b.render_manifest(placeholder, "0.6.13")
    manifest_ok = ('Name="12345Taft.MKeyParseCompanion"' in m and 'Publisher="CN=ABCD1234-0000-1111-2222-333344445555"' in m
                   and 'Version="0.6.13.0"' in m and "<PublisherDisplayName>Taft &amp; Co</PublisherDisplayName>" in m
                   and m.count("M+ KeyParse Companion") == 3 and "runFullTrust" in m and "windows.startupTask" in m
                   and 'Executable="KeyParseCompanion.exe"' in m and "{{" not in m)
    local_ok = 'Name="KeyParse.Companion.LocalTest"' in local and "{{" not in local
    probs_ok = (b.identity_problems(real) == [] and len(b.identity_problems(placeholder)) >= 1
                and b.identity_problems(real | {"publisher": "ABCD"}) == ["publisher must start with CN="])
    try:
        b.msix_version("0.6.13.1.2"); bad_refused = False
    except ValueError:
        bad_refused = True
    ver_ok = b.msix_version("0.6.13") == "0.6.13.0" and b.msix_version("1") == "1.0.0.0" and bad_refused
    toc_ok = b.toc_version() == "0.6.16"
    out = TMP / 't48'
    if out.exists():
        shutil.rmtree(out)
    made = b.make_assets(out)
    from PIL import Image
    sizes_ok = all(Image.open(out / n).size == (s, s) for files in b.ASSETS.values() for n, s in files)
    big = Image.open(out / "Square150x150Logo.png")
    clear_corner = big.getpixel((0, 0))[3] == 0 and big.getpixel((150, 150))[3] == 255
    referenced = set(_re.findall(r'Assets\\(\w+)\.png', m))
    refs_ok = all(f"{r}.png" in made for r in referenced) and len(referenced) == 3
    cfg = b.pri_config('<r>\n\t<packaging>\n\t\t<x/>\n\t</packaging>\n\t<index root="\\" startIndexAt="\\">\n</index></r>')
    pri_ok = "packaging" not in cfg and 'startIndexAt="Assets"' in cfg and 'root="\\"' in cfg
    ok = manifest_ok and local_ok and probs_ok and ver_ok and toc_ok and sizes_ok and clear_corner and refs_ok and pri_ok
    return ok, (f"manifest={manifest_ok} local={local_ok} probs={probs_ok} ver={ver_ok} toc={toc_ok} sizes={sizes_ok} "
                f"transparent={clear_corner} refs={refs_ok} pri={pri_ok}")

@case("49. Test queue: fake applicants in KeyParse's own window get the real labels, icons, tooltip and sort; never looked up, saved or alerted")
def _():
    wow = new_wow(TMP / 't49')
    pre = SETTINGS_STUB + ('CreateSettingsButtonInitializer = function(name, text, click) TESTBTN = click return {} end '
                           'FlashClientIcon = function() FLASHED = (FLASHED or 0) + 1 end')
    g = Game(wow, pre=pre)
    # a REAL player who happens to have a preset's name: the real list must keep showing the real (weak) data
    g.run('KeyParse_Data.players["Pyrostar-TestRealm"] = { t = os.time(), v = 2, roles = { dps = { [16] = { 9, 10 } } } }')
    g.run('TESTBTN()')                                   # options panel button
    opened = g.L.eval('KeyParseTestQueue ~= nil')
    g.run('SlashCmdList.KEYPARSE("test")')               # /kp test
    q = 'KeyParseTestQueue'
    g.run(f'{q}.keyBox:SetText("18") {q}.keyBox._s_OnEnterPressed({q}.keyBox)')
    g.run(f'{q}.presetButton._s_OnClick({q}.presetButton) LASTBTN["All presets"]()')
    def rows():
        g.run(f'ROWS = {{}} for _, r in ipairs({q}.rows) do if r._shown ~= false and r.fake then ROWS[#ROWS+1] = r.fake.name .. " = " .. (r.Label._text or "") end end')
        return list(g.L.eval('ROWS').values())
    r1 = rows()
    names = [x.split(" = ")[0].split("-")[0] for x in r1]
    lab = {x.split(" = ")[0].split("-")[0]: x.split(" = ", 1)[1] for x in r1}
    order_ok = names == ["Holyglow", "Pyrostar", "Petlover", "Rarelogs", "Stabsalot", "Bonkbonk", "Hiddenguy"]
    labels_ok = ("RaidTargetingIcon_1" in lab["Pyrostar"] and "+BL" in lab["Pyrostar"] and "92" in lab["Pyrostar"]
                 and "RaidTargetingIcon_8" in lab["Bonkbonk"] and "!" in lab["Stabsalot"] and "!" in lab["Petlover"]
                 and "ff5555*" in lab["Rarelogs"] and "+BR" not in lab["Rarelogs"]      # you're a Paladin: brez covered
                 and "healer" in lab["Holyglow"] and "no logs" in lab["Hiddenguy"])
    g.run(f'TIP = {{}} {q}.rows[2]._s_OnEnter({q}.rows[2])')
    tip = " / ".join(g.L.eval('TIP').values())
    tip_ok = ("TEST applicant - not real" in tip and "strong applicant" in tip and "Played with you | 3 keys, 3 timed" in tip
              and "KeyParse Test Dungeon" in tip and "+16 to +18" in tip)
    g.run(f'{q}.groupButton._s_OnClick({q}.groupButton) LASTBTN["|cffffffffMage|r"]()')   # a Mage joins: lust covered
    no_bl = "+BL" not in [x for x in rows() if x.startswith("Pyrostar")][0]
    g.run(f'{q}.rows[2].Invite._s_OnClick({q}.rows[2].Invite)')                          # fake Invite: row goes away
    g.run(f'{q}.rows[1].Decline._s_OnClick({q}.rows[1].Decline)')                        # fake Decline
    after = [x.split(" = ")[0].split("-")[0] for x in rows()]
    removed_ok = "Pyrostar" not in after and "Holyglow" not in after and len(after) == 5
    # editor: a custom applicant
    g.run(f'{q}.addButton._s_OnClick({q}.addButton) local e = KeyParseTestEditor '
          'e.fields.name:SetText("Custom-Realm") e.keyRows[1].avg:SetText("99") e.keyRows[2].avg:SetText("99") '
          'e.keyRows[3].avg:SetText("99") e.keyRows[1].runs:SetText("4") e.keyRows[2].runs:SetText("4") e.keyRows[3].runs:SetText("4") '
          'e.saveButton._s_OnClick(e.saveButton)')
    r3 = rows()
    custom_ok = r3[0].startswith("Custom-Realm") and "RaidTargetingIcon_1" in r3[0]
    # isolation: nothing queued, saved, alerted or flashed; the real list still shows real data
    sv = g.sv()
    g.applicants([[("Pyrostar-TestRealm", "DAMAGER")]])
    real_label = g.labels()[0]
    said = " ".join(str(x) for x in g.printed())
    iso_ok = (g.requests() == [] and "TestRealm" not in sv and "Custom" not in sv and g.L.eval('FLASHED') is None
              and "strong applicant" not in said and "10" in real_label and "92" not in real_label
              and "RaidTargetingIcon_1" not in real_label)
    g.run('SlashCmdList.KEYPARSE("help")')
    help_ok = any("/kp test" in str(x) for x in g.printed())
    ok = opened and order_ok and labels_ok and tip_ok and no_bl and removed_ok and custom_ok and iso_ok and help_ok
    return ok, (f"opened={opened} order={names} labels={labels_ok} {lab} tip_ok={tip_ok} tip={tip[:300]!r} no_bl={no_bl} "
                f"after={after} custom={r3[:1]} iso={iso_ok} req={g.requests()} real={real_label!r} help={help_ok}")

@case("50. Quiet chat also hides 'Parses updated.' after a fetch; the strong-applicant alert and /kp status points still show")
def _():
    wow = new_wow(TMP / 't50')
    fake = FakeWCL({("Pts", "dalaran"): dps_runs(15)}); fake.spent = 312
    c, cfg, api = companion(wow, fake, TMP / 't50'); cache = {}
    c.process(api, cfg, cache, [("Pts-Dalaran", "us")])
    g = Game(wow, db_lua='KeyParseDB = { settings = { quietChat = true }, requests = { ["Pts-Dalaran"] = os.time() - 5 } }')
    g.run('RunTimers() RunTimers()')
    said = " ".join(g.printed())
    loaded = g.L.eval('KeyParse_Data.players["Pts-Dalaran"] ~= nil')
    before = len(g.printed()); g.run('SlashCmdList.KEYPARSE("status")')
    status = " ".join(g.printed()[before:])
    loud = Game(wow, db_lua='KeyParseDB = { requests = { ["Pts-Dalaran"] = os.time() - 5 } }')
    loud.run('RunTimers() RunTimers()')
    loud_said = " ".join(loud.printed())
    ok = loaded and "Parses updated" not in said and "688|r/1000" in status and "Parses updated" in loud_said
    return ok, f"loaded={loaded} quiet={said[-160:]!r} status={status[:120]!r} loud_has={'Parses updated' in loud_said}"

@case("51. /kp search: fetches with one reload, reopens on that player with keys, dungeons, timed runs, specs and history")
def _():
    wow = new_wow(TMP / 't51')
    # +15: Altar timed (1000s of 1800), Den over time (2000s of 1900); +14 Altar; Fire and Frost runs
    fake = FakeWCL({("Kalen", "area-52"): {12993: [(15, 91.0, 1_000_000, "Fire"), (15, 85.0, 1_100_000, "Fire"),
                                                   (14, 70.0, 1_200_000, "Frost")],
                                           12825: [(15, 40.0, 2_000_000, "Fire")]}})
    c, cfg, api = companion(wow, fake, TMP / 't51'); cache = {}
    g = Game(wow, db_lua='KeyParseDB = { history = { season = 15, players = { ["Kalen-Area52"] = { n = 2, timed = 1, '
                         'runs = { { t = os.time() - 7200, map = 501, lvl = 15, timed = true } } } } } }')
    g.run('SlashCmdList.KEYPARSE("search kalen-area 52")')
    queued = g.requests() == ["Kalen-Area52"] and g.L.eval('RELOADED') is True
    c.process(api, cfg, cache, [("Kalen-Area52", "us")])
    g2 = Game(wow, db_lua=g.sv())                      # the reload: window comes back on Kalen
    S = 'KeyParseSearch'
    shown = g2.L.eval(f'{S} ~= nil and {S}:IsShown()') and g2.L.eval(f'{S}.header._text') == "Kalen-Area52"
    keys = [g2.L.eval(f'{S}.keyRows[{i}].label._text') for i in (1, 2)]
    keys_ok = "+15" in keys[0] and "<" in keys[0] and "+14" in keys[1]
    d1 = " ".join(str(g2.L.eval(f'{S}.dungeonRows[1].{k}._text')) for k in ("name", "avg", "runs", "time"))
    d2 = " ".join(str(g2.L.eval(f'{S}.dungeonRows[2].{k}._text')) for k in ("name", "avg", "runs", "time"))
    title = g2.L.eval(f'{S}.dungeonTitle._text')
    dun_ok = ("Altar of Fangs" in d1 and "88.0" in d1 and "2 runs" in d1 and "33ff9916:40" in d1 and "30:00" in d1
              and "Den of Nalorakk" in d2 and "ff555533:20" in d2 and "timed 1 of 2" in title)
    specs = g2.L.eval(f'{S}.specs._text') or ""
    hist = g2.L.eval(f'{S}.history[1]._text') or ""
    extra_ok = "Fire" in specs and "Frost" in specs and "2 keys, 1 timed" in hist
    status_ok = (g2.L.eval(f'{S}.status._text') or "") == "" and g2.requests() == []
    # click the +14 row: its dungeons
    g2.run(f'{S}.keyRows[2]._s_OnClick({S}.keyRows[2])')
    k14 = "+14" in g2.L.eval(f'{S}.dungeonTitle._text') and "70.0" in g2.L.eval(f'{S}.dungeonRows[1].avg._text')
    # fresh data: searching again (other casing) shows it at once, no reload, one entry in Recent
    g2.run('RELOADED = nil SlashCmdList.KEYPARSE("search KALEN-area52")')
    again_ok = g2.L.eval('RELOADED') is None and g2.requests() == [] and g2.L.eval(f'{S}.recent[2]._shown') is False
    # in combat: queued, no reload, says so
    g2.run('InCombatLockdown = function() return true end SlashCmdList.KEYPARSE("search newguy")')
    combat_ok = (g2.L.eval('RELOADED') is None and g2.requests() == ["Newguy-Dalaran"]
                 and "Leave combat" in (g2.L.eval(f'{S}.status._text') or ""))
    g2.run('SlashCmdList.KEYPARSE("help")')
    help_ok = any("/kp search" in str(x) for x in g2.printed())
    ok = queued and shown and keys_ok and dun_ok and extra_ok and status_ok and k14 and again_ok and combat_ok and help_ok
    return ok, (f"queued={queued} req={g.requests()} shown={shown} keys={keys} d1={d1!r} d2={d2!r} title={title!r} "
                f"specs={specs!r} hist={hist!r} status_ok={status_ok} k14={k14} again={again_ok} combat={combat_ok} help={help_ok}")

print()
w = max(len(t) for t, _, _ in results)
for title, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {title.ljust(w)}  {'' if ok else detail}")
print(f"\n{sum(ok for _, ok, _ in results)}/{len(results)} passed")
