"""Test harness: runs the real KeyParse.lua against stubbed WoW APIs, and companion.py against a fake Warcraft Logs."""
import json, sys, time, shutil
from pathlib import Path
from lupa import LuaRuntime

REPO = Path(__file__).resolve().parent.parent
ROOT = REPO / 'addon'
sys.path.insert(0, str(REPO / 'companion'))

LUA_ENV = r'''
out = {} time = os.time format = string.format date = os.date
function print(s) table.insert(out, s) end
local W = {}
W.__index = function(t, k)
  if type(k) == "string" and k:sub(1,1) == "_" then return nil end
  if k == "IsShown" or k == "IsVisible" then return function(self) return self._shown ~= false end end
  if k == "GetWidth" then return function(self) return self._w or 100 end end
  if k == "SetWidth" then return function(self, w) self._w = w end end
  if k == "SetSize" then return function(self, w) self._w = w end end
  if k == "SetShown" then return function(self, v) self._shown = v and true or false end end
  if k == "memberIdx" or k == "resultID" or k == "_arrow" or k == "_kpListing" then return nil end
  if k == "Show" then return function(self) self._shown = true end end
  if k == "SetShown" then return function(self, v) self._shown = v and true or false end end
  if k == "Hide" then return function(self) self._shown = false end end
  if k == "Enable" then return function(self) self._enabled = true end end
  if k == "Disable" then return function(self) self._enabled = false end end
  if k == "SetText" then return function(self, v) self._text = v end end
  if k == "GetFontString" then return function() return nil end end
  if k == "GetStringWidth" then return function() return 60 end end
  if k == "GetAtlas" then return function() return "groupfinder-background-dungeons" end end
  if k == "SetPoint" then return function(self, ...) self._pt = {...} end end
  if k == "SetAttribute" then return function(self, a, v) rawset(self, "_a_" .. a, v) end end
  if k == "GetText" then return function(self) return rawget(self, "_text") end end
  if k == "SetScript" then return function(self, ev, fn) rawset(self, "_s_" .. ev, fn) end end
  if k == "HookScript" then return function(self, ev, fn) rawset(self, "_h_" .. ev, fn) end end
  if k == "GetParent" then return function(self) return rawget(self, "_parent") end end
  if k == "CreateFontString" then return function(self) local fs = NewW() rawset(self, "_label", fs) return fs end end
  if k == "CreateTexture" then return function(self) local t = NewW() local l = rawget(self, "_texs") or {} l[#l+1] = t rawset(self, "_texs", l) return t end end
  return function() end
end
function NewW(o) return setmetatable(o or {}, W) end
UIParent = NewW()
function CreateFrame(kind, name, parent, tmpl)
  local f = NewW({_parent = parent})
  if name then _G[name] = f end
  if kind == "Frame" and not parent then MAIN = f end
  if tmpl == "UIPanelButtonTemplate" then FETCH = f end
  if kind == "Button" and parent and (parent.memberIdx or parent.resultID) then rawset(parent, "_arrow", f) end
  return f
end
MY_REALM = "Dalaran"
function GetNormalizedRealmName() return MY_REALM end
function IsShiftKeyDown() return false end
function InCombatLockdown() return false end
function GetCurrentRegion() return 1 end
HOOKED = {} GHOOKS = {} function hooksecurefunc(a, b, c) if type(a) == "table" then table.insert(HOOKED, c) else GHOOKS[a] = b end end
timers = {} C_Timer = { After = function(d, fn) table.insert(timers, fn) end }
function RunTimers() local t = timers timers = {} for _, fn in ipairs(t) do fn() end end
SlashCmdList = {} Enum = { TooltipDataType = { Unit = 2 } }
TooltipDataProcessor = { AddTooltipPostCall = function(_, fn) TIPFN = fn end }
TIP = {} GameTooltip = NewW({ AddLine = function(_, s) table.insert(TIP, s) end, AddDoubleLine = function(_, a, b) table.insert(TIP, a .. " | " .. b) end })
GameTooltip_Hide = function() end
GUIDS = {}
function GetPlayerInfoByGUID(g)
  if g == "Player-0-SELF" then return "c", SELF[4], "r", "R", 2, SELF[1], SELF[2] end
  local i = tonumber(g:match("^Player%-0%-P(%d)$")) if i then local p = PARTY[i] return "c", p[4], "r", "R", 2, p[1], p[2] end
  local x = GUIDS[g] return "c", "C", "r", "R", 2, x[1], x[2] end
-- Group Finder
APPS, STATUS, ORDER = {}, {}, {}
local function Member(parent, idx) return NewW({ _parent = parent, memberIdx = idx, Name = NewW(), RoleIcon1 = NewW(), ItemLevel = NewW(), Rating = NewW() }) end
function SetApplicants(list) -- list of { {name, role}, ... } per application
  APPS, STATUS, ORDER, FRAMES = {}, {}, {}, {}
  for i, app in ipairs(list) do
    local id = 100 + i
    APPS[id] = app ; ORDER[#ORDER + 1] = id
    local f = NewW({ applicantID = id }) f.Members = {}
    for m = 1, #app do f.Members[m] = Member(f, m) end
    FRAMES[#FRAMES + 1] = f
  end
end
SetApplicants({})
LISTING = { name = "+16 chill" }
-- party / raid
PARTY = {}          -- e.g. { {"Tank1", "Thrall", "TANK", "WARRIOR"}, ... } (party1..4)
IN_RAID = false
SELF = { "Taftonator", "", "DAMAGER", "PALADIN" }
function IsInGroup() return #PARTY > 0 end
function IsInRaid() return IN_RAID end
function GetNumSubgroupMembers() return #PARTY end
function UnitGUID(u)
  if u == "player" then return "Player-0-SELF" end
  local i = tonumber((u or ""):match("^party(%d)$")) if i and PARTY[i] then return "Player-0-P" .. i end
  return nil
end
function UnitClass(u)
  if u == "player" then return "C", SELF[4], 0 end
  local i = tonumber((u or ""):match("^party(%d)$")) if i and PARTY[i] then return "C", PARTY[i][4], 0 end
end
function UnitGroupRolesAssigned(u)
  if u == "player" then return SELF[3] end
  local i = tonumber((u or ""):match("^party(%d)$")) return i and PARTY[i] and PARTY[i][3] or "NONE"
end
RAID_CLASS_COLORS = setmetatable({}, { __index = function() return { colorStr = "ffffffff" } end })
-- listings you can join
RESULTS = {}        -- resultID -> { leaderName=, members = { {name=, role=, class=, spec=, leader=}, ... } }
OWNED_KEY = nil
SEASON = 15
C_MythicPlus = { GetOwnedKeystoneLevel = function() return OWNED_KEY end, GetCurrentSeason = function() return SEASON end }
function UnitName(u) if u == "player" then return SELF[1] end end
-- Blizzard's M+ dungeons: challenge map id -> name, timer (s), instance map id
CHALLENGE = { [501] = { "Altar of Fangs", 1800, 2001 }, [502] = { "Den of Nalorakk", 1900, 2002 } }
C_ChallengeMode = {
  GetMapTable = function() local t = {} for id in pairs(CHALLENGE) do t[#t + 1] = id end return t end,
  GetMapUIInfo = function(id) local c = CHALLENGE[id] return c[1], id, c[2], nil, nil, c[3] end,
  GetChallengeCompletionInfo = function() return COMPLETION end,   -- set COMPLETION = {...} in a test
}
SPECS = { [63] = "Fire", [64] = "Frost" }
function GetSpecializationInfoByID(id) return id, SPECS[id] end
C_LFGList = {
  GetActiveEntryInfo = function() return LISTING end,
  HasActiveEntryInfo = function() return LISTING ~= nil end,
  GetApplications = function() return MYAPPS or {} end,
  GetApplicants = function() return ORDER end,
  GetApplicantInfo = function(id) return { numMembers = #APPS[id], applicationStatus = STATUS[id] or "applied" } end,
  GetApplicantMemberInfo = function(id, m) local a = APPS[id][m] return a[1], a[4] or "x", "x", 90, 700, 0, false, false, false, a[2], nil, 0, 0, nil, 0, a[3] end,
  GetActivityInfoTable = function(id) return id and ACTIVITIES and ACTIVITIES[id] end,
  GetSearchResultInfo = function(id) local r = RESULTS[id] return r and { leaderName = r.leaderName, numMembers = #r.members, partyGUID = r.guid } end,
  GetLfgCategoryInfo = function(id) return { name = id == 2 and "Dungeons" or "Other" } end,
  GetSearchResultPlayerInfo = function(id, i) local m = RESULTS[id].members[i]
    return { name = m.name, assignedRole = m.role, classFilename = m.class, specName = m.spec, isLeader = m.leader or false } end,
}
SEARCHFRAMES = {}
SEARCHPANEL = NewW({ ScrollBox = NewW({ GetFrames = function() return SEARCHFRAMES end, RegisterCallback = function(_, ev, fn) SEARCHCB = fn end }) })
MenuUtil = { CreateContextMenu = function(owner, gen) MENU = {} gen(owner, NewRoot()) end }
ScrollBoxListMixin = { Event = { OnUpdate = 1 } }
VIEWER = NewW({ NameColumnHeader = NewW(), RoleColumnHeader = NewW(), InfoBackground = NewW(), EntryName = NewW(), VoiceChatFrame = NewW({ _shown = false }),
  ScrollBox = NewW({ GetFrames = function() return FRAMES end }) })
CATBUTTONS = { NewW({ categoryID = 1, filters = 0 }), NewW({ categoryID = 2, filters = 0 }), NewW({ categoryID = 3, filters = 0 }) }
CATSEL = NewW({ CategoryButtons = CATBUTTONS, FindGroupButton = NewW() })
LFGListFrame = { ApplicationViewer = VIEWER, SearchPanel = SEARCHPANEL, CategorySelection = CATSEL }
PVEFrame = NewW({ _w = 563 }) LFGListPVEStub = NewW({ _w = 338 }) PVE_FRAME_BASE_WIDTH = 563
function PVEFrame_ShowFrame() end
function ReloadUI() RELOADED = true end
C_Texture = { GetAtlasInfo = function() return { width = 330, height = 110, file = 1, leftTexCoord = 0, rightTexCoord = 1, topTexCoord = 0, bottomTexCoord = 1 } end }
-- menus
MENU = {}
local function Desc(depth)
  local d = {} local pad = string.rep("  ", depth)
  function d:CreateTitle(t) table.insert(MENU, pad .. "[" .. t .. "]") end
  function d:CreateDivider() end
  function d:CreateCheckbox(t, get, set) table.insert(MENU, pad .. "[" .. (get() and "x" or " ") .. "] " .. t) LASTBTN = LASTBTN or {} LASTBTN[t] = set return Desc(depth + 1) end
  function d:CreateButton(t, cb) table.insert(MENU, pad .. t) local s = Desc(depth + 1) s._cb = cb LASTBTN = LASTBTN or {} LASTBTN[t] = cb return s end
  return d
end
function NewRoot() return Desc(0) end
MENUFNS = {} Menu = { ModifyMenu = function(tag, fn) MENUFNS[tag] = fn end, GetManager = function() return {} end }
MenuUtil = { CreateContextMenu = function(owner, gen) gen(owner, Desc(0)) end }
LOAD_FAIL = false
C_AddOns = { LoadAddOn = function(name)
  if LOAD_FAIL then return false, "DISABLED" end
  local f = io.open(ADDON_DIR .. "/" .. name .. "/Data.lua") if not f then return false, "MISSING" end
  local s = f:read("*a") f:close() load(s)() return true end }
'''


class Game:
    """One WoW session running the real addon."""
    def __init__(self, wow: Path, db_lua='KeyParseDB = nil', pre=''):
        self.L = LuaRuntime()
        self.L.globals().ADDON_DIR = str(wow / 'Interface/AddOns')
        self.L.execute(LUA_ENV)
        self.L.execute(db_lua)
        if pre:
            self.L.execute(pre)
        chunk = self.L.eval('function(p) local f = io.open(p) local s = f:read("*a") f:close() return load(s, "KeyParse.lua") end')(
            str(wow / 'Interface/AddOns/KeyParse/KeyParse.lua'))
        self.L.globals().CH = chunk
        self.L.execute('CH("KeyParse") MAIN._s_OnEvent(nil, "ADDON_LOADED", "KeyParse") MAIN._s_OnEvent(nil, "PLAYER_LOGIN")')
        self.run('RunTimers() RunTimers() RunTimers()')
        self.run('if HOOKED[1] then HOOKED[1]() end')   # first menu opened -> menus registered

    def run(self, code):
        return self.L.execute(code)

    def ev(self, name):
        self.run(f'MAIN._s_OnEvent(nil, "{name}")')

    def applicants(self, groups):
        lua = "{" + ",".join("{" + ",".join(f'{{"{n}","{r}"}}' for n, r in g) + "}" for g in groups) + "}"
        self.run(f'SetApplicants({lua}) VIEWER._h_OnShow(VIEWER)')
        self.ev("LFG_LIST_APPLICANT_LIST_UPDATED")

    def labels(self):
        self.run('RESULT = {} for _, f in ipairs(FRAMES) do for _, m in ipairs(f.Members) do RESULT[#RESULT+1] = (m._label and m._label._text) or "" end end')
        return list(self.L.eval('RESULT').values())

    def requests(self):
        return sorted(self.L.eval('KeyParseDB.requests').keys())

    def button(self):
        return self.L.eval('FETCH._text'), self.L.eval('FETCH._enabled')

    def right_click_listing(self, result_id):
        self.run(f'MENU = {{}} MENUFNS["MENU_LFG_FRAME_SEARCH_ENTRY"](NewW({{ resultID = {result_id} }}), NewRoot(), nil)')
        return list(self.L.eval('MENU').values())

    def right_click(self, name, server):
        self.run(f'MENU = {{}} MENUFNS["MENU_UNIT_PLAYER"](nil, NewRoot(), {{ which = "PLAYER", name = "{name}", server = "{server}" }})')
        return list(self.L.eval('MENU').values())

    def printed(self):
        return list(self.L.eval('out').values())

    def sv(self):
        """What WoW would write to SavedVariables on /reload."""
        return self.L.eval('''(function()
          local function ser(v, ind)
            if type(v) == "table" then
              local parts = {"{"}
              for k, x in pairs(v) do
                local key = type(k) == "string" and string.format("[%q]", k) or "[" .. k .. "]"
                parts[#parts+1] = ind .. "  " .. key .. " = " .. ser(x, ind .. "  ") .. ","
              end
              parts[#parts+1] = ind .. "}"
              return table.concat(parts, "\\n")
            elseif type(v) == "string" then return string.format("%q", v)
            else return tostring(v) end
          end
          return "\\nKeyParseDB = " .. ser(KeyParseDB, "") .. "\\n"
        end)()''')


def new_wow(tmp: Path):
    if tmp.exists():
        shutil.rmtree(tmp)
    addons = tmp / '_retail_/Interface/AddOns'
    addons.mkdir(parents=True)
    for d in ['KeyParse', 'KeyParse_Data1', 'KeyParse_Data2', 'KeyParse_Data3']:
        shutil.copytree(ROOT / d, addons / d)
    (tmp / '_retail_/WTF/Account/ACC1/SavedVariables').mkdir(parents=True)
    return tmp / '_retail_'


ENC = [{"id": i, "name": n} for i, n in [(12993, "Altar of Fangs"), (12825, "Den of Nalorakk"), (61762, "Kings' Rest"),
       (12813, "Murder Row"), (112521, "Ruby Life Pools"), (61877, "Temple of Sethraliss"), (12859, "The Blinding Vale"), (12923, "Voidscar Arena")]]


class FakeWCL:
    """Fake Warcraft Logs API. players: {(name, slug): {enc_id: [(key, pct, dur, spec), ...]}}"""
    def __init__(self, players, zone_id=55, encounters=ENC):
        self.players, self.zone_id, self.encounters, self.calls = players, zone_id, encounters, []

    def post(self, url, json=None, data=None, auth=None, headers=None, timeout=None):
        import json as js
        class R:
            def __init__(s, b): s.status_code, s._b, s.text = 200, b, js.dumps(b)
            def json(s): return s._b
            def raise_for_status(s): pass
        if "oauth" in url:
            return R({"access_token": "t"})
        q = json["query"]; v = json.get("variables") or {}
        rl = {"limitPerHour": 1000, "pointsSpentThisHour": getattr(self, "spent", 5), "pointsResetIn": 100}
        if "expansions" in q:
            return R({"data": {"worldData": {"expansions": [{"id": 7, "name": "Midnight", "zones": [
                {"id": self.zone_id, "name": f"Mythic+ Season {self.zone_id}", "encounters": self.encounters}]}]}, "rateLimitData": rl}})
        if "servers(" in q:
            return R({"data": {"worldData": {"region": {"servers": {"has_more_pages": False, "data": [
                {"name": "Dalaran", "normalizedName": "Dalaran", "slug": "dalaran"},
                {"name": "Azjol-Nerub", "normalizedName": "AzjolNerub", "slug": "azjolnerub"},
                {"name": "Area 52", "normalizedName": "Area52", "slug": "area-52"},
                {"name": "Mal'Ganis", "normalizedName": "Mal'Ganis", "slug": "malganis"},
                {"name": "Anvilmar", "normalizedName": "Anvilmar", "slug": "anvilmar"}]}}}, "rateLimitData": rl}})
        self.calls.append((v["name"], v["server"]))
        busy = getattr(self, "busy", {})
        if busy.get(v["name"], 0) > 0:
            busy[v["name"]] -= 1
            return R({"data": {"characterData": {"character": None}}, "errors": [{"message": "no database points remaining"}]})
        p = self.players.get((v["name"], v["server"]))
        metric = "hps" if "metric: hps" in q else "dps"
        if p is None:
            return R({"data": {"characterData": {"character": None}, "rateLimitData": rl}})
        ch = {}
        for e in self.encounters:
            ranks = [{"bracketData": k, "rankPercent": pct, "duration": dur, "spec": spec, "amount": 1.0}
                     for (k, pct, dur, spec) in p.get(e["id"], [])]
            ch[f"d{e['id']}"] = {"ranks": ranks}
        return R({"data": {"characterData": {"character": ch}, "rateLimitData": rl}})


def companion(wow: Path, fake: FakeWCL, tmp: Path):
    import importlib, companion as c
    importlib.reload(c)
    c.time.sleep = lambda s: None
    c.CACHE_PATH = tmp / 'cache.json'
    c.LOG_PATH = tmp / 'log.txt'
    c.requests.post = fake.post
    cfg = {"wow_retail_path": str(wow)}
    api = c.WCL("id", "secret")
    return c, cfg, api
