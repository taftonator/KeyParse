-- KeyParse: shows a player's average Warcraft Logs M+ parse at a key level.
--
-- How data gets in and out (WoW addons can't use the internet or read files mid-session):
--   OUT: lookups are queued in KeyParseDB.requests, which WoW saves to disk on /reload.
--   IN:  the companion app writes results into KeyParse_Data1..3, small load-on-demand
--        addons. We load them a few seconds AFTER login, which gives the companion time
--        to fetch the players queued by that same /reload. One reload, no second one.

local ADDON_NAME = ...

local REGION_KEYS = { [1] = "us", [2] = "kr", [3] = "eu", [4] = "tw", [5] = "cn" }
local ROLE_LABEL = { dps = "DPS", heal = "Healer", tank = "Tank" }
local LFG_ROLE = { DAMAGER = "dps", HEALER = "heal", TANK = "tank" }
local DEFAULT_SETTINGS = {
    minRuns = 3, targetKey = nil, showInCombat = false, autoQueueApplicants = true, reopenGroupFinder = true,
    wideGroupFinder = true, reloadOnLookup = true, pinParsedGroup = true, sortApplicants = true,
    showChecklist = true, showHistory = true, quietChat = false,
    alertStrong = true, strongIcon = true, strongParse = 80, weakIcon = true,
}
local STALE_REQUEST = 24 * 60 * 60     -- forget lookups that never came back after a day
local REFRESH_AFTER = 20 * 60 * 60     -- auto-queue applicants again before the companion's 24h expiry
local SLOT_DELAYS = { 1, 5, 12 }       -- seconds after login to try each data slot

local issecret = _G.issecretvalue or function() return false end
local LabelText, FillKeysMenu, FetchAndReload -- defined in the Group Finder section, used by the right-click menu
local LoadAddOn = (C_AddOns and C_AddOns.LoadAddOn) or _G.LoadAddOn
-- Set ONLY while the test queue draws a row or tooltip (see "test queue"): the real label/tooltip/sort code
-- then reads fake players, your test key, test group and test history from it, and never real data.
local TEST

KeyParse_Data = { generated = 0, season = "", players = {} }

-------------------------------------------------------------------- helpers

local function Print(msg)
    print("|cff33ff99KeyParse|r: " .. msg)
end

-- True when none of the values are Midnight "secret values" (which we can't read).
local function IsSafe(...)
    for i = 1, select("#", ...) do
        local v = select(i, ...)
        if v ~= nil and issecret(v) then
            return false
        end
    end
    return true
end

-- Builds the "Name-Realm" key the companion and the data use.
local function FullName(name, realm)
    if not name or not IsSafe(name, realm) or name == "" then
        return nil
    end
    local short, rest = name:match("^([^%-]+)%-(.+)$")
    if short then
        name, realm = short, rest -- already "Name-Realm"
    end
    if not realm or realm == "" then
        realm = GetNormalizedRealmName()
    end
    if not realm or realm == "" then
        return nil
    end
    -- Same form Blizzard uses for applicants: no spaces or dashes ("Area 52" / "Azjol-Nerub" -> "Area52" / "AzjolNerub")
    return name .. "-" .. (realm:gsub("[%s%-]", ""))
end

local function GetPlayer(full)
    if TEST then
        return full and TEST.players[full]
    end
    return full and KeyParse_Data.players[full]
end

local function CountKeys(t)
    local n = 0
    for _ in pairs(t) do
        n = n + 1
    end
    return n
end

-- Warcraft Logs parse colors.
local function ParseColor(pct)
    if pct >= 100 then return "e5cc80" end
    if pct >= 99 then return "e268a8" end
    if pct >= 95 then return "ff8000" end
    if pct >= 75 then return "a335ee" end
    if pct >= 50 then return "0070ff" end
    if pct >= 25 then return "1eff00" end
    return "9d9d9d"
end

local function RunCount(keys)
    local n = 0
    for _, v in pairs(keys) do
        n = n + v[1]
    end
    return n
end

-- The role this player has the most logged runs in.
local function MainRole(p)
    local best, bestN
    for role, keys in pairs(p.roles or {}) do
        local n = RunCount(keys)
        if not bestN or n > bestN then
            best, bestN = role, n
        end
    end
    return best
end

-- "+16" in the title of the group you listed, if there is one.
local function ListingKey()
    if not C_LFGList or not C_LFGList.GetActiveEntryInfo then
        return nil
    end
    local ok, info = pcall(C_LFGList.GetActiveEntryInfo)
    if not ok or not info then
        return nil -- not listing a group
    end
    -- A title like "+16 chill" names the key; "LF +2 dps for 15" doesn't, so only trust "+N" at the start.
    if IsSafe(info.name) and type(info.name) == "string" then
        local n = tonumber(info.name:match("^%s*%+%s*(%d+)"))
        if n and n >= 2 then
            return n
        end
    end
    -- Otherwise assume you're listing your own keystone.
    if C_MythicPlus and C_MythicPlus.GetOwnedKeystoneLevel then
        local ok2, lvl = pcall(C_MythicPlus.GetOwnedKeystoneLevel)
        if ok2 and type(lvl) == "number" and lvl >= 2 then
            return lvl
        end
    end
end

-- The key you're pushing: /kp key N wins, otherwise your listing's "+N", otherwise auto.
local function TargetKey()
    if TEST then
        return TEST.key
    end
    return KeyParseDB.settings.targetKey or ListingKey()
end

-- Which key level to show. Returns level, isLowSample.
-- No target: highest key with at least minRuns runs.
-- Target +16: highest key BELOW 16 with at least minRuns runs.
local function PickKey(keys, target)
    local minRuns = KeyParseDB.settings.minRuns
    local ceiling = target and (target - 1) or math.huge
    local top
    for lvl, v in pairs(keys) do
        if lvl <= ceiling and v[1] >= minRuns and (not top or lvl > top) then
            top = lvl
        end
    end
    if top then
        return top, false
    end
    for lvl in pairs(keys) do
        if lvl <= ceiling and (not top or lvl > top) then
            top = lvl
        end
    end
    return top, true
end

local function AgeText(t)
    local days = math.floor((time() - (t or 0)) / 86400)
    if days >= 2 then
        return format(" |cff888888(%dd old)|r", days)
    end
    return ""
end

-- "Murder Row (Mythic Keystone)" / "Murder Row" -> "murderrow", so Blizzard and Warcraft Logs names match.
local function NormName(s)
    if type(s) ~= "string" then
        return ""
    end
    return (s:lower():gsub("%b()", ""):gsub("[^%w]", ""))
end

-- Blizzard's M+ dungeons: timer and name, by normalized name and by instance map ID.
local challengeByName, challengeByMap
local function LoadChallengeMaps()
    if challengeByName or not (C_ChallengeMode and C_ChallengeMode.GetMapTable) then
        return
    end
    local ok, maps = pcall(C_ChallengeMode.GetMapTable)
    if not ok or type(maps) ~= "table" or #maps == 0 then
        return -- not ready yet (early in login): try again next time
    end
    challengeByName, challengeByMap = {}, {}
    for _, cm in ipairs(maps) do
        local ok2, name, _, timeLimit, _, _, mapID = pcall(C_ChallengeMode.GetMapUIInfo, cm)
        if ok2 and IsSafe(name) and type(name) == "string" then
            local e = { name = name, timer = type(timeLimit) == "number" and timeLimit or nil }
            challengeByName[NormName(name)] = e
            if type(mapID) == "number" then
                challengeByMap[mapID] = e
            end
        end
    end
end

-- Warcraft Logs' dungeon list { {encounterID, name}, ... } (the test queue's own one while it draws).
local function Dungeons()
    return TEST and TEST.dungeons or KeyParse_Data.dungeons or {}
end

-- Timer (seconds) of a Warcraft Logs dungeon, or nil if Blizzard's list doesn't have it.
local function DungeonTimer(encounterID)
    if TEST then
        return TEST.timers[encounterID]
    end
    LoadChallengeMaps()
    for _, d in ipairs(Dungeons()) do
        if d[1] == encounterID then
            local e = challengeByName and challengeByName[NormName(d[2])]
            return e and e.timer
        end
    end
end

-- The dungeon of the group you listed, as Warcraft Logs' id and name. nil if not listing a dungeon.
local function ListingDungeon()
    if TEST then
        return TEST.dungeons[1][1], TEST.dungeons[1][2]
    end
    if not C_LFGList or not C_LFGList.GetActiveEntryInfo then
        return nil
    end
    local ok, info = pcall(C_LFGList.GetActiveEntryInfo)
    if not ok or type(info) ~= "table" then
        return nil
    end
    local activityID = (type(info.activityIDs) == "table" and info.activityIDs[1]) or info.activityID
    local ok2, act = pcall(C_LFGList.GetActivityInfoTable, activityID)
    if not ok2 or type(act) ~= "table" then
        return nil
    end
    local want = {}
    LoadChallengeMaps()
    local cm = challengeByMap and type(act.mapID) == "number" and challengeByMap[act.mapID]
    if cm then
        want[NormName(cm.name)] = true
    end
    if IsSafe(act.fullName) then
        want[NormName(act.fullName)] = true
    end
    for _, d in ipairs(Dungeons()) do
        if want[NormName(d[2])] then
            return d[1], d[2]
        end
    end
end

-- Has this player done (and timed) your key level? "new": no logged runs at +target or higher.
-- "untimed": runs there, but none in time. nil: fine, or can't tell.
local function Experience(p, role, target)
    local keys = target and p and p.roles and p.roles[role]
    if not keys then
        return nil
    end
    local any, timed, unknown = false, false, false
    for lvl, v in pairs(keys) do
        if lvl >= target then
            any = true
            for enc, d in pairs(v.d or {}) do
                local timer = DungeonTimer(enc)
                if d[3] and timer then
                    timed = timed or d[3] <= timer
                else
                    unknown = true -- older data, or a dungeon Blizzard's list doesn't name the same way
                end
            end
        end
    end
    if not any then
        return "new"
    end
    if not timed and not unknown then
        return "untimed"
    end
end

-- Applied as a spec they have no logs on? Returns the specs they do have logs on ("Fire, Arcane").
local function SpecMismatch(p, role, appliedSpec)
    local logged = appliedSpec and p and p.specs and p.specs[role]
    if not logged or not next(logged) then
        return nil
    end
    local want = NormName(appliedSpec)
    local names = {}
    for spec in pairs(logged) do
        if NormName(spec) == want then
            return nil
        end
        names[#names + 1] = spec
    end
    table.sort(names, function(a, b) return logged[a] > logged[b] end)
    return table.concat(names, ", ")
end

-- Everything the tooltip and applicant labels need. preferredRole: "dps"/"heal"/"tank" or nil.
-- Returns state, and for state "ok": role, level, runs, avg, lowSample
local function Summarize(full, preferredRole)
    local p = GetPlayer(full)
    if not p then
        return (not TEST and KeyParseDB.requests[full]) and "queued" or "none"
    end
    if p.error then
        return "error"
    end
    if p.missing then
        return "missing"
    end
    local role = (preferredRole and p.roles[preferredRole]) and preferredRole or MainRole(p)
    if not role then
        return "missing"
    end
    local keys = p.roles[role]
    local lvl, low = PickKey(keys, TargetKey())
    if not lvl then
        return "nokey", role
    end
    return "ok", role, lvl, keys[lvl][1], keys[lvl][2], low
end

-- The one number on an applicant's row: the average of ALL their runs from 2 keys below the key you're
-- pushing up to that key (listing +18 -> every +16, +17 and +18 run together, weighted by runs).
-- No target key: their shown key's average (PickKey). Returns state, role, avg, runs, lo, hi;
-- state "norange" = has logs but no runs in that range.
local function RangeAvg(full, preferredRole)
    local state, role = Summarize(full, preferredRole)
    if state ~= "ok" and state ~= "nokey" then
        return state, role
    end
    local keys = GetPlayer(full).roles[role]
    local target = TargetKey()
    local lo, hi
    if target then
        lo, hi = target - 2, target
    else
        lo = PickKey(keys, nil)
        hi = lo
    end
    local runs, sum = 0, 0
    for lvl = lo or 1, hi or 0 do
        local e = keys[lvl]
        if e then
            runs, sum = runs + e[1], sum + e[1] * e[2]
        end
    end
    if runs == 0 then
        return "norange", role, nil, 0, lo, hi
    end
    return "ok", role, sum / runs, runs, lo, hi
end

-------------------------------------------------------------------- tooltip lines

-- appliedSpec: the spec an applicant applied as (Group Finder only), for the spec check.
local function AddParseLines(tooltip, full, preferredRole, appliedSpec)
    local state, role, lvl, n, avg, low = Summarize(full, preferredRole)
    if state == "none" then
        tooltip:AddLine("KeyParse: no data (right-click > Get M+ parses)", 0.5, 0.5, 0.5)
        return
    elseif state == "queued" then
        tooltip:AddLine("KeyParse: lookup queued (/reload to fetch)", 0.6, 0.6, 0.6)
        return
    elseif state == "error" then
        tooltip:AddLine("KeyParse: lookup failed - retried automatically after 10 min", 1, 0.4, 0.4)
        return
    elseif state == "missing" then
        tooltip:AddLine("KeyParse: no public M+ logs", 0.5, 0.5, 0.5)
        return
    elseif state == "nokey" then
        tooltip:AddLine(format("KeyParse: no logged runs below +%d", TargetKey() or 0), 0.5, 0.5, 0.5)
        return
    end

    local p = GetPlayer(full)
    tooltip:AddDoubleLine(
        "KeyParse " .. (ROLE_LABEL[role] or role),
        format("|cff%s%d|r avg on +%d (%d run%s)%s%s",
            ParseColor(avg), math.floor(avg + 0.5), lvl, n, n == 1 and "" or "s",
            low and " |cffff5555low sample|r" or "", AgeText(p.t)),
        1, 0.82, 0, 1, 1, 1)

    -- the dungeon of the group you listed, at the same key level
    local encID, encName = ListingDungeon()
    local dd = encID and p.roles[role][lvl].d and p.roles[role][lvl].d[encID]
    if dd then
        tooltip:AddDoubleLine("   " .. encName, format("|cff%s%d|r on +%d (%d run%s)", ParseColor(dd[2]),
            math.floor(dd[2] + 0.5), lvl, dd[1], dd[1] == 1 and "" or "s"), 0.8, 0.8, 0.8, 1, 1, 1)
    elseif encID then
        tooltip:AddLine(format("   No %s parses on +%d", encName, lvl), 0.5, 0.5, 0.5)
    end
    local target = TargetKey()
    local exp = Experience(p, role, target)
    if exp == "new" then
        tooltip:AddLine(format("   ! No logged runs at +%d or higher", target), 1, 0.6, 0.2)
    elseif exp == "untimed" then
        tooltip:AddLine(format("   ! Never timed +%d or higher (in logs)", target), 1, 0.6, 0.2)
    end
    local otherSpecs = SpecMismatch(p, role, appliedSpec)
    if otherSpecs then
        tooltip:AddLine(format("   ! Applied as %s, but logs are %s", appliedSpec, otherSpecs), 1, 0.6, 0.2)
    end

    if IsShiftKeyDown() then
        for r, rkeys in pairs(p.roles) do
            local levels = {}
            for k in pairs(rkeys) do
                levels[#levels + 1] = k
            end
            table.sort(levels, function(a, b) return a > b end)
            for _, k in ipairs(levels) do
                tooltip:AddDoubleLine(
                    format("   %s +%d", ROLE_LABEL[r] or r, k),
                    format("|cff%s%.1f|r (%d)", ParseColor(rkeys[k][2]), rkeys[k][2], rkeys[k][1]),
                    0.8, 0.8, 0.8, 1, 1, 1)
            end
        end
    end
end

-------------------------------------------------------------------- played-with history
-- Every finished key (timed or depleted, not practice runs) is remembered per player in
-- KeyParseDB.history (SavedVariables: written on logout/reload, survives a PC shutdown). Cleared when a
-- new M+ season starts. Shown in tooltips only: applicants, mouseover, search-list leaders.
-- KeyParseDB.history = { season = 15, players = { ["Name-Realm"] = { n = 3, timed = 2, runs = {
--     { t = time, map = challengeMapID, lvl = 16, timed = true }, ... newest last, at most HISTORY_KEEP } } } }

local HISTORY_KEEP = 10      -- runs kept per player (the counts keep going)
local HISTORY_SHOWN = 3      -- newest runs listed in a tooltip

local function CurrentSeason()
    local ok, s = pcall(function() return C_MythicPlus and C_MythicPlus.GetCurrentSeason() end)
    return ok and IsSafe(s) and type(s) == "number" and s > 0 and s or nil
end

-- KeyParseDB.history, emptied first if the season changed (only when the season is known).
local function History()
    if TEST then
        return TEST.history
    end
    local h = KeyParseDB.history
    if type(h) ~= "table" or type(h.players) ~= "table" then
        h = { players = {} }
        KeyParseDB.history = h
    end
    local season = CurrentSeason()
    if season and h.season ~= season then
        if h.season then
            h.players = {}
        end
        h.season = season
    end
    return h
end

local lastRecorded
local function RecordCompletedKey()
    local ok, info = pcall(function() return C_ChallengeMode.GetChallengeCompletionInfo() end)
    if not ok or type(info) ~= "table" or not IsSafe(info.mapChallengeModeID, info.level, info.onTime, info.practiceRun)
        or info.practiceRun or not info.level or info.level <= 0 or type(info.members) ~= "table" then
        return 0
    end
    local id = format("%s:%s:%s", tostring(info.mapChallengeModeID), tostring(info.level), tostring(info.time))
    if id == lastRecorded then
        return 0 -- the event fired twice for the same run
    end
    lastRecorded = id
    local me = FullName(UnitName and UnitName("player"), GetNormalizedRealmName())
    local players = History().players
    local count = 0
    for _, m in ipairs(info.members) do
        local full
        local guid = m.memberGUID
        if guid and IsSafe(guid) then
            local ok2, _, _, _, _, _, name, realm = pcall(GetPlayerInfoByGUID, guid)
            full = ok2 and FullName(name, realm) or nil
        end
        full = full or FullName(m.name)
        if full and full ~= me then
            local e = players[full] or { n = 0, timed = 0, runs = {} }
            players[full] = e
            e.n = e.n + 1
            e.timed = e.timed + (info.onTime and 1 or 0)
            table.insert(e.runs, { t = time(), map = info.mapChallengeModeID, lvl = info.level, timed = info.onTime and true or false })
            while #e.runs > HISTORY_KEEP do
                table.remove(e.runs, 1)
            end
            count = count + 1
        end
    end
    return count
end

local function AgoText(t)
    local s = math.max(0, time() - (t or 0))
    if s < 3600 then
        return format("%dm ago", math.floor(s / 60))
    elseif s < 86400 then
        return format("%dh ago", math.floor(s / 3600))
    end
    return format("%dd ago", math.floor(s / 86400))
end

local function DungeonName(mapID)
    if TEST then
        return TEST.dungeons[1][2]
    end
    local ok, name = pcall(C_ChallengeMode.GetMapUIInfo, mapID)
    return ok and IsSafe(name) and name or ("dungeon " .. tostring(mapID))
end

local function AddHistoryLines(tooltip, full)
    if not KeyParseDB.settings.showHistory then
        return
    end
    local e = History().players[full] -- History() also drops last season's runs
    if not e or not e.n or e.n == 0 then
        return
    end
    tooltip:AddDoubleLine("Played with you", format("%d key%s, %d timed", e.n, e.n == 1 and "" or "s", e.timed or 0),
        1, 0.82, 0, 1, 1, 1)
    local runs = e.runs or {}
    for i = #runs, math.max(1, #runs - HISTORY_SHOWN + 1), -1 do
        local r = runs[i]
        tooltip:AddDoubleLine(format("   +%d %s", r.lvl or 0, DungeonName(r.map)),
            format("%s, %s", r.timed and "|cff33ff99timed|r" or "|cffff5555depleted|r", AgoText(r.t)),
            0.8, 0.8, 0.8, 1, 1, 1)
    end
end

-- Everything KeyParse adds to a player's tooltip.
local function AddLines(tooltip, full, preferredRole, appliedSpec)
    if not full then
        return
    end
    AddParseLines(tooltip, full, preferredRole, appliedSpec)
    AddHistoryLines(tooltip, full)
end

-- Unit tooltips (world, party frames, nameplates). Uses the GUID so we never touch secret unit tokens.
local function OnUnitTooltip(tooltip, data)
    if tooltip ~= GameTooltip then
        return
    end
    if InCombatLockdown() and not KeyParseDB.settings.showInCombat then
        return
    end
    local guid = data and data.guid
    if not guid or not IsSafe(guid) or not guid:find("^Player%-") then
        return
    end
    local ok, _, _, _, _, _, name, realm = pcall(GetPlayerInfoByGUID, guid)
    if ok and IsSafe(name, realm) then
        AddLines(tooltip, FullName(name, realm))
    end
end

-------------------------------------------------------------------- lookup queue

local UpdateFetchButton -- defined in the Group Finder section

local function PendingCount()
    return CountKeys(KeyParseDB.requests)
end

-- KeyParse is a DPS tool: healers are never looked up (saves Warcraft Logs points).
local function Queue(full, quiet, fromApplicants, role)
    if not full or TEST then -- never look up a test-queue name
        return false
    end
    if role == "heal" then
        if not quiet then
            Print(format("|cffffffff%s|r is a healer. KeyParse only looks up DPS (and tanks).", full))
        end
        return false
    end
    KeyParseDB.requests[full] = time()
    KeyParseDB.fromApplicants[full] = fromApplicants or nil
    if not quiet then
        Print(format("Queued |cffffffff%s|r. |cffffff00/reload|r to fetch (the companion app must be running).", full))
    end
    if UpdateFetchButton then
        UpdateFetchButton()
    end
    return true
end

-- Needs a lookup: never fetched, or fetched a while ago, and not already queued.
local function NeedsLookup(full)
    if not full or KeyParseDB.requests[full] then
        return false
    end
    local p = GetPlayer(full)
    if p and p.error then
        return time() - (p.t or 0) > 10 * 60 -- failed lookups get retried after 10 minutes
    end
    if p and not p.missing and (p.v or 1) < 2 then
        return true -- saved before per-dungeon detail existed
    end
    return not p or time() - (p.t or 0) > REFRESH_AFTER
end

-- Drop requests that already have newer data, or are more than a day old.
local function CleanRequests()
    local now = time()
    for full, t in pairs(KeyParseDB.requests) do
        local p = GetPlayer(full)
        if (p and (p.t or 0) >= t) or now - t > STALE_REQUEST then
            KeyParseDB.requests[full] = nil
        end
    end
    for full in pairs(KeyParseDB.fromApplicants) do
        if not KeyParseDB.requests[full] then
            KeyParseDB.fromApplicants[full] = nil
        end
    end
end

-- Blizzard keeps withdrawn, declined and timed-out applicants in the list (greyed out) until you
-- dismiss them, so only these statuses count as someone actually applying.
local ACTIVE_STATUS = { applied = true, invited = true }

local function IsActiveApplicant(info)
    return info and ACTIVE_STATUS[info.applicationStatus] and not info.pendingApplicationStatus
end

-- Everyone actively applying to your listed group, as a set of "Name-Realm".
local function CurrentApplicants()
    local set = {}
    local ok, applicants = pcall(C_LFGList.GetApplicants)
    if not ok or not applicants then
        return set
    end
    for _, id in ipairs(applicants) do
        local info = C_LFGList.GetApplicantInfo(id)
        for m = 1, (IsActiveApplicant(info) and info.numMembers or 0) do
            local ok2, fullName = pcall(C_LFGList.GetApplicantMemberInfo, id, m)
            local full = ok2 and FullName(fullName)
            if full then
                set[full] = true
            end
        end
    end
    return set
end

-- Strong applicants: parse at or above the "strong parse" setting (default 90). They get a star on their
-- row, a tooltip line, and one chat line + taskbar flash after the reload that fetched their parses.
local STRONG_ICON = "|TInterface\\TargetingFrame\\UI-RaidTargetingIcon_1:12|t"

-- Strong = the number on their row (RangeAvg: all runs from target-2 to target) is at or above the setting
-- (default 80), in the role they applied as, from at least minRuns runs. No target key: nobody is strong.
-- Returns that avg plus the key range.
local function StrongParse(full, role)
    if not TargetKey() or not role then
        return nil
    end
    local state, usedRole, avg, runs, lo, hi = RangeAvg(full, role)
    if state == "ok" and usedRole == role and runs >= KeyParseDB.settings.minRuns
        and avg >= (KeyParseDB.settings.strongParse or 80) then
        return avg, lo, hi
    end
end

-- Weak = the row number is below 25 (grey on Warcraft Logs), same role, from at least minRuns runs.
-- Only while the key you're pushing is +19 or lower: anyone applying to 20s is assumed good.
local WEAK_ICON = "|TInterface\\TargetingFrame\\UI-RaidTargetingIcon_8:12|t"
local WEAK_BELOW = 25
local WEAK_MAX_KEY = 19

local function WeakParse(full, role)
    local target = TargetKey()
    if not target or target > WEAK_MAX_KEY or not role then
        return nil
    end
    local state, usedRole, avg, runs = RangeAvg(full, role)
    if state == "ok" and usedRole == role and runs >= KeyParseDB.settings.minRuns and avg < WEAK_BELOW then
        return avg
    end
end

-- Applicants to your listing with a strong parse, best first: { { full, avg, lvl }, ... }
local function StrongApplicants()
    local list = {}
    local ok, ids = pcall(C_LFGList.GetApplicants)
    if not ok or type(ids) ~= "table" then
        return list
    end
    for _, id in ipairs(ids) do
        local info = C_LFGList.GetApplicantInfo(id)
        for m = 1, (IsActiveApplicant(info) and info.numMembers or 0) do
            local ok2, name, _, _, _, _, _, _, _, _, role = pcall(C_LFGList.GetApplicantMemberInfo, id, m)
            local full = ok2 and IsSafe(role) and FullName(name)
            if full then
                local avg = StrongParse(full, LFG_ROLE[role])
                if avg then
                    list[#list + 1] = { full, avg }
                end
            end
        end
    end
    table.sort(list, function(a, b) return a[2] > b[2] end)
    return list
end

local strongAlerted = false -- once per reload
local function AlertStrongApplicants()
    if strongAlerted or not KeyParseDB.settings.alertStrong then
        return
    end
    local list = StrongApplicants()
    if #list == 0 then
        return
    end
    strongAlerted = true
    local parts = {}
    for i = 1, math.min(#list, 3) do
        local e = list[i]
        parts[#parts + 1] = format("|cffffffff%s|r |cff%s%d|r", e[1], ParseColor(e[2]), math.floor(e[2] + 0.5))
    end
    local target = TargetKey()
    Print(format("%s %d strong applicant%s (%d+ avg on +%d to +%d): %s%s", STRONG_ICON, #list, #list == 1 and "" or "s",
        KeyParseDB.settings.strongParse or 80, target - 2, target, table.concat(parts, ", "),
        #list > 3 and ", ..." or ""))
    if FlashClientIcon then
        pcall(FlashClientIcon) -- flashes the WoW taskbar icon when you're tabbed out
    end
end

-- Forget auto-queued lookups for people who are no longer applying (you delisted, relisted, or they left).
local function DropOldApplicantRequests()
    local current = CurrentApplicants()
    for full in pairs(KeyParseDB.fromApplicants) do
        if not current[full] then
            KeyParseDB.requests[full] = nil
            KeyParseDB.fromApplicants[full] = nil
        end
    end
end

local function NewestRequest()
    local newest = 0
    for _, t in pairs(KeyParseDB.requests) do
        if t > newest then
            newest = t
        end
    end
    return newest
end

local function QueueGroup()
    local n = 0
    local prefix, count = "party", GetNumSubgroupMembers()
    if IsInRaid() then
        prefix, count = "raid", GetNumGroupMembers()
    end
    for i = 1, count do
        local guid = UnitGUID(prefix .. i)
        if guid and IsSafe(guid) then
            local ok, _, _, _, _, _, name, realm = pcall(GetPlayerInfoByGUID, guid)
            local okRole, r = pcall(UnitGroupRolesAssigned, prefix .. i)
            local role = okRole and IsSafe(r) and LFG_ROLE[r] or nil
            if ok and Queue(FullName(name, realm), true, nil, role) then
                n = n + 1
            end
        end
    end
    return n
end

-- You and your party members (not raids): { {full=, role=, class=}, ... }
local function PartyMembers()
    local list = {}
    if not IsInGroup() or IsInRaid() then
        return list
    end
    local units = { "player" }
    for i = 1, GetNumSubgroupMembers() do
        units[#units + 1] = "party" .. i
    end
    for _, unit in ipairs(units) do
        local guid = UnitGUID(unit)
        if guid and IsSafe(guid) then
            local ok, _, class, _, _, _, name, realm = pcall(GetPlayerInfoByGUID, guid)
            local full = ok and FullName(name, realm)
            if full then
                local okRole, r = pcall(UnitGroupRolesAssigned, unit)
                list[#list + 1] = { full = full, class = class,
                    role = okRole and IsSafe(r) and LFG_ROLE[r] or nil }
            end
        end
    end
    return list
end

-- The leader of a group listed in the Group Finder, as a one-entry list.
-- Only the leader: Blizzard gives the other members' names WITHOUT their realm, so looking them up
-- would search your own realm and find nothing (that's what happened before 0.7.2).
-- leaderName is "Name-Realm" for other realms and plain "Name" for yours, like applicants.
local function ListingMembers(resultID)
    local ok, info = pcall(C_LFGList.GetSearchResultInfo, resultID)
    if not ok or type(info) ~= "table" or not IsSafe(info.leaderName) then
        return {}, 0
    end
    local leader = { full = FullName(info.leaderName), leader = true }
    for i = 1, (info.numMembers or 0) do
        local ok2, m = pcall(C_LFGList.GetSearchResultPlayerInfo, resultID, i)
        if ok2 and type(m) == "table" and m.isLeader then
            leader.class = m.classFilename
            leader.spec = m.specName
            leader.role = IsSafe(m.assignedRole) and LFG_ROLE[m.assignedRole] or nil
            break
        end
    end
    return { leader }, 0
end

-- Something that still identifies a listed group after a reload and a new search
-- (search result IDs change; the group's GUID doesn't).
local function ListingKey(resultID)
    if type(resultID) ~= "number" then
        return nil
    end
    local ok, info = pcall(C_LFGList.GetSearchResultInfo, resultID)
    if not ok or type(info) ~= "table" then
        return nil
    end
    local key = {}
    if info.partyGUID and IsSafe(info.partyGUID) then
        key.guid = info.partyGUID
    end
    if info.leaderName and IsSafe(info.leaderName) then
        key.leader = FullName(info.leaderName)
    end
    if not key.guid and not key.leader then
        return nil
    end
    return key
end

local function SameListing(resultID, key)
    local k = key and ListingKey(resultID)
    if not k then
        return false
    end
    if key.guid and k.guid then
        return key.guid == k.guid
    end
    return key.leader ~= nil and key.leader == k.leader
end

local function GroupFetchedCount(list)
    local n = 0
    for _, m in ipairs(list) do
        if m.full and GetPlayer(m.full) then
            n = n + 1
        end
    end
    return n
end

-- Queue everyone we have a name for, then reload to fetch (not in combat).
local function FetchMembers(list, resultID)
    local n = 0
    for _, m in ipairs(list) do
        if m.full and Queue(m.full, true, nil, m.role) then
            n = n + 1
        end
    end
    if n == 0 then
        return
    end
    if KeyParseDB.settings.reloadOnLookup and not InCombatLockdown() then
        FetchAndReload(resultID)
    else
        Print(format("Queued %d player%s. /reload to fetch.", n, n == 1 and "" or "s"))
    end
end

-- Applicants to your listed group. onlyNeeded: skip anyone with fresh data.
local function QueueApplicants(onlyNeeded)
    local n = 0
    local ok, applicants = pcall(C_LFGList.GetApplicants)
    if not ok or not applicants then
        return 0
    end
    for _, id in ipairs(applicants) do
        local info = C_LFGList.GetApplicantInfo(id)
        for m = 1, (IsActiveApplicant(info) and info.numMembers or 0) do
            local ok2, fullName, _, _, _, _, _, _, _, _, assignedRole = pcall(C_LFGList.GetApplicantMemberInfo, id, m)
            local full = ok2 and FullName(fullName)
            local role = ok2 and IsSafe(assignedRole) and LFG_ROLE[assignedRole] or nil
            if full and role ~= "heal" and (not onlyNeeded or NeedsLookup(full)) and Queue(full, true, true, role) then
                n = n + 1
            end
        end
    end
    return n
end

-------------------------------------------------------------------- Warcraft Logs points left

-- Vibrant green when the hour's points are all there, fading to grey as they run out.
local function PointsColor(frac)
    frac = math.max(0, math.min(1, frac))
    local r = 0.5 + (0.1 - 0.5) * frac
    local g = 0.5 + (1.0 - 0.5) * frac
    local b = 0.5 + (0.1 - 0.5) * frac
    return format("%02x%02x%02x", math.floor(r * 255 + 0.5), math.floor(g * 255 + 0.5), math.floor(b * 255 + 0.5))
end

-- "WCL points: 688/1000 (resets in 23 min)", as of the last companion update. nil if unknown.
-- What the companion says the player has to fix (empty/nil when all is well).
local problemShown = false
local function CompanionProblem()
    local p = KeyParse_Data and KeyParse_Data.problem
    return type(p) == "string" and p ~= "" and p or nil
end

local function PointsText()
    local p = KeyParse_Data and KeyParse_Data.points
    if type(p) ~= "table" or type(p.limit) ~= "number" or p.limit <= 0 then
        return nil
    end
    local now = time()
    if (KeyParse_Data.paused or 0) > now then
        -- Warcraft Logs' "no database points remaining": a load limit on their side, not your points;
        -- seen clearing within minutes. The companion re-checks every 2 min.
        return "|cff808080WCL busy (database limit), retrying every 2 min|r"
    end
    local reset = p.reset or 0
    if reset <= now then -- a new hour started since the companion last asked
        return format("WCL points: |cff%s%d|r/%d", PointsColor(1), p.limit, p.limit)
    end
    local left = math.max(0, p.limit - (p.spent or 0))
    return format("WCL points: |cff%s%d|r/%d (resets in %d min)", PointsColor(left / p.limit), left, p.limit,
        math.ceil((reset - now) / 60))
end

-------------------------------------------------------------------- loading data slots

local slotIndex = 0
local dataLoaded = false
local RefreshSearchArrowsHook -- set in the Group Finder section
local RefreshApplicantLabels -- defined in the Group Finder section
local PlayerSearch -- { Open, Refresh, Reopen }, defined in "player search"

local function LoadNextSlot()
    slotIndex = slotIndex + 1
    if slotIndex > #SLOT_DELAYS then
        return
    end
    KeyParse_Slot = nil
    local ok, loaded, reason = pcall(LoadAddOn, ADDON_NAME .. "_Data" .. slotIndex)
    local slot = KeyParse_Slot
    KeyParse_Slot = nil
    if not ok or not loaded or type(slot) ~= "table" then
        Print(format("Couldn't load %s_Data%d (%s). Make sure all KeyParse addons are enabled in the AddOns list.",
            ADDON_NAME, slotIndex, tostring(reason or loaded)))
        if slotIndex < #SLOT_DELAYS then
            return LoadNextSlot() -- try the next one straight away
        end
        dataLoaded = true -- keep working (auto-queue, labels) even without data
        if RefreshApplicantLabels then
            RefreshApplicantLabels()
        end
        if PlayerSearch then
            PlayerSearch.Refresh(slotIndex < #SLOT_DELAYS)
        end
        return
    end
    dataLoaded = true
    if slot.generated and slot.generated >= (KeyParse_Data.generated or 0) then
        KeyParse_Data = slot
        KeyParse_Data.players = KeyParse_Data.players or {}
    end

    local hadPending = PendingCount() > 0
    local newest = NewestRequest()
    CleanRequests()
    if RefreshApplicantLabels then
        RefreshApplicantLabels()
    end
    if RefreshSearchArrowsHook then
        RefreshSearchArrowsHook()
    end
    if UpdateFetchButton then
        UpdateFetchButton()
    end
    if KeyParseDB.settings.autoQueueApplicants then
        QueueApplicants(true) -- people who applied while we were loading
    end

    -- something the player has to fix in the companion (e.g. a rejected API key): say it once per login
    if CompanionProblem() and not problemShown then
        problemShown = true
        Print("|cffff5555companion: " .. CompanionProblem() .. "|r")
    end

    local finished = slot.done and (slot.generated or 0) >= newest
    if PlayerSearch then -- the search window: new numbers, and stop saying "Fetching" after the last slot
        PlayerSearch.Refresh(hadPending and not finished and PendingCount() > 0 and (slot.paused or 0) <= time()
            and slotIndex < #SLOT_DELAYS)
    end
    if not hadPending then
        return
    end
    if (slot.paused or 0) > time() and PendingCount() > 0 then
        Print("Warcraft Logs is busy (its database limit, not your points). The companion retries every 2 min; /reload in a few minutes.")
    elseif finished or PendingCount() == 0 then
        local pts = PointsText()
        if not KeyParseDB.settings.quietChat then -- info only: points are also in /kp status and the Group Finder
            Print("Parses updated." .. (pts and (" " .. pts) or ""))
        end
        AlertStrongApplicants()
    elseif slotIndex < #SLOT_DELAYS then
        C_Timer.After(SLOT_DELAYS[slotIndex + 1] - SLOT_DELAYS[slotIndex], LoadNextSlot)
    elseif (slot.generated or 0) < newest then
        Print("The companion app didn't respond. Start it (Start KeyParse Companion), then /reload.")
    else
        Print(format("%d lookup%s still running in the companion. /reload again in a moment.",
            PendingCount(), PendingCount() == 1 and "" or "s"))
    end
end

-------------------------------------------------------------------- right-click menus

local UNIT_MENUS = {
    "SELF", "PLAYER", "PARTY", "RAID_PLAYER", "RAID", "TARGET", "FOCUS", "FRIEND",
    "GUILD", "CHAT_ROSTER", "COMMUNITIES_GUILD_MEMBER", "COMMUNITIES_WOW_MEMBER", "ENEMY_PLAYER",
}

local function NameFromMenu(owner, contextData)
    if contextData then
        if contextData.unit and IsSafe(contextData.unit) then
            local guid = UnitGUID(contextData.unit)
            if guid and IsSafe(guid) then
                local ok, _, _, _, _, _, name, realm = pcall(GetPlayerInfoByGUID, guid)
                if ok then
                    local full = FullName(name, realm)
                    if full then
                        return full
                    end
                end
            end
        end
        if contextData.name then
            return FullName(contextData.name, contextData.server)
        end
    end
    if owner then
        -- Group Finder: an applicant in your group's list
        if owner.memberIdx and owner.GetParent then
            local parent = owner:GetParent()
            if parent and parent.applicantID then
                local ok, fullName = pcall(C_LFGList.GetApplicantMemberInfo, parent.applicantID, owner.memberIdx)
                if ok then
                    return FullName(fullName)
                end
            end
        end
        -- Group Finder: a listed group's leader
        if owner.resultID then
            local ok, info = pcall(C_LFGList.GetSearchResultInfo, owner.resultID)
            if ok and info and IsSafe(info.leaderName) then
                return FullName(info.leaderName)
            end
        end
    end
end

-- "Name   72 +15 (6)" for each member; hovering a member opens their keys, then each key's dungeons.
local function MemberName(m)
    local short = m.full and m.full:match("^[^%-]+") or "?"
    local color = m.class and RAID_CLASS_COLORS and RAID_CLASS_COLORS[m.class]
    if color and color.colorStr then
        short = "|c" .. color.colorStr .. short .. "|r"
    end
    return short .. (m.leader and " |cffffd100(leader)|r" or "")
end

local function FillMembersMenu(desc, list)
    for _, m in ipairs(list) do
        if m.full then
            local state = Summarize(m.full, m.role)
            local label = LabelText(m.full, m.role)
            if label == "" then
                label = m.role == "heal" and "|cff888888healer, not looked up|r" or "|cff888888not fetched|r"
            end
            local button = desc:CreateButton(MemberName(m) .. "   " .. label)
            if state == "ok" or state == "nokey" then
                FillKeysMenu(button, m.full, m.role)
            end
        else
            desc:CreateButton(format("|cff888888%s (name hidden by Blizzard)|r",
                m.spec or (m.role and ROLE_LABEL[m.role]) or "Member"), function() end)
        end
    end
end

-- Your party (right-click your own character): "Show group parses". Before the lookup it costs
-- one lookup per non-healer, so it's flagged in red. Afterwards it's a submenu: members > keys > dungeons.
local function AddPartyEntries(desc, list)
    local dps = 0
    for _, m in ipairs(list) do
        if m.full and m.role ~= "heal" then
            dps = dps + 1
        end
    end
    if dps == 0 then
        return
    end
    local fetched = GroupFetchedCount(list)
    if fetched > 0 then
        local sub = desc:CreateButton(format("Show group parses (%d/%d)", fetched, dps))
        FillMembersMenu(sub, list)
        sub:CreateDivider()
        sub:CreateButton("Refresh group parses", function() FetchMembers(list) end)
    else
        desc:CreateButton("Show group parses", function() FetchMembers(list) end)
    end
end

-- A group listed in the Group Finder: only its leader can be looked up (see ListingMembers).
local function AddLeaderEntries(desc, leader, resultID)
    local state = Summarize(leader.full, leader.role)
    if leader.role == "heal" then
        desc:CreateButton("|cff888888Leader is a healer (not looked up)|r", function() end)
    elseif state == "ok" or state == "nokey" then
        local sub = desc:CreateButton("Leader parse   " .. LabelText(leader.full, leader.role))
        FillKeysMenu(sub, leader.full, leader.role)
        sub:CreateDivider()
        sub:CreateButton("Refresh leader parse", function() FetchMembers({ leader }, resultID) end)
    elseif state == "queued" then
        desc:CreateButton("|cff888888Leader parse queued|r (fetch now)", function()
            if not InCombatLockdown() then
                FetchAndReload(resultID)
            end
        end)
    elseif state == "missing" then
        desc:CreateButton("|cff888888Leader: no public M+ logs|r (check again)", function() FetchMembers({ leader }, resultID) end)
    else
        desc:CreateButton("Show leader parse", function() FetchMembers({ leader }, resultID) end)
    end
end

-- The ▼ on a Group Finder listing.
local function ShowListingMenu(owner, resultID)
    local list = ListingMembers(resultID)
    if MenuUtil and MenuUtil.CreateContextMenu then
        MenuUtil.CreateContextMenu(owner, function(_, root)
            root:CreateTitle("Leader parse")
            FillMembersMenu(root, list)
        end)
    end
end

local function OnMenu(owner, rootDescription, contextData)
    -- A group listed in the Group Finder (one you might join): its leader's parse.
    if owner and owner.resultID and not owner.memberIdx then
        local list = ListingMembers(owner.resultID)
        if list[1] and list[1].full then
            rootDescription:CreateDivider()
            rootDescription:CreateTitle("KeyParse")
            AddLeaderEntries(rootDescription, list[1], owner.resultID)
        end
        return
    end
    local full = NameFromMenu(owner, contextData)
    if not full then
        return
    end
    rootDescription:CreateDivider()
    rootDescription:CreateTitle("KeyParse")
    local function Fetch()
        -- Queue them, then reload right away so the companion picks it up (not in combat).
        if KeyParseDB.settings.reloadOnLookup and not InCombatLockdown() then
            Queue(full, true)
            FetchAndReload()
        else
            Queue(full)
        end
    end
    local party = PartyMembers()
    local inParty
    for _, m in ipairs(party) do
        if m.full == full then
            inParty = m
            break
        end
    end
    local state = Summarize(full)
    if inParty and inParty.role == "heal" and state ~= "ok" and state ~= "nokey" then
        rootDescription:CreateButton("|cff888888Healer (not looked up)|r", function() end)
    elseif state == "ok" or state == "nokey" then
        -- "54 +14 (4)" with every key level (and each key's dungeons) in the submenu on the right
        local summary = rootDescription:CreateButton(LabelText(full))
        FillKeysMenu(summary, full)
        summary:CreateDivider()
        summary:CreateButton("Refresh parses", Fetch)
    elseif state == "queued" then
        rootDescription:CreateButton("|cff888888M+ parses queued|r (fetch now)", function()
            if not InCombatLockdown() then
                FetchAndReload()
            end
        end)
    elseif state == "missing" then
        rootDescription:CreateButton("|cff888888No public M+ logs|r (check again)", Fetch)
    elseif state == "error" then
        rootDescription:CreateButton("|cffff5555Lookup failed|r (try again)", Fetch)
    else
        rootDescription:CreateButton("Get M+ parses", Fetch)
    end

    -- Right-clicking your own character in a party: the whole party's parses.
    if #party > 1 and party[1].full == full then
        AddPartyEntries(rootDescription, party)
    end
end

-- Like Raider.IO, wait until Blizzard opens its first menu before modifying menus,
-- so the menu system is fully set up and we don't taint it.
local menusReady = false
local function InitMenus()
    if menusReady or not (Menu and Menu.ModifyMenu) then
        return
    end
    menusReady = true
    for _, which in ipairs(UNIT_MENUS) do
        Menu.ModifyMenu("MENU_UNIT_" .. which, OnMenu)
    end
    Menu.ModifyMenu("MENU_LFG_FRAME_MEMBER_APPLY", OnMenu)
    Menu.ModifyMenu("MENU_LFG_FRAME_SEARCH_ENTRY", OnMenu)
end

-------------------------------------------------------------------- Group Finder

local hookedMembers = {}
local memberLabels = {}

local function ApplicantMember(member)
    local parent = member:GetParent()
    if not parent or not parent.applicantID or not member.memberIdx then
        return nil
    end
    local ok, fullName, class, _, _, _, _, _, _, _, assignedRole, _, _, _, _, _, specID =
        pcall(C_LFGList.GetApplicantMemberInfo, parent.applicantID, member.memberIdx)
    if not ok or not IsSafe(assignedRole) then
        return nil
    end
    local specName
    if IsSafe(specID) and type(specID) == "number" and specID > 0 and GetSpecializationInfoByID then
        local ok2, _, name = pcall(GetSpecializationInfoByID, specID)
        specName = ok2 and IsSafe(name) and name or nil
    end
    return FullName(fullName), LFG_ROLE[assignedRole], specName, IsSafe(class) and class or nil
end

-- Group checklist: Bloodlust and battle res, from the classes in your group (no Warcraft Logs points).
-- Shown next to your listing's title; applicants who'd fill a missing one get +BL / +BR on their row.
local LUST_CLASSES = { SHAMAN = true, MAGE = true, HUNTER = true, EVOKER = true }
local BREZ_CLASSES = { DRUID = true, DEATHKNIGHT = true, WARLOCK = true, PALADIN = true }
local LUST_NAMES = "Shaman, Mage, Hunter (pet), Evoker"
local BREZ_NAMES = "Druid, Death Knight, Warlock, Paladin"

local function UnitClassFile(unit)
    if not UnitClass then
        return nil
    end
    local ok, _, file = pcall(UnitClass, unit)
    return ok and IsSafe(file) and type(file) == "string" and file or nil
end

-- What you + party1..4 already bring: { lust = bool, brez = bool }.
local function GroupHas()
    local has = { lust = false, brez = false }
    if TEST then
        for _, class in ipairs(TEST.classes) do
            has.lust = has.lust or LUST_CLASSES[class] or false
            has.brez = has.brez or BREZ_CLASSES[class] or false
        end
        return has
    end
    local units = { "player" }
    if not (IsInRaid and IsInRaid()) then
        local n = GetNumSubgroupMembers and GetNumSubgroupMembers() or 0
        for i = 1, (IsSafe(n) and n or 0) do
            units[#units + 1] = "party" .. i
        end
    end
    for _, unit in ipairs(units) do
        local class = UnitClassFile(unit)
        if class then
            has.lust = has.lust or LUST_CLASSES[class] or false
            has.brez = has.brez or BREZ_CLASSES[class] or false
        end
    end
    return has
end

-- "+BL" / "+BR" for an applicant whose class fills something your group is missing.
local function FillsTag(class, has)
    if not class or not has or not KeyParseDB.settings.showChecklist then
        return ""
    end
    if not has.lust and LUST_CLASSES[class] then
        return "|cff33ff99+BL|r"
    elseif not has.brez and BREZ_CLASSES[class] then
        return "|cff33ff99+BR|r"
    end
    return ""
end

local function ChecklistText(has)
    local function item(name, ok)
        return format("|cff%s%s|r |TInterface\\RaidFrame\\ReadyCheck-%s:12|t", ok and "33ff99" or "ff5555", name,
            ok and "Ready" or "NotReady")
    end
    return item("Lust", has.lust) .. "  " .. item("Brez", has.brez)
end

local checklistFrame
local function UpdateGroupChecklist(has)
    local viewer = LFGListFrame and LFGListFrame.ApplicationViewer
    if not viewer or not viewer.EntryName or not CreateFrame then
        return
    end
    if not checklistFrame then
        checklistFrame = CreateFrame("Frame", "KeyParseGroupChecklist", viewer)
        checklistFrame:SetSize(110, 16)
        local text = checklistFrame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        text:SetJustifyH("RIGHT")
        text:SetPoint("RIGHT", checklistFrame, "RIGHT", 0, 0)
        checklistFrame.text = text
        checklistFrame:SetScript("OnEnter", function(self)
            GameTooltip:SetOwner(self, "ANCHOR_BOTTOM")
            GameTooltip:SetText("KeyParse: group checklist")
            GameTooltip:AddLine("Bloodlust: " .. LUST_NAMES, 1, 1, 1)
            GameTooltip:AddLine("Battle res: " .. BREZ_NAMES, 1, 1, 1)
            GameTooltip:AddLine("Applicants who'd fill a gap show +BL / +BR.", 0.6, 0.6, 0.6)
            GameTooltip:Show()
        end)
        checklistFrame:SetScript("OnLeave", GameTooltip_Hide)
    end
    -- placed in the top-right stack by UpdateViewerPoints
    checklistFrame.text:SetText(ChecklistText(has))
    checklistFrame:SetSize((checklistFrame.text:GetStringWidth() or 100) + 2, 16)
    checklistFrame:SetShown(KeyParseDB.settings.showChecklist and not (IsInRaid and IsInRaid()))
end

-- Short text shown next to an applicant's name.
local ROLE_SHORT = { dps = "dps", heal = "heal", tank = "tank" }

-- appliedSpec: applicants only. An orange ! means: new to your key level, or applied on a spec without logs
-- (details in the tooltip). With a dungeon listed: "<that dungeon>/<overall> +15".
LabelText = function(full, role, appliedSpec)
    local state, usedRole, lvl, n, avg, low = Summarize(full, role)
    if state == "ok" then
        local mark = low and "|cffff5555*|r" or ""
        local p = GetPlayer(full)
        if Experience(p, usedRole, TargetKey()) or SpecMismatch(p, usedRole, appliedSpec) then
            mark = mark .. "|cffff9933!|r"
        end
        if role and usedRole ~= role then
            -- e.g. applied as tank but only has DPS logs: say whose parse this is
            return format("|cff%s%d|r |cffaaaaaa+%d %s|r%s", ParseColor(avg), math.floor(avg + 0.5), lvl,
                ROLE_SHORT[usedRole] or usedRole, mark)
        end
        local encID = ListingDungeon()
        local dd = encID and p.roles[usedRole][lvl].d and p.roles[usedRole][lvl].d[encID]
        if dd then
            return format("|cff%s%d|r|cffaaaaaa/|r|cff%s%d|r |cffaaaaaa+%d|r%s", ParseColor(dd[2]),
                math.floor(dd[2] + 0.5), ParseColor(avg), math.floor(avg + 0.5), lvl, mark)
        end
        return format("|cff%s%d|r |cffaaaaaa+%d (%d)|r%s", ParseColor(avg), math.floor(avg + 0.5), lvl, n, mark)
    elseif state == "queued" then
        return "|cff888888...|r"
    elseif state == "nokey" then
        return format("|cff888888none <+%d|r", TargetKey() or 0) -- has logs, just not below your key
    elseif state == "missing" then
        return "|cff888888no logs|r"
    elseif state == "error" then
        return "|cffff5555failed|r"
    end
    return ""
end

-- Applicant rows: just one number (RangeAvg: every run from 2 keys below your key up to it), coloured,
-- plus red * (fewer than min runs) and orange ! (new to your key / spec without logs). A grey "-" when they
-- have logs but no runs in that range. The tooltip has the details.
local function ApplicantLabel(full, role, appliedSpec)
    local state, usedRole, avg, runs = RangeAvg(full, role)
    if state == "ok" or state == "norange" then
        local p = GetPlayer(full)
        local mark = (state == "ok" and runs < KeyParseDB.settings.minRuns) and "|cffff5555*|r" or ""
        -- ! also when the number is from another role (applied tank, only DPS logs): the tooltip says which
        if Experience(p, usedRole, TargetKey()) or SpecMismatch(p, usedRole, appliedSpec) or (role and usedRole ~= role) then
            mark = mark .. "|cffff9933!|r"
        end
        if state == "norange" then
            return "|cff888888-|r" .. mark
        end
        return format("|cff%s%d|r%s", ParseColor(avg), math.floor(avg + 0.5), mark)
    end
    return LabelText(full, role, appliedSpec) -- "...", "no logs", "failed"
end

-- Layout of Blizzard's applicant rows (LFGListApplicantMemberTemplate), used to make room for our column.
local COLUMN_WIDTH = 90          -- extra width added for the "Parse" column
local NAME_RIGHT = 95            -- the Name text ends here
local BLIZZ = { memberWidth = 250, roleX = 104, ilvlX = 177, ratingX = 218, applicantWidth = 309 }

local function IsWide()
    return KeyParseDB.settings.wideGroupFinder
end

-- All of a player's averages as dropdown lines, best role first.
-- All of a player's averages: one section per role (preferredRole first), one line per key level
-- (highest first), and for each key every dungeon in Warcraft Logs' order.
local function KeyBreakdown(full, preferredRole)
    local p = GetPlayer(full)
    if not p or not p.roles or not next(p.roles) then
        return nil
    end
    local roles = {}
    for r in pairs(p.roles) do
        roles[#roles + 1] = r
    end
    table.sort(roles, function(a, b)
        if a == preferredRole then return true end
        if b == preferredRole then return false end
        return RunCount(p.roles[a]) > RunCount(p.roles[b])
    end)
    local minRuns = KeyParseDB.settings.minRuns

    local function DungeonLines(entry)
        if not entry.d then
            return { "|cff888888No dungeon detail yet (Refresh parses to get it)|r" }
        end
        local out = {}
        for _, dungeon in ipairs(Dungeons()) do
            local id, name = dungeon[1], dungeon[2]
            local d = entry.d[id]
            if d then
                out[#out + 1] = format("%s   |cff%s%.1f|r  |cffaaaaaa(%d run%s)|r",
                    name, ParseColor(d[2]), d[2], d[1], d[1] == 1 and "" or "s")
            else
                out[#out + 1] = format("%s   |cff888888no parses|r", name)
            end
        end
        return out
    end

    local sections = {}
    for _, r in ipairs(roles) do
        local keys = p.roles[r]
        local shown = PickKey(keys, TargetKey())
        local section = {
            title = format("%s%s", ROLE_LABEL[r] or r, (preferredRole and r == preferredRole) and " (applied as)" or ""),
            keys = {},
        }
        local levels = {}
        for k in pairs(keys) do
            levels[#levels + 1] = k
        end
        table.sort(levels, function(a, b) return a > b end)
        for _, k in ipairs(levels) do
            local n, avg = keys[k][1], keys[k][2]
            local dim = n < minRuns and "|cff888888" or "|cffffffff"
            section.keys[#section.keys + 1] = {
                text = format("%s+%d|r   |cff%s%.1f|r   %s%d run%s|r%s", dim, k, ParseColor(avg), avg, dim, n,
                    n == 1 and "" or "s", k == shown and "  |cffffd100<|r" or ""),
                dungeons = DungeonLines(keys[k]),
            }
        end
        sections[#sections + 1] = section
    end
    return p, sections
end

-- Fill a menu (or submenu) with the breakdown: key levels that each open their dungeons.
FillKeysMenu = function(desc, full, preferredRole)
    local p, sections = KeyBreakdown(full, preferredRole)
    if not p then
        return false
    end
    desc:CreateTitle(format("%s%s", full, p.spec and (" - " .. p.spec) or ""))
    for _, section in ipairs(sections) do
        desc:CreateDivider()
        desc:CreateTitle(section.title)
        for _, key in ipairs(section.keys) do
            local keyButton = desc:CreateButton(key.text)
            for _, text in ipairs(key.dungeons) do
                keyButton:CreateButton(text, function() end)
            end
        end
    end
    return true
end

-- The ▼ next to an applicant.
local function ShowAllKeys(owner, full, role)
    if MenuUtil and MenuUtil.CreateContextMenu then
        MenuUtil.CreateContextMenu(owner, function(_, root)
            FillKeysMenu(root, full, role)
        end)
        return
    end
    -- fallback: show it as a tooltip
    local p, sections = KeyBreakdown(full, role)
    if not p then
        return
    end
    GameTooltip:SetOwner(owner, "ANCHOR_RIGHT")
    GameTooltip:SetText(full)
    for _, section in ipairs(sections) do
        GameTooltip:AddLine(section.title, 1, 0.82, 0)
        for _, key in ipairs(section.keys) do
            GameTooltip:AddLine(key.text)
            for _, text in ipairs(key.dungeons) do
                GameTooltip:AddLine("      " .. text, 0.8, 0.8, 0.8)
            end
        end
    end
    GameTooltip:Show()
end

local memberArrows = {}

-- Everything in an applicant's KeyParse column: star/skull, +BL/+BR, the number, * and !. (Also the test queue.)
local function RowText(full, role, spec, class, has)
    if not full then
        return ""
    end
    local text = ApplicantLabel(full, role, spec)
    if role == "heal" and text == "" then
        text = "|cff888888healer|r"
    end
    local tag = FillsTag(class, has)
    if tag ~= "" then
        text = text ~= "" and (tag .. " " .. text) or tag
    end
    if KeyParseDB.settings.strongIcon and StrongParse(full, role) then
        text = STRONG_ICON .. text
    elseif KeyParseDB.settings.weakIcon and WeakParse(full, role) then
        text = WEAK_ICON .. text
    end
    return text
end

-- Shift Blizzard's role icons / item level / rating right to make room for our column (or put them back).
local function LayoutMember(member)
    local extra = IsWide() and COLUMN_WIDTH or 0
    if member.lastKeyParseExtra == extra then
        return
    end
    member.lastKeyParseExtra = extra
    member:SetWidth(BLIZZ.memberWidth + extra)
    if member.RoleIcon1 then
        member.RoleIcon1:ClearAllPoints()
        member.RoleIcon1:SetPoint("LEFT", member, "LEFT", BLIZZ.roleX + extra, 0)
    end
    if member.ItemLevel then
        member.ItemLevel:ClearAllPoints()
        member.ItemLevel:SetPoint("CENTER", member, "LEFT", BLIZZ.ilvlX + extra, 0)
    end
    if member.Rating then
        member.Rating:ClearAllPoints()
        member.Rating:SetPoint("CENTER", member, "LEFT", BLIZZ.ratingX + extra, 0)
    end
end

local function UpdateMemberLabel(member, has)
    LayoutMember(member)
    local label = memberLabels[member]
    local arrow = memberArrows[member]
    if not label then
        label = member:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        label:SetJustifyH("LEFT")
        label:SetWordWrap(false)
        memberLabels[member] = label

        arrow = CreateFrame("Button", nil, member)
        arrow:SetSize(16, 16)
        arrow:SetNormalTexture("Interface\\Buttons\\UI-ScrollBar-ScrollDownButton-Up")
        arrow:SetPushedTexture("Interface\\Buttons\\UI-ScrollBar-ScrollDownButton-Down")
        arrow:SetHighlightTexture("Interface\\Buttons\\UI-ScrollBar-ScrollDownButton-Highlight", "ADD")
        arrow:SetScript("OnClick", function(self)
            if self.full then
                ShowAllKeys(self, self.full, self.role)
            end
        end)
        arrow:SetScript("OnEnter", function(self)
            GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
            GameTooltip:SetText("KeyParse: every key level")
            GameTooltip:Show()
        end)
        arrow:SetScript("OnLeave", GameTooltip_Hide)
        memberArrows[member] = arrow
    end

    label:ClearAllPoints()
    arrow:ClearAllPoints()
    if IsWide() then
        label:SetPoint("LEFT", member, "LEFT", NAME_RIGHT + 4, 0)
        label:SetWidth(COLUMN_WIDTH - 22)
        arrow:SetPoint("LEFT", member, "LEFT", NAME_RIGHT + COLUMN_WIDTH - 17, 0)
    else -- narrow mode: squeeze in after the name like before
        local w = member.Name and math.min(member.Name:GetStringWidth() or 0, member.Name:GetWidth() or 0) or 0
        label:SetPoint("LEFT", member.Name or member, "LEFT", w + 4, 0)
        label:SetWidth(0)
        arrow:SetPoint("LEFT", label, "RIGHT", 1, 0)
    end

    local full, role, spec, class = ApplicantMember(member)
    label:SetText(RowText(full, role, spec, class, has))
    local p = full and GetPlayer(full)
    arrow.full, arrow.role = full, role
    arrow:SetShown(p and p.roles and next(p.roles) ~= nil or false)
end

-- KeyParse's lines under an applicant's tooltip (Blizzard's applicant tooltip, or the test queue's).
local function AddApplicantLines(GameTooltip, full, role, spec, class)
        local tag = FillsTag(class, GroupHas())
        if tag ~= "" then
            GameTooltip:AddLine(tag:find("BL") and "KeyParse: brings Bloodlust (your group has none)"
                or "KeyParse: brings a battle res (your group has none)", 0.2, 1, 0.6)
        end
        -- what the single number on the row means
        local state, usedRole, avg, runs, lo, hi = RangeAvg(full, role)
        local range = lo and (lo == hi and format("+%d", lo) or format("+%d to +%d", lo, hi)) or ""
        if state == "ok" then
            GameTooltip:AddLine(format("KeyParse row: |cff%s%d|r = avg of %d %s run%s on %s", ParseColor(avg),
                math.floor(avg + 0.5), runs, ROLE_LABEL[usedRole] or usedRole, runs == 1 and "" or "s", range), 1, 1, 1)
        elseif state == "norange" then
            GameTooltip:AddLine(format("KeyParse row: - = no logged runs on %s", range), 0.6, 0.6, 0.6)
        end
        local strongAvg = StrongParse(full, role)
        if KeyParseDB.settings.strongIcon and strongAvg then
            GameTooltip:AddLine(format("%s KeyParse: strong applicant (%d+ avg)", STRONG_ICON,
                KeyParseDB.settings.strongParse or 80), 1, 0.82, 0)
        elseif KeyParseDB.settings.weakIcon and WeakParse(full, role) then
            GameTooltip:AddLine(format("%s KeyParse: weak applicant (avg below %d on keys up to +%d)", WEAK_ICON,
                WEAK_BELOW, WEAK_MAX_KEY), 1, 0.4, 0.4)
        end
        AddLines(GameTooltip, full, role, spec)
end

local function OnApplicantMemberEnter(member)
    local full, role, spec, class = ApplicantMember(member)
    if full and GameTooltip:IsShown() then
        AddApplicantLines(GameTooltip, full, role, spec, class)
        GameTooltip:Show()
    end
end

local function ApplicantFrames()
    local viewer = LFGListFrame and LFGListFrame.ApplicationViewer
    local scrollBox = viewer and viewer.ScrollBox
    return scrollBox and scrollBox.GetFrames and scrollBox:GetFrames() or {}
end

-- Your own listing: a right-aligned stack in the top-right corner of the dungeon picture, so it never
-- runs into the title on the left. Lines, top to bottom (empty ones collapse):
--   1. group checklist (Lust / Brez)    2. KeyParse notice (lookups waiting)    3. WCL points left
local viewerNotice, viewerPoints
local function UpdateViewerPoints()
    local viewer = LFGListFrame and LFGListFrame.ApplicationViewer
    local bg = viewer and viewer.InfoBackground
    if not bg or not viewer.CreateFontString then
        return
    end
    if not viewerPoints then
        viewerNotice = viewer:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        viewerNotice:SetJustifyH("RIGHT")
        viewerPoints = viewer:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        viewerPoints:SetJustifyH("RIGHT")
    end
    local pending = PendingCount()
    local notice = pending > 0 and format("KeyParse: %d lookup%s waiting (reload to fetch)", pending,
        pending == 1 and "" or "s") or nil
    if CompanionProblem() then -- a problem beats the waiting count: nothing gets fetched until it's fixed
        notice = "|cffff5555KeyParse companion: API key rejected, run its setup|r"
    end
    viewerNotice:SetText(notice or "")
    viewerNotice:SetShown(notice ~= nil)
    local pts = PointsText()
    viewerPoints:SetText(pts or "")
    viewerPoints:SetShown(pts ~= nil)

    -- the picture is widened in wide mode (see ExtendInfoBackground), so its right edge is the corner
    local above
    for _, line in ipairs({ checklistFrame or false, viewerNotice, viewerPoints }) do
        if line and line:IsShown() then
            line:ClearAllPoints()
            if above then
                line:SetPoint("TOPRIGHT", above, "BOTTOMRIGHT", 0, -3)
            else
                line:SetPoint("TOPRIGHT", bg, "TOPRIGHT", -12, -12)
            end
            above = line
        end
    end
end

-- Raider.IO's round "copy group" button sits just left of the bottom centre of the Group Finder,
-- which lands on Blizzard's Delist button on your own listing. While the listing shows, put it just
-- right of Delist; put it back where Raider.IO had it afterwards. (Not a Blizzard frame: no taint.)
local function PlaceRaiderIOButton(onListing)
    local b = _G.RaiderIO_ExportButton
    local viewer = LFGListFrame and LFGListFrame.ApplicationViewer
    if type(b) ~= "table" or not b.ClearAllPoints or not viewer or not viewer.RemoveEntryButton then
        return
    end
    b:ClearAllPoints()
    if onListing then
        b:SetPoint("LEFT", viewer.RemoveEntryButton, "RIGHT", 8, 1)
    else
        b:SetPoint("BOTTOMRIGHT", LFGListFrame, "BOTTOM", -12, 7) -- Raider.IO's own spot
    end
end

RefreshApplicantLabels = function()
    local has = GroupHas()
    UpdateGroupChecklist(has)
    UpdateViewerPoints() -- after the checklist: it stacks the top-right lines
    for _, frame in ipairs(ApplicantFrames()) do
        if frame.SetWidth then
            frame:SetWidth(BLIZZ.applicantWidth + (IsWide() and COLUMN_WIDTH or 0))
        end
        for _, member in ipairs(frame.Members or {}) do
            if not hookedMembers[member] then
                hookedMembers[member] = true
                member:HookScript("OnEnter", OnApplicantMemberEnter)
            end
            UpdateMemberLabel(member, has)
        end
    end
end

-------------------------------------------------------------------- back to your search after a reload
-- A reload throws away Blizzard's search list. Addons can't run a Group Finder search themselves
-- (Blizzard blocks it) and can't type into its search box, so after the reload we:
--   1. reopen Premade Groups,
--   2. show one "Back to your <category> search" button. It's a secure button: your click makes
--      Blizzard's own Category + Find Group buttons run, exactly as if you'd clicked them,
--   3. remind you what was in the search box (e.g. 18-18) until you've searched it again,
--   4. highlight the group you parsed in the list (and say where it is if it's scrolled off).

local RETURN_WINDOW = 120      -- seconds: only act on a reload KeyParse started just now
local RETURN_FOR = 15 * 60     -- keep the button/highlight around this long after the reload
local returnState              -- what was open before the reload (from KeyParseDB.returnTo)

local function ReturnActive()
    return returnState ~= nil and time() < (returnState.untilTime or 0)
end

-- Remember what the Group Finder was showing, and which listing the lookup came from.
local function SaveReturnState(focusResultID)
    local state = { at = time() }
    local panel = LFGListFrame and LFGListFrame.SearchPanel
    if panel and panel.IsVisible and panel:IsVisible() and type(panel.categoryID) == "number" then
        state.categoryID = panel.categoryID
        state.filters = type(panel.filters) == "number" and panel.filters or 0
        local box = panel.SearchBox
        local ok, text = pcall(function() return box and box:GetText() end)
        if ok and IsSafe(text) and type(text) == "string" and text:match("%S") then
            state.text = text:match("^%s*(.-)%s*$")
        end
        if type(focusResultID) ~= "number" and type(panel.selectedResult) == "number" then
            focusResultID = panel.selectedResult -- the group you had clicked on
        end
    end
    state.focus = ListingKey(focusResultID)
    KeyParseDB.returnTo = (state.categoryID or state.focus) and state or nil
end

-- Reload to fetch, and remember to reopen the Group Finder afterwards.
FetchAndReload = function(focusResultID)
    if KeyParseDB.settings.reopenGroupFinder and PVEFrame and PVEFrame:IsShown() then
        KeyParseDB.reopenAt = time()
        SaveReturnState(focusResultID)
    end
    ReloadUI()
end

local returnButton, proxyCategory, proxyFind

local function CategoryButtonFor(categoryID, filters)
    local sel = LFGListFrame and LFGListFrame.CategorySelection
    local fallback
    for _, b in ipairs(sel and sel.CategoryButtons or {}) do
        if b:IsShown() and b.categoryID == categoryID then
            if b.filters == filters then
                return b
            end
            fallback = fallback or b
        end
    end
    return fallback
end

local function CategoryName(categoryID)
    local ok, info = pcall(C_LFGList.GetLfgCategoryInfo, categoryID)
    return ok and type(info) == "table" and IsSafe(info.name) and info.name or "group"
end

-- Shows/updates the secure button. Returns true if it's showing.
local function UpdateReturnButton()
    if not returnButton or InCombatLockdown() then
        return returnButton ~= nil and returnButton:IsShown()
    end
    local sel = LFGListFrame and LFGListFrame.CategorySelection
    local listed = select(2, pcall(C_LFGList.HasActiveEntryInfo))
    local target = ReturnActive() and returnState.categoryID and not returnState.used and listed ~= true
        and sel and sel:IsVisible() and CategoryButtonFor(returnState.categoryID, returnState.filters)
    if target then
        proxyCategory:SetAttribute("clickbutton", target)
        proxyFind:SetAttribute("clickbutton", sel.FindGroupButton)
        returnButton:SetText(format("KeyParse: back to your %s search", CategoryName(returnState.categoryID)))
        returnButton:Show()
        return true
    end
    returnButton:Hide()
    return false
end

local function CreateReturnButton()
    local sel = LFGListFrame and LFGListFrame.CategorySelection
    if returnButton or not sel or not sel.FindGroupButton or InCombatLockdown() then
        return
    end
    -- Hidden helpers that click Blizzard's own buttons. Named, because a macro's /click needs a name.
    -- useOnKeyDown = false: act on the (default) button-up that /click sends.
    proxyCategory = CreateFrame("Button", "KeyParseReturnCategory", UIParent, "SecureActionButtonTemplate")
    proxyCategory:SetAttribute("type", "click")
    proxyCategory:SetAttribute("useOnKeyDown", false)
    proxyFind = CreateFrame("Button", "KeyParseReturnFind", UIParent, "SecureActionButtonTemplate")
    proxyFind:SetAttribute("type", "click")
    proxyFind:SetAttribute("useOnKeyDown", false)

    returnButton = CreateFrame("Button", "KeyParseReturnButton", sel, "SecureActionButtonTemplate, UIPanelButtonTemplate")
    returnButton:SetSize(300, 26)
    returnButton:SetPoint("TOP", sel, "TOP", -3, -30) -- over the "Premade Groups" title
    returnButton:RegisterForClicks("AnyUp")
    returnButton:SetAttribute("useOnKeyDown", false)
    returnButton:SetAttribute("type", "macro")
    returnButton:SetAttribute("macrotext", "/click KeyParseReturnCategory\n/click KeyParseReturnFind")
    returnButton:SetScript("PostClick", function()
        if returnState then
            returnState.used = true
        end
        if not InCombatLockdown() then
            returnButton:Hide()
        end
    end)
    returnButton:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_BOTTOM")
        GameTooltip:SetText("Back to the group list you were browsing")
        if returnState and returnState.text then
            GameTooltip:AddLine(format("Then type |cffffff00%s|r in the search box and press Enter.", returnState.text), 1, 1, 1, true)
        end
        GameTooltip:AddLine("(Blizzard doesn't let addons run the search for you.)", 0.6, 0.6, 0.6, true)
        GameTooltip:Show()
    end)
    returnButton:SetScript("OnLeave", GameTooltip_Hide)
    returnButton:Hide()
    sel:HookScript("OnShow", UpdateReturnButton) -- the category buttons are filled in by then
end

-- After a KeyParse reload, open Group Finder > Premade Groups again.
local hintShown = false
local function ReopenGroupFinder()
    if InCombatLockdown() then
        return
    end
    if not (PVEFrame and PVEFrame:IsShown()) then
        if not PVEFrame and LoadAddOn then
            pcall(LoadAddOn, "Blizzard_GroupFinder")
        end
        local ok = PVEFrame_ShowFrame and pcall(PVEFrame_ShowFrame, "GroupFinderFrame", "LFGListPVEStub")
        if not ok and PVEFrame_ToggleFrame then
            pcall(PVEFrame_ToggleFrame, "GroupFinderFrame", "LFGListPVEStub")
        end
    end
    if RefreshApplicantLabels then
        RefreshApplicantLabels()
    end
    if returnState and returnState.categoryID then
        CreateReturnButton() -- only made when needed: most sessions never have this secure button
    end
    if UpdateReturnButton() then
        return
    end
    -- Your own listing reopens by itself. If you'd applied to someone else's group and we don't know
    -- what you were searching, say how to get the list back.
    local okOwn, own = pcall(C_LFGList.HasActiveEntryInfo)
    local okApps, apps = pcall(C_LFGList.GetApplications)
    if not (okOwn and own) and not (returnState and returnState.categoryID) and okApps and type(apps) == "table"
        and #apps > 0 and not hintShown then
        hintShown = true
        print(format("|cff33ff99KeyParse|r: your %d application(s) are still active. Click Dungeons, then Find Group, to see the list again.", #apps))
    end
end

-- After the reload is done: did the window come back?
local function CheckReopened()
    if not InCombatLockdown() and PVEFrame and not PVEFrame:IsShown() then
        Print("couldn't reopen the Group Finder (press |cffffff00I|r).")
    end
end

-- Search list extras: "type 18-18 again" reminder, and the parsed group's highlight.
local searchHint
local searchGlows = {}

local function FocusPosition(panel)
    -- where the parsed group sits in Blizzard's list: results first, then your applications
    local i = 0
    local seen = {}
    for _, list in ipairs({ type(panel.results) == "table" and panel.results or {},
                            type(panel.applications) == "table" and panel.applications or {} }) do
        for _, id in ipairs(list) do
            if not seen[id] then
                seen[id] = true
                i = i + 1
                if SameListing(id, returnState.focus) then
                    return i
                end
            end
        end
    end
end

-- Runs right after Blizzard sorts the search results: move the group you parsed to the top.
-- Only the order of Blizzard's own list changes (the same thing sorting addons do); nothing is
-- searched, selected or signed up for. /kp pin off turns it off.
local function PinParsedGroup(panel)
    if not KeyParseDB.settings.pinParsedGroup or not ReturnActive() or not returnState.focus then
        return
    end
    if type(panel) ~= "table" or panel.searching or type(panel.results) ~= "table" then
        return
    end
    local results = panel.results
    for i, id in ipairs(results) do
        if SameListing(id, returnState.focus) then
            if i > 1 then
                table.remove(results, i)
                table.insert(results, 1, id)
            end
            returnState.pinned = true
            return
        end
    end
end

local function UpdateSearchExtras(frames)
    local panel = LFGListFrame and LFGListFrame.SearchPanel
    local active = ReturnActive()
    local focusShown = false
    for _, f in ipairs(frames or {}) do
        local hit = active and returnState.focus and f.resultID and SameListing(f.resultID, returnState.focus)
        local glow = searchGlows[f]
        if hit and not glow then
            glow = f:CreateTexture(nil, "BACKGROUND", nil, 7) -- under the text
            glow:SetAllPoints(f)
            glow:SetColorTexture(0.2, 0.8, 1, 0.18)
            glow.bar = f:CreateTexture(nil, "OVERLAY")
            glow.bar:SetPoint("TOPLEFT", f, "TOPLEFT", 0, 0)
            glow.bar:SetPoint("BOTTOMLEFT", f, "BOTTOMLEFT", 0, 0)
            glow.bar:SetWidth(3)
            glow.bar:SetColorTexture(0.2, 0.8, 1, 0.9)
            searchGlows[f] = glow
        end
        if glow then
            glow:SetShown(hit and true or false)
            glow.bar:SetShown(hit and true or false)
        end
        focusShown = focusShown or (hit and true or false)
    end
    if not panel then
        return
    end
    if not searchHint and panel.CreateFontString then
        searchHint = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        searchHint:SetJustifyH("RIGHT")
    end
    if not searchHint then
        return
    end
    local text
    if active then
        local ok, current = pcall(function() return panel.SearchBox and panel.SearchBox:GetText() end)
        current = ok and IsSafe(current) and type(current) == "string" and current:match("^%s*(.-)%s*$") or ""
        if returnState.text and current:lower() ~= returnState.text:lower() and not returnState.searchedText then
            text = format("KeyParse: type |cffffff00%s|r + Enter", returnState.text)
        elseif returnState.focus and not focusShown and not panel.searching then
            local pos = FocusPosition(panel)
            text = pos and format("KeyParse: parsed group is |cffffff00#%d|r, scroll down", pos)
        elseif returnState.focus and focusShown and returnState.pinned and not panel.searching then
            text = "KeyParse: parsed group pinned to the top"
        end
        if returnState.text and current:lower() == returnState.text:lower() and panel.searching == false
            and type(panel.results) == "table" and panel:IsVisible() then
            returnState.searchedText = true -- done; don't nag if they change it later
        end
    end
    -- Warcraft Logs points: their own line ("WCL points: ..."), never mixed into a KeyParse notice;
    -- under the KeyParse hint when there is one.
    local pts = PointsText()
    local twoLines = text ~= nil and pts ~= nil
    if twoLines then
        text = text .. "\n" .. pts
    elseif pts then
        text = pts
    end
    searchHint:ClearAllPoints()
    searchHint:SetPoint("TOPRIGHT", panel, "TOPRIGHT", -10, twoLines and -29 or -36) -- 2 lines: start higher
    searchHint:SetText(text or "")
    searchHint:SetShown(text ~= nil)
end

local fetchButton
UpdateFetchButton = function()
    if not fetchButton then
        return
    end
    local n = 0
    for full in pairs(CurrentApplicants()) do
        if KeyParseDB.requests[full] then
            n = n + 1
        end
    end
    if n > 0 then
        fetchButton:SetText(format("KeyParse: fetch %d (reload)", n))
        fetchButton:Enable()
    else
        fetchButton:SetText("KeyParse: nothing to fetch")
        fetchButton:Disable() -- greyed out, still visible
    end
    fetchButton:Show()
end

local function OnSearchEntryTooltip(tooltip, resultID)
    local ok, info = pcall(C_LFGList.GetSearchResultInfo, resultID)
    if ok and info and IsSafe(info.leaderName) then
        AddLines(tooltip, FullName(info.leaderName))
        tooltip:Show()
    end
end

-- The dungeon picture at the top is a fixed-size atlas image. To fill the extra width without
-- distorting its border, draw it as 3 slices: the left and right edges at normal size, and the
-- middle stretched. The original stays (invisible) and is widened so things anchored to its right
-- edge (the group's role icons) move out to the new corner.
local BG_EDGE = 30
local bgSlices

local function ExtendInfoBackground(viewer, extra)
    local bg = viewer and viewer.InfoBackground
    if not bg or not bg.GetAtlas or not C_Texture or not C_Texture.GetAtlasInfo then
        return
    end
    local atlas = bg:GetAtlas()
    local info = atlas and C_Texture.GetAtlasInfo(atlas)
    if not info or not info.width or info.width <= BG_EDGE * 2 then
        return
    end
    if not bgSlices then
        bgSlices = {}
        for i = 1, 3 do
            bgSlices[i] = viewer:CreateTexture(nil, "BACKGROUND", nil, 1)
        end
        hooksecurefunc(bg, "SetAtlas", function() -- Blizzard swaps the picture per activity
            C_Timer.After(0, function() ExtendInfoBackground(viewer, IsWide() and COLUMN_WIDTH or 0) end)
        end)
    end
    if extra <= 0 then
        bg:SetSize(info.width, info.height)
        bg:SetAlpha(1)
        for _, t in ipairs(bgSlices) do
            t:Hide()
        end
        return
    end

    local file = info.file or info.filename
    local L, R, T, B = info.leftTexCoord, info.rightTexCoord, info.topTexCoord, info.bottomTexCoord
    local edgeTex = (R - L) * BG_EDGE / info.width
    local left, mid, right = bgSlices[1], bgSlices[2], bgSlices[3]
    for _, t in ipairs(bgSlices) do
        t:SetTexture(file)
        t:SetHeight(info.height)
        t:ClearAllPoints()
        t:Show()
    end
    left:SetTexCoord(L, L + edgeTex, T, B)
    left:SetWidth(BG_EDGE)
    left:SetPoint("TOPLEFT", bg, "TOPLEFT")
    mid:SetTexCoord(L + edgeTex, R - edgeTex, T, B)
    mid:SetWidth(info.width - BG_EDGE * 2 + extra)
    mid:SetPoint("TOPLEFT", left, "TOPRIGHT")
    right:SetTexCoord(R - edgeTex, R, T, B)
    right:SetWidth(BG_EDGE)
    right:SetPoint("TOPLEFT", mid, "TOPRIGHT")

    bg:SetSize(info.width + extra, info.height)
    bg:SetAlpha(0)
end

-- Make the Group Finder wider while your applicant list is showing, with a "Parse" column header.
local baseStubWidth, parseHeader
local function ApplyWidth()
    if not PVEFrame or not LFGListPVEStub or InCombatLockdown() then
        return
    end
    local viewer = LFGListFrame and LFGListFrame.ApplicationViewer
    baseStubWidth = baseStubWidth or LFGListPVEStub:GetWidth()
    local wide = IsWide() and viewer and viewer:IsVisible() and LFGListPVEStub:IsShown()
    local baseWidth = PVE_FRAME_BASE_WIDTH or 563
    if wide then
        PVEFrame:SetWidth(baseWidth + COLUMN_WIDTH)
        LFGListPVEStub:SetWidth(baseStubWidth + COLUMN_WIDTH)
    else
        if math.abs(PVEFrame:GetWidth() - (baseWidth + COLUMN_WIDTH)) < 1 then
            PVEFrame:SetWidth(baseWidth)
        end
        LFGListPVEStub:SetWidth(baseStubWidth)
    end
    if viewer and viewer.NameColumnHeader and viewer.RoleColumnHeader then
        if not parseHeader then
            local ok, header = pcall(CreateFrame, "Button", nil, viewer, "LFGListColumnHeaderTemplate")
            parseHeader = ok and header or CreateFrame("Button", nil, viewer)
            parseHeader:SetSize(COLUMN_WIDTH, 24)
            parseHeader:SetPoint("LEFT", viewer.NameColumnHeader, "RIGHT", 0, 0)
            parseHeader:EnableMouse(false)
            if not parseHeader:GetFontString() then
                parseHeader:SetNormalFontObject("GameFontHighlightSmall")
            end
            parseHeader:SetText("Parse")
        end
        parseHeader:SetShown(IsWide())
        viewer.RoleColumnHeader:ClearAllPoints()
        viewer.RoleColumnHeader:SetPoint("LEFT", viewer.NameColumnHeader, "RIGHT", IsWide() and COLUMN_WIDTH or 0, 0)
    end
    if viewer then
        ExtendInfoBackground(viewer, (IsWide() and COLUMN_WIDTH) or 0)
    end
    RefreshApplicantLabels()
end

local searchArrows = {}
local function RefreshSearchArrows()
    local panel = LFGListFrame and LFGListFrame.SearchPanel
    local box = panel and panel.ScrollBox
    if not box or not box.GetFrames then
        return
    end
    for _, frame in ipairs(box:GetFrames() or {}) do
        if frame.resultID then
            local arrow = searchArrows[frame]
            if not arrow then
                arrow = CreateFrame("Button", nil, frame)
                arrow:SetSize(16, 16)
                arrow:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -6, -5)
                arrow:SetNormalTexture("Interface\\Buttons\\UI-ScrollBar-ScrollDownButton-Up")
                arrow:SetPushedTexture("Interface\\Buttons\\UI-ScrollBar-ScrollDownButton-Down")
                arrow:SetHighlightTexture("Interface\\Buttons\\UI-ScrollBar-ScrollDownButton-Highlight", "ADD")
                arrow:SetScript("OnClick", function(self)
                    local parent = self:GetParent()
                    if parent and parent.resultID then
                        ShowListingMenu(self, parent.resultID)
                    end
                end)
                arrow:SetScript("OnEnter", function(self)
                    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
                    GameTooltip:SetText("KeyParse: the leader's parse")
                    GameTooltip:Show()
                end)
                arrow:SetScript("OnLeave", GameTooltip_Hide)
                searchArrows[frame] = arrow
            end
            arrow:SetShown(GroupFetchedCount((ListingMembers(frame.resultID))) > 0)
        end
    end
    UpdateSearchExtras(box:GetFrames())
end

RefreshSearchArrowsHook = RefreshSearchArrows

local groupFinderHooked = false
-- Applicants to your group, sorted: healers first (never looked up, and rare), then best parse first,
-- then everyone without a parse in Blizzard's order. Runs right after Blizzard sorts the list, and only
-- changes its order (the same kind of change as the search pin). /kp sort off turns it off.
-- One player's sort score: healers 1000, else the number on their row, -1 without one.
local function MemberScore(full, role)
    if role == "heal" then
        return 1000
    end
    local state, _, avg = RangeAvg(full, role) -- the number shown on the row
    return state == "ok" and avg or -1
end

local function ApplicantScore(applicantID)
    local ok, info = pcall(C_LFGList.GetApplicantInfo, applicantID)
    local count = ok and type(info) == "table" and info.numMembers or 1
    local best = -1
    for m = 1, count do
        local ok2, name, _, _, _, _, _, _, _, _, assignedRole = pcall(C_LFGList.GetApplicantMemberInfo, applicantID, m)
        if ok2 and IsSafe(name, assignedRole) and name then
            best = math.max(best, MemberScore(FullName(name), LFG_ROLE[assignedRole]))
        end
    end
    return best
end

-- Sorts list in place, best score first, ties keep their order. Used for Blizzard's list and the test queue.
local function SortByScore(list, scoreOf)
    if not KeyParseDB.settings.sortApplicants or type(list) ~= "table" or #list < 2 then
        return
    end
    local score, pos = {}, {}
    for i, item in ipairs(list) do
        pos[item] = i
        score[item] = scoreOf(item)
    end
    table.sort(list, function(a, b)
        if score[a] ~= score[b] then
            return score[a] > score[b]
        end
        return pos[a] < pos[b] -- keep Blizzard's order for ties
    end)
end

local function SortApplicantsByParse(applicants)
    SortByScore(applicants, ApplicantScore)
end

local function HookGroupFinder()
    if groupFinderHooked or not LFGListFrame or not LFGListFrame.ApplicationViewer then
        return
    end
    groupFinderHooked = true
    local viewer = LFGListFrame.ApplicationViewer

    local scrollBox = viewer.ScrollBox
    if scrollBox and scrollBox.RegisterCallback and ScrollBoxListMixin then
        scrollBox:RegisterCallback(ScrollBoxListMixin.Event.OnUpdate, RefreshApplicantLabels)
    end
    local searchBox = LFGListFrame.SearchPanel and LFGListFrame.SearchPanel.ScrollBox
    if searchBox and searchBox.RegisterCallback and ScrollBoxListMixin then
        searchBox:RegisterCallback(ScrollBoxListMixin.Event.OnUpdate, RefreshSearchArrows)
    end
    if LFGListUtil_SetSearchEntryTooltip then
        hooksecurefunc("LFGListUtil_SetSearchEntryTooltip", OnSearchEntryTooltip)
    end
    if LFGListUtil_SortSearchResults then
        hooksecurefunc("LFGListUtil_SortSearchResults", PinParsedGroup)
    end
    if LFGListUtil_SortApplicants then
        hooksecurefunc("LFGListUtil_SortApplicants", SortApplicantsByParse)
    end

    viewer:HookScript("OnShow", function()
        if dataLoaded then
            DropOldApplicantRequests() -- clear anything left over from earlier listings
        end
        ApplyWidth()
        UpdateFetchButton()
        PlaceRaiderIOButton(true)
    end)
    viewer:HookScript("OnHide", function()
        ApplyWidth()
        PlaceRaiderIOButton(false)
    end)
    if PVEFrame_ShowFrame then
        hooksecurefunc("PVEFrame_ShowFrame", ApplyWidth) -- Blizzard resets the width every time it opens
    end

    fetchButton = CreateFrame("Button", nil, viewer, "UIPanelButtonTemplate")
    fetchButton:SetSize(190, 22)
    fetchButton:SetPoint("BOTTOMRIGHT", viewer, "TOPRIGHT", -4, 2)
    fetchButton:SetScript("OnClick", FetchAndReload)
    UpdateFetchButton()
    RefreshApplicantLabels()
end

local function OnApplicantsChanged()
    -- wait until our data is loaded, so we don't re-queue players we already have
    if dataLoaded then
        DropOldApplicantRequests() -- someone withdrew or was declined
        if KeyParseDB.settings.autoQueueApplicants then
            QueueApplicants(true)
        end
    end
    UpdateFetchButton()
    RefreshApplicantLabels()
end

-------------------------------------------------------------------- test queue
-- /kp test or the options panel button: KeyParse's OWN frame, docked over the Premade Groups panel and drawn
-- like Blizzard's applicant list, filled with fake applicants you make up. It is not Blizzard's list (that one is
-- server-side; fake applicant IDs error and writing into it taints Invite/Decline) and uses no Blizzard
-- applicant templates. Rows go through the real RowText / AddApplicantLines / SortByScore code with TEST set
-- (WithTest), so labels, icons, tooltip and order are exactly what a real applicant with that data would get.
-- Fakes live in this Lua session only: never in KeyParseDB (requests, history) or the data slots, never looked
-- up (Queue refuses while TEST is set), no alert, no FlashClientIcon. Gone after a reload.

-- The section is one function scope so its locals don't count toward the file's 200-local limit.
local OpenTestQueue = (function()
    local TEST_DUNGEON = { -1, "KeyParse Test Dungeon" }
    local TEST_TIMER = 30 * 60
    local TEST_ROW_H = 24
    local TEST_ROW_W = BLIZZ.memberWidth + COLUMN_WIDTH + 84 -- + Invite/Decline
    local TEST_CLASSES = { "WARRIOR", "PALADIN", "HUNTER", "ROGUE", "PRIEST", "DEATHKNIGHT", "SHAMAN", "MAGE", "WARLOCK",
        "MONK", "DRUID", "DEMONHUNTER", "EVOKER" }
    local CLASS_SPECS = {
        WARRIOR = { { "Arms", "dps" }, { "Fury", "dps" }, { "Protection", "tank" } },
        PALADIN = { { "Holy", "heal" }, { "Protection", "tank" }, { "Retribution", "dps" } },
        HUNTER = { { "Beast Mastery", "dps" }, { "Marksmanship", "dps" }, { "Survival", "dps" } },
        ROGUE = { { "Assassination", "dps" }, { "Outlaw", "dps" }, { "Subtlety", "dps" } },
        PRIEST = { { "Discipline", "heal" }, { "Holy", "heal" }, { "Shadow", "dps" } },
        DEATHKNIGHT = { { "Blood", "tank" }, { "Frost", "dps" }, { "Unholy", "dps" } },
        SHAMAN = { { "Elemental", "dps" }, { "Enhancement", "dps" }, { "Restoration", "heal" } },
        MAGE = { { "Arcane", "dps" }, { "Fire", "dps" }, { "Frost", "dps" } },
        WARLOCK = { { "Affliction", "dps" }, { "Demonology", "dps" }, { "Destruction", "dps" } },
        MONK = { { "Brewmaster", "tank" }, { "Mistweaver", "heal" }, { "Windwalker", "dps" } },
        DRUID = { { "Balance", "dps" }, { "Feral", "dps" }, { "Guardian", "tank" }, { "Restoration", "heal" } },
        DEMONHUNTER = { { "Havoc", "dps" }, { "Vengeance", "tank" }, { "Devourer", "dps" } },
        EVOKER = { { "Devastation", "dps" }, { "Preservation", "heal" }, { "Augmentation", "dps" } },
    }
    local ROLE_LFG_NAME = { dps = "DAMAGER", heal = "HEALER", tank = "TANK" }
    local ROLE_ATLAS = { dps = "roleicon-tiny-dps", heal = "roleicon-tiny-healer", tank = "roleicon-tiny-tank" }

    local testState -- { key, classes = { "PALADIN", ... }, list = { fake, ... } }; this session only
    local testFrame, testEditor
    local RefreshTestQueue

    local function TestState()
        if not testState then
            testState = { key = KeyParseDB.settings.targetKey or ListingKey() or 15,
                classes = { UnitClassFile("player") or "PALADIN" }, list = {} }
        end
        return testState
    end

    local function ClassName(class)
        local names = _G.LOCALIZED_CLASS_NAMES_MALE
        return (type(names) == "table" and names[class]) or (class:sub(1, 1) .. class:sub(2):lower())
    end

    local function ClassHex(class)
        if C_ClassColor and C_ClassColor.GetClassColor then
            local ok, c = pcall(C_ClassColor.GetClassColor, class)
            if ok and type(c) == "table" and c.GenerateHexColor then
                return c:GenerateHexColor()
            end
        end
        local c = RAID_CLASS_COLORS and RAID_CLASS_COLORS[class]
        return c and c.colorStr or "ffffffff"
    end

    local function SpecRole(class, spec)
        for _, s in ipairs(CLASS_SPECS[class] or {}) do
            if s[1] == spec then
                return s[2]
            end
        end
    end

    -- The KeyParse_Data entry a real lookup would have produced for this fake (nil = never looked up).
    local function FakePlayer(f)
        if f.noLogs then
            return { t = time(), v = 2, missing = true }
        end
        local keys, total = {}, 0
        for _, k in ipairs(f.keys or {}) do
            if k.lvl and k.lvl >= 2 and (k.runs or 0) > 0 then
                local fastest = k.timed and (TEST_TIMER - 120) or (TEST_TIMER + 120)
                keys[k.lvl] = { k.runs, k.avg or 0, d = { [TEST_DUNGEON[1]] = { k.runs, k.avg or 0, fastest } } }
                total = total + k.runs
            end
        end
        if total == 0 then
            return nil
        end
        local role = f.logsRole or f.role
        return { t = time(), v = 2, spec = f.logSpec, roles = { [role] = keys }, specs = { [role] = { [f.logSpec or "?"] = total } } }
    end

    local function FakeHistory(f, key)
        local n = math.floor(f.played or 0)
        if n <= 0 then
            return nil
        end
        local e = { n = n, timed = math.max(0, math.min(math.floor(f.playedTimed or 0), n)), runs = {} }
        local shown = math.min(n, HISTORY_KEEP)
        for i = shown, 1, -1 do -- newest last; the newest ones are the timed ones
            e.runs[#e.runs + 1] = { t = time() - i * 86400, map = 0, lvl = key, timed = i <= e.timed }
        end
        return e
    end

    local function BuildTest()
        local st = TestState()
        local t = { key = st.key, classes = st.classes, players = {}, history = { players = {} },
            dungeons = { TEST_DUNGEON }, timers = { [TEST_DUNGEON[1]] = TEST_TIMER } }
        for _, f in ipairs(st.list) do
            t.players[f.name] = FakePlayer(f)
            t.history.players[f.name] = FakeHistory(f, st.key)
        end
        return t
    end

    -- Runs fn with the test data in place of the real data; always puts the real data back.
    local function WithTest(fn, ...)
        local prev = TEST
        TEST = BuildTest()
        local ok, a, b = pcall(fn, ...)
        TEST = prev
        if not ok then
            Print("test queue error: " .. tostring(a))
            return nil
        end
        return a, b
    end

    -- Three key levels ending at your key: { {lvl, avg, runs, timed}, ... }
    local function KeyRange(K, avgs, runs, timed, top)
        local keys = {}
        top = top or K
        for i = 1, 3 do
            local lvl = top - 3 + i
            if lvl >= 2 then
                keys[#keys + 1] = { lvl = lvl, avg = avgs[i], runs = runs[i], timed = timed }
            end
        end
        return keys
    end

    local TEST_PRESETS = {
        { "Strong", function(K) return { name = "Pyrostar-TestRealm", class = "MAGE", spec = "Fire", logSpec = "Fire",
            role = "dps", ilvl = 722, rating = 3350, keys = KeyRange(K, { 94, 91, 89 }, { 6, 5, 4 }, true),
            played = 3, playedTimed = 3 } end },
        { "Weak", function(K) return { name = "Bonkbonk-TestRealm", class = "WARRIOR", spec = "Fury", logSpec = "Fury",
            role = "dps", ilvl = 694, rating = 2050, keys = KeyRange(K, { 15, 12, 9 }, { 5, 4, 3 }, true) } end },
        { "New to key", function(K) return { name = "Stabsalot-TestRealm", class = "ROGUE", spec = "Outlaw", logSpec = "Outlaw",
            role = "dps", ilvl = 708, rating = 2600, keys = KeyRange(K, { 66, 72, 70 }, { 4, 5, 4 }, true, K - 1) } end },
        { "Wrong spec", function(K) return { name = "Petlover-TestRealm", class = "HUNTER", spec = "Marksmanship",
            logSpec = "Beast Mastery", role = "dps", ilvl = 715, rating = 2900, keys = KeyRange(K, { 78, 74, 71 }, { 5, 4, 3 }, true) } end },
        { "Too few runs", function(K) return { name = "Rarelogs-TestRealm", class = "WARLOCK", spec = "Destruction",
            logSpec = "Destruction", role = "dps", ilvl = 711, rating = 2700, keys = KeyRange(K, { 82, 0, 61 }, { 1, 0, 1 }, true) } end },
        { "Healer", function(K) return { name = "Holyglow-TestRealm", class = "PRIEST", spec = "Holy", logSpec = "Holy",
            role = "heal", ilvl = 716, rating = 3000, keys = {} } end },
        { "No logs", function(K) return { name = "Hiddenguy-TestRealm", class = "DEATHKNIGHT", spec = "Unholy",
            logSpec = "Unholy", role = "dps", ilvl = 705, rating = 2400, noLogs = true, keys = {} } end },
    }

    -- Adds a fake, replacing one with the same name (or the one being edited).
    local function AddFake(f, replacing)
        local list = TestState().list
        for i = #list, 1, -1 do
            if list[i].name == f.name or (replacing and list[i] == replacing) then
                table.remove(list, i)
            end
        end
        list[#list + 1] = f
        RefreshTestQueue()
    end

    local function RemoveFake(f)
        local list = TestState().list
        for i = #list, 1, -1 do
            if list[i] == f then
                table.remove(list, i)
            end
        end
        RefreshTestQueue()
    end

    local function AddPreset(index)
        local preset = TEST_PRESETS[index]
        if preset then
            AddFake(preset[2](TestState().key))
        end
    end

    -- small widget helpers
    local function Text(parent, text, x, y, font)
        local fs = parent:CreateFontString(nil, "OVERLAY", font or "GameFontNormalSmall")
        fs:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
        fs:SetText(text)
        return fs
    end

    local function Input(parent, width, x, y, numeric)
        local e = CreateFrame("EditBox", nil, parent, "InputBoxTemplate")
        e:SetSize(width, 20)
        e:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
        e:SetAutoFocus(false)
        if numeric then
            e:SetNumeric(true)
            e:SetMaxLetters(5)
        end
        e:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)
        e:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
        return e
    end

    local function Num(e, default)
        return tonumber(e:GetText() or "") or default
    end

    local function MenuButton(parent, width, x, y, fill)
        local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
        b:SetSize(width, 22)
        b:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
        b:SetScript("OnClick", function(self)
            if MenuUtil and MenuUtil.CreateContextMenu then
                MenuUtil.CreateContextMenu(self, function(_, root) fill(root) end)
            end
        end)
        return b
    end

    local function Check(parent, label, x, y)
        local c = CreateFrame("CheckButton", nil, parent, "UICheckButtonTemplate")
        c:SetSize(22, 22)
        c:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
        if label then
            local fs = c:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
            fs:SetPoint("LEFT", c, "RIGHT", 2, 0)
            fs:SetText(label)
        end
        return c
    end

    local function TestWindow(name, width, height, title)
        local ok, f = pcall(CreateFrame, "Frame", name, UIParent, "BasicFrameTemplateWithInset")
        if not ok or not f then
            f = CreateFrame("Frame", name, UIParent, "BackdropTemplate")
        end
        f:SetSize(width, height)
        f:SetFrameStrata("HIGH")
        f:SetToplevel(true)
        f:SetClampedToScreen(true)
        f:EnableMouse(true)
        f:SetMovable(true)
        f:RegisterForDrag("LeftButton")
        f:SetScript("OnDragStart", f.StartMoving)
        f:SetScript("OnDragStop", f.StopMovingOrSizing)
        local titleText = type(f.TitleText) == "table" and f.TitleText or Text(f, "", 10, -6, "GameFontNormal")
        titleText:SetText(title)
        f.title = titleText
        -- everything of ours goes on body, above the template's Inset (a child frame that would cover our regions)
        f.body = CreateFrame("Frame", nil, f)
        f.body:SetAllPoints(f)
        f.body:SetFrameLevel((f:GetFrameLevel() or 0) + 5)
        if type(UISpecialFrames) == "table" then
            table.insert(UISpecialFrames, name) -- Esc closes it
        end
        return f
    end

    -------- the editor ("Add fake applicant")

    local function FillEditor(ed)
        local d = ed.data
        ed.fields.name:SetText(d.name or "")
        ed.classButton:SetText("|c" .. ClassHex(d.class) .. ClassName(d.class) .. "|r")
        ed.specButton:SetText(d.spec or "?")
        ed.roleButton:SetText(ROLE_LABEL[d.role] or d.role)
        ed.logSpecButton:SetText(d.logSpec or "?")
        ed.logsRoleButton:SetText(d.logsRole and (ROLE_LABEL[d.logsRole] or d.logsRole) or "Same as applied")
        ed.fields.ilvl:SetText(tostring(d.ilvl or 0))
        ed.fields.rating:SetText(tostring(d.rating or 0))
        ed.noLogs:SetChecked(d.noLogs and true or false)
        for i, row in ipairs(ed.keyRows) do
            local k = d.keys[i] or {}
            row.lvl:SetText(k.lvl and tostring(k.lvl) or "")
            row.avg:SetText(k.avg and tostring(k.avg) or "")
            row.runs:SetText(k.runs and tostring(k.runs) or "")
            row.timed:SetChecked(k.timed and true or false)
        end
        ed.fields.played:SetText(tostring(d.played or 0))
        ed.fields.playedTimed:SetText(tostring(d.playedTimed or 0))
    end

    local function SaveEditor(ed)
        local d = ed.data
        local full = FullName(strtrim and strtrim(ed.fields.name:GetText() or "") or (ed.fields.name:GetText() or ""))
        if not full then
            Print("test queue: type a name (Name or Name-Realm).")
            return
        end
        d.name = full
        d.ilvl = Num(ed.fields.ilvl, 0)
        d.rating = Num(ed.fields.rating, 0)
        d.noLogs = ed.noLogs:GetChecked() and true or false
        d.keys = {}
        for _, row in ipairs(ed.keyRows) do
            local lvl = Num(row.lvl)
            if lvl then
                d.keys[#d.keys + 1] = { lvl = lvl, avg = math.max(0, math.min(100, Num(row.avg, 0))), runs = Num(row.runs, 0),
                    timed = row.timed:GetChecked() and true or false }
            end
        end
        d.played = Num(ed.fields.played, 0)
        d.playedTimed = Num(ed.fields.playedTimed, 0)
        AddFake(d, ed.original)
        ed:Hide()
    end

    local function CreateEditor()
        local ed = TestWindow("KeyParseTestEditor", 330, 420, "KeyParse test queue: fake applicant")
        ed.fields = {}
        local W = ed.body
        local y = -32
        Text(W, "Name-Realm", 14, y - 4)
        ed.fields.name = Input(W, 170, 130, y)
        y = y - 28
        Text(W, "Class", 14, y - 5)
        ed.classButton = MenuButton(W, 170, 126, y, function(root)
            for _, class in ipairs(TEST_CLASSES) do
                root:CreateButton("|c" .. ClassHex(class) .. ClassName(class) .. "|r", function()
                    local d = ed.data
                    d.class = class
                    local first = CLASS_SPECS[class][1]
                    d.spec, d.logSpec, d.role = first[1], first[1], first[2]
                    FillEditor(ed)
                end)
            end
        end)
        y = y - 26
        Text(W, "Applied as (spec)", 14, y - 5)
        ed.specButton = MenuButton(W, 170, 126, y, function(root)
            for _, s in ipairs(CLASS_SPECS[ed.data.class] or {}) do
                root:CreateButton(s[1], function()
                    ed.data.spec, ed.data.role = s[1], s[2]
                    FillEditor(ed)
                end)
            end
        end)
        y = y - 26
        Text(W, "Role", 14, y - 5)
        ed.roleButton = MenuButton(W, 170, 126, y, function(root)
            for _, r in ipairs({ "dps", "tank", "heal" }) do
                root:CreateButton(ROLE_LABEL[r], function()
                    ed.data.role = r
                    FillEditor(ed)
                end)
            end
        end)
        y = y - 26
        Text(W, "Logs are on (spec)", 14, y - 5)
        ed.logSpecButton = MenuButton(W, 170, 126, y, function(root)
            for _, s in ipairs(CLASS_SPECS[ed.data.class] or {}) do
                root:CreateButton(s[1], function()
                    ed.data.logSpec = s[1]
                    FillEditor(ed)
                end)
            end
        end)
        y = y - 26
        Text(W, "Logs are as (role)", 14, y - 5)
        ed.logsRoleButton = MenuButton(W, 170, 126, y, function(root)
            root:CreateButton("Same as applied", function()
                ed.data.logsRole = nil
                FillEditor(ed)
            end)
            for _, r in ipairs({ "dps", "tank", "heal" }) do
                root:CreateButton(ROLE_LABEL[r], function()
                    ed.data.logsRole = r
                    FillEditor(ed)
                end)
            end
        end)
        y = y - 30
        Text(W, "Item level", 14, y - 4)
        ed.fields.ilvl = Input(W, 40, 84, y, true)
        Text(W, "M+ rating", 150, y - 4)
        ed.fields.rating = Input(W, 50, 220, y, true)
        y = y - 26
        ed.noLogs = Check(W, "No public logs on Warcraft Logs", 10, y)
        y = y - 28
        Text(W, "Key", 20, y)
        Text(W, "Avg parse", 66, y)
        Text(W, "Runs", 140, y)
        Text(W, "Timed", 190, y)
        ed.keyRows = {}
        for i = 1, 3 do
            y = y - 22
            local row = {}
            row.lvl = Input(W, 30, 20, y, true)
            row.avg = Input(W, 40, 70, y, true)
            row.runs = Input(W, 30, 140, y, true)
            row.timed = Check(W, nil, 192, y + 1)
            ed.keyRows[i] = row
        end
        y = y - 30
        Text(W, "Played with you: keys", 14, y - 4)
        ed.fields.played = Input(W, 30, 150, y, true)
        Text(W, "timed", 192, y - 4)
        ed.fields.playedTimed = Input(W, 30, 232, y, true)

        ed.saveButton = CreateFrame("Button", nil, W, "UIPanelButtonTemplate")
        ed.saveButton:SetSize(130, 22)
        ed.saveButton:SetPoint("BOTTOMLEFT", ed, "BOTTOMLEFT", 14, 12)
        ed.saveButton:SetText("Add to test queue")
        ed.saveButton:SetScript("OnClick", function() SaveEditor(ed) end)
        local cancel = CreateFrame("Button", nil, W, "UIPanelButtonTemplate")
        cancel:SetSize(80, 22)
        cancel:SetPoint("BOTTOMRIGHT", ed, "BOTTOMRIGHT", -14, 12)
        cancel:SetText(CANCEL or "Cancel")
        cancel:SetScript("OnClick", function() ed:Hide() end)
        return ed
    end

    -- f: a fake to edit, or nil for a new one.
    local function OpenTestEditor(f)
        testEditor = testEditor or CreateEditor()
        local K = TestState().key
        local d = {}
        if f then
            for k, v in pairs(f) do
                d[k] = v
            end
            d.keys = {}
            for i, k in ipairs(f.keys or {}) do
                d.keys[i] = { lvl = k.lvl, avg = k.avg, runs = k.runs, timed = k.timed }
            end
        else
            d = { name = "Testplayer-TestRealm", class = "MAGE", spec = "Fire", logSpec = "Fire", role = "dps",
                ilvl = 715, rating = 2800, keys = KeyRange(K, { 70, 68, 65 }, { 4, 3, 2 }, true), played = 0, playedTimed = 0 }
        end
        testEditor.data, testEditor.original = d, f
        testEditor.saveButton:SetText(f and "Save" or "Add to test queue")
        FillEditor(testEditor)
        testEditor:ClearAllPoints()
        if testFrame and testFrame:IsShown() then
            testEditor:SetPoint("TOPLEFT", testFrame, "TOPRIGHT", 4, 0)
        else
            testEditor:SetPoint("CENTER", UIParent, "CENTER", 200, 0)
        end
        testEditor:Show()
    end

    -------- the queue window

    local function SetRoleIcon(tex, role)
        local atlas
        if GetIconForRole then
            local ok, a = pcall(GetIconForRole, ROLE_LFG_NAME[role], false)
            atlas = ok and type(a) == "string" and a or nil
        end
        if not (atlas and C_Texture and C_Texture.GetAtlasInfo and C_Texture.GetAtlasInfo(atlas)) then
            atlas = ROLE_ATLAS[role]
        end
        if tex.SetAtlas then
            tex:SetAtlas(atlas)
        end
    end

    local function RatingText(rating)
        if C_ChallengeMode and C_ChallengeMode.GetDungeonScoreRarityColor then
            local ok, c = pcall(C_ChallengeMode.GetDungeonScoreRarityColor, rating)
            if ok and type(c) == "table" and c.WrapTextInColorCode then
                return c:WrapTextInColorCode(tostring(rating))
            end
        end
        return tostring(rating)
    end

    local function OnTestRowEnter(row)
        local f = row.fake
        if not f then
            return
        end
        GameTooltip:SetOwner(row, "ANCHOR_RIGHT")
        GameTooltip:SetText("|c" .. ClassHex(f.class) .. f.name .. "|r")
        GameTooltip:AddLine("TEST applicant - not real", 1, 0.3, 0.3)
        GameTooltip:AddLine(format("%s %s", f.spec or "", ClassName(f.class)), 1, 1, 1)
        GameTooltip:AddLine(format("Item Level: %d", f.ilvl or 0), 1, 1, 1)
        GameTooltip:AddLine("Mythic+ Rating: " .. RatingText(f.rating or 0), 1, 1, 1)
        WithTest(AddApplicantLines, GameTooltip, f.name, f.role, f.spec, f.class)
        GameTooltip:AddLine("Click to edit", 0.5, 0.5, 0.5)
        GameTooltip:Show()
    end

    local function CreateTestRow(parent, i)
        local r = CreateFrame("Button", nil, parent)
        r:SetSize(TEST_ROW_W, TEST_ROW_H)
        r:SetPoint("TOPLEFT", parent, "TOPLEFT", 0, -(i - 1) * TEST_ROW_H)
        r:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
        r.Name = r:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        r.Name:SetPoint("LEFT", r, "LEFT", 8, 0)
        r.Name:SetWidth(NAME_RIGHT - 8)
        r.Name:SetJustifyH("LEFT")
        r.Name:SetWordWrap(false)
        r.Label = r:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        r.Label:SetPoint("LEFT", r, "LEFT", NAME_RIGHT + 4, 0)
        r.Label:SetWidth(COLUMN_WIDTH - 22)
        r.Label:SetJustifyH("LEFT")
        r.Label:SetWordWrap(false)
        r.Arrow = CreateFrame("Button", nil, r)
        r.Arrow:SetSize(16, 16)
        r.Arrow:SetPoint("LEFT", r, "LEFT", NAME_RIGHT + COLUMN_WIDTH - 17, 0)
        r.Arrow:SetNormalTexture("Interface\\Buttons\\UI-ScrollBar-ScrollDownButton-Up")
        r.Arrow:SetPushedTexture("Interface\\Buttons\\UI-ScrollBar-ScrollDownButton-Down")
        r.Arrow:SetHighlightTexture("Interface\\Buttons\\UI-ScrollBar-ScrollDownButton-Highlight", "ADD")
        r.Arrow:SetScript("OnClick", function(self)
            local f = r.fake
            if f then
                WithTest(ShowAllKeys, self, f.name, f.role)
            end
        end)
        r.Role = r:CreateTexture(nil, "ARTWORK")
        r.Role:SetSize(16, 16)
        r.Role:SetPoint("LEFT", r, "LEFT", BLIZZ.roleX + COLUMN_WIDTH, 0)
        r.ItemLevel = r:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        r.ItemLevel:SetPoint("CENTER", r, "LEFT", BLIZZ.ilvlX + COLUMN_WIDTH, 0)
        r.Rating = r:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        r.Rating:SetPoint("CENTER", r, "LEFT", BLIZZ.ratingX + COLUMN_WIDTH, 0)
        r.Decline = CreateFrame("Button", nil, r)
        r.Decline:SetSize(20, 20)
        r.Decline:SetPoint("RIGHT", r, "RIGHT", -4, 0)
        r.Decline:SetNormalTexture("Interface\\Buttons\\UI-GroupLoot-Pass-Up")
        r.Decline:SetPushedTexture("Interface\\Buttons\\UI-GroupLoot-Pass-Down")
        r.Decline:SetHighlightTexture("Interface\\Buttons\\UI-GroupLoot-Pass-Highlight", "ADD")
        r.Decline:SetScript("OnClick", function() RemoveFake(r.fake) end)
        r.Invite = CreateFrame("Button", nil, r, "UIPanelButtonTemplate")
        r.Invite:SetSize(52, 20)
        r.Invite:SetPoint("RIGHT", r.Decline, "LEFT", -2, 0)
        r.Invite:SetText(INVITE or "Invite")
        r.Invite:SetScript("OnClick", function() RemoveFake(r.fake) end)
        r:SetScript("OnEnter", OnTestRowEnter)
        r:SetScript("OnLeave", GameTooltip_Hide)
        r:SetScript("OnClick", function() OpenTestEditor(r.fake) end)
        return r
    end

    local function GroupText(classes)
        local parts = {}
        for _, c in ipairs(classes) do
            parts[#parts + 1] = "|c" .. ClassHex(c) .. ClassName(c) .. "|r"
        end
        return #parts > 0 and table.concat(parts, ", ") or "nobody"
    end

    -- Over Blizzard's Premade Groups panel when it's open (anchoring our frame to theirs doesn't touch theirs),
    -- otherwise in the middle of the screen.
    local function DockTestFrame()
        testFrame:ClearAllPoints()
        local lfg = LFGListFrame
        if type(lfg) == "table" and lfg.IsVisible and lfg:IsVisible() then
            testFrame:SetPoint("TOPLEFT", lfg, "TOPLEFT", -4, 0)
        else
            testFrame:SetPoint("CENTER", UIParent, "CENTER", 0, 40)
        end
    end

    local function CreateTestFrame()
        local f = TestWindow("KeyParseTestQueue", TEST_ROW_W + 36, 440, "KeyParse test queue")
        local W = f.body
        -- banner + watermark: this can never be mistaken for the real list
        local banner = W:CreateTexture(nil, "ARTWORK")
        banner:SetPoint("TOPLEFT", f, "TOPLEFT", 8, -26)
        banner:SetPoint("TOPRIGHT", f, "TOPRIGHT", -8, -26)
        banner:SetHeight(20)
        banner:SetColorTexture(0.55, 0.08, 0.08, 0.85)
        local bannerText = W:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
        bannerText:SetPoint("CENTER", banner, "CENTER", 0, 0)
        bannerText:SetText("TEST - not real applicants")
        f.banner = bannerText
        local mark = W:CreateFontString(nil, "BACKGROUND", "GameFontNormalHuge")
        mark:SetFont(STANDARD_TEXT_FONT or "Fonts\\FRIZQT__.TTF", 110, "OUTLINE")
        mark:SetPoint("CENTER", f, "CENTER", 0, -40)
        mark:SetText("TEST")
        mark:SetTextColor(1, 1, 1)
        mark:SetAlpha(0.07)
        f.watermark = mark

        -- your key + your group
        Text(W, "Your key  +", 14, -58)
        f.keyBox = Input(W, 32, 84, -54, true)
        local function SetKey(self)
            local n = tonumber(self:GetText() or "")
            if n then
                TestState().key = math.max(2, math.min(40, math.floor(n)))
            end
            self:SetText(tostring(TestState().key))
            RefreshTestQueue()
        end
        f.keyBox:SetScript("OnEnterPressed", function(self) self:ClearFocus() SetKey(self) end)
        f.keyBox:SetScript("OnEditFocusLost", SetKey)
        Text(W, "Your group", 136, -58)
        f.groupButton = MenuButton(W, TEST_ROW_W - 190, 206, -54, function(root)
            root:CreateTitle("Classes in your group (you + party)")
            for _, class in ipairs(TEST_CLASSES) do
                root:CreateCheckbox("|c" .. ClassHex(class) .. ClassName(class) .. "|r",
                    function() return tContains and tContains(TestState().classes, class) or false end,
                    function()
                        local classes = TestState().classes
                        for i = #classes, 1, -1 do
                            if classes[i] == class then
                                table.remove(classes, i)
                                RefreshTestQueue()
                                return
                            end
                        end
                        classes[#classes + 1] = class
                        RefreshTestQueue()
                    end)
            end
        end)

        f.addButton = CreateFrame("Button", nil, W, "UIPanelButtonTemplate")
        f.addButton:SetSize(150, 22)
        f.addButton:SetPoint("TOPLEFT", f, "TOPLEFT", 12, -80)
        f.addButton:SetText("Add fake applicant")
        f.addButton:SetScript("OnClick", function() OpenTestEditor(nil) end)
        f.presetButton = MenuButton(W, 110, 166, -80, function(root)
            root:CreateTitle("Add a preset applicant")
            for i, preset in ipairs(TEST_PRESETS) do
                root:CreateButton(preset[1], function() AddPreset(i) end)
            end
            root:CreateDivider()
            root:CreateButton("All presets", function()
                for i = 1, #TEST_PRESETS do
                    AddPreset(i)
                end
            end)
        end)
        f.presetButton:SetText("Presets")
        f.clearButton = CreateFrame("Button", nil, W, "UIPanelButtonTemplate")
        f.clearButton:SetSize(80, 22)
        f.clearButton:SetPoint("TOPLEFT", f, "TOPLEFT", 280, -80)
        f.clearButton:SetText("Clear")
        f.clearButton:SetScript("OnClick", function()
            TestState().list = {}
            RefreshTestQueue()
        end)

        -- column headers, like Blizzard's
        local hy = -110
        Text(W, NAME or "Name", 20, hy)
        Text(W, "KeyParse", 12 + NAME_RIGHT + 4, hy)
        Text(W, ROLE or "Role", 12 + BLIZZ.roleX + COLUMN_WIDTH - 4, hy)
        Text(W, "iLvl", 12 + BLIZZ.ilvlX + COLUMN_WIDTH - 10, hy)
        Text(W, "Rating", 12 + BLIZZ.ratingX + COLUMN_WIDTH - 16, hy)

        local scroll = CreateFrame("ScrollFrame", nil, W, "UIPanelScrollFrameTemplate")
        scroll:SetPoint("TOPLEFT", f, "TOPLEFT", 12, -126)
        scroll:SetPoint("BOTTOMRIGHT", f, "BOTTOMRIGHT", -30, 34)
        local content = CreateFrame("Frame", nil, scroll)
        content:SetSize(TEST_ROW_W, TEST_ROW_H)
        scroll:SetScrollChild(content)
        f.content = content
        f.rows = {}
        f.empty = Text(W, "No fake applicants yet: add one, or pick a preset.", 20, -140, "GameFontDisableSmall")
        f.footer = Text(W, "", 14, -414, "GameFontDisableSmall")
        f.footer:ClearAllPoints()
        f.footer:SetPoint("BOTTOMLEFT", f, "BOTTOMLEFT", 14, 12)
        f:SetScript("OnShow", function()
            DockTestFrame()
            RefreshTestQueue()
        end)
        f:SetScript("OnHide", function()
            if testEditor then
                testEditor:Hide()
            end
        end)
        return f
    end

    RefreshTestQueue = function()
        if not testFrame or not testFrame:IsShown() then
            return
        end
        local st = TestState()
        local list = {}
        for _, f in ipairs(st.list) do
            list[#list + 1] = f
        end
        -- the real sort, label and icon code, reading the test data
        local texts, arrows = WithTest(function()
            SortByScore(list, function(f) return MemberScore(f.name, f.role) end)
            local has = GroupHas()
            local out, arr = {}, {}
            for i, f in ipairs(list) do
                out[i] = RowText(f.name, f.role, f.spec, f.class, has)
                local p = GetPlayer(f.name)
                arr[i] = p and p.roles and next(p.roles) ~= nil or false
            end
            return out, arr
        end)
        texts, arrows = texts or {}, arrows or {}
        for i, f in ipairs(list) do
            local r = testFrame.rows[i] or CreateTestRow(testFrame.content, i)
            testFrame.rows[i] = r
            r.fake = f
            r.Name:SetText("|c" .. ClassHex(f.class) .. f.name .. "|r")
            r.Label:SetText(texts[i] or "")
            r.Arrow:SetShown(arrows[i] or false)
            SetRoleIcon(r.Role, f.role)
            r.ItemLevel:SetText(tostring(f.ilvl or 0))
            r.Rating:SetText(RatingText(f.rating or 0))
            r:Show()
        end
        for i = #list + 1, #testFrame.rows do
            testFrame.rows[i].fake = nil
            testFrame.rows[i]:Hide()
        end
        testFrame.content:SetHeight(math.max(TEST_ROW_H, #list * TEST_ROW_H))
        testFrame.empty:SetShown(#list == 0)
        testFrame.keyBox:SetText(tostring(st.key))
        testFrame.groupButton:SetText(GroupText(st.classes))
        local note = KeyParseDB.settings.sortApplicants and "Sorted like your real list." or "Not sorted (/kp sort on)."
        if st.key > WEAK_MAX_KEY then
            note = note .. format(" No skulls above +%d.", WEAK_MAX_KEY)
        end
        testFrame.footer:SetText(note .. " Fakes are never looked up or saved.")
    end

    local function OpenTestQueueNow()
        testFrame = testFrame or CreateTestFrame()
        testFrame:Show()
        DockTestFrame()
        RefreshTestQueue()
    end

    return OpenTestQueueNow
end)()

-------------------------------------------------------------------- player search
-- /kp search Name-Realm: everything KeyParse knows about one player in its own window, so you don't need
-- the Warcraft Logs site. A player without fresh data is queued and fetched with one reload (addons can't go
-- online); the window reopens on that player after the reload. KeyParseDB.search = { recent = { full, ... },
-- reopen = { full, at } }. Only real data: never opened from the test queue.

PlayerSearch = (function()
    local SEARCH_RECENT = 10
    local SEARCH_KEYS = 14     -- key-level rows shown
    local SEARCH_DUNGEONS = 8  -- dungeon rows shown
    local REOPEN_FOR = 300     -- seconds: reopen the window after a reload KeyParse started for a search
    local searchFrame
    local shown = { full = nil, role = nil, lvl = nil }
    local fetching = false     -- just reloaded for this search: data slots still loading
    local RefreshSearch

    local function SearchDB()
        local s = KeyParseDB.search
        if type(s) ~= "table" then
            s = {}
            KeyParseDB.search = s
        end
        s.recent = type(s.recent) == "table" and s.recent or {}
        return s
    end

    -- "taftonator-dalaran" -> "Taftonator-Dalaran": the same key the menus and applicants use, so one player
    -- never gets two lookups. Realms are matched case-insensitively against yours and every name we know.
    local function CanonicalName(text)
        text = (text or ""):gsub("^%s+", ""):gsub("%s+$", "")
        local full = FullName(text)
        if not full then
            return nil
        end
        local name, realm = full:match("^([^%-]+)%-(.+)$")
        name = name:sub(1, 1):upper() .. name:sub(2):lower()
        local want = realm:lower()
        local mine = (GetNormalizedRealmName() or ""):gsub("[%s%-]", "")
        if mine:lower() == want then
            return name .. "-" .. mine
        end
        local known = { KeyParse_Data.players, KeyParseDB.requests, History().players }
        for _, t in ipairs(known) do
            for k in pairs(t) do
                local r = type(k) == "string" and k:match("^[^%-]+%-(.+)$")
                if r and r:lower() == want then
                    return name .. "-" .. r
                end
            end
        end
        for _, k in ipairs(SearchDB().recent) do
            local r = k:match("^[^%-]+%-(.+)$")
            if r and r:lower() == want then
                return name .. "-" .. r
            end
        end
        return name .. "-" .. realm:sub(1, 1):upper() .. realm:sub(2)
    end

    local function Remember(full)
        local recent = SearchDB().recent
        for i = #recent, 1, -1 do
            if recent[i] == full then
                table.remove(recent, i)
            end
        end
        table.insert(recent, 1, full)
        while #recent > SEARCH_RECENT do
            table.remove(recent)
        end
    end

    local function Clock(sec)
        sec = math.floor(sec + 0.5)
        return format("%d:%02d", math.floor(sec / 60), sec % 60)
    end

    -- Queue the player and fetch (reload) right away when that's allowed. Returns what happened.
    local function Fetch(full)
        if not Queue(full, true) then
            return "refused"
        end
        if KeyParseDB.settings.reloadOnLookup and not InCombatLockdown() then
            SearchDB().reopen = { full = full, at = time() }
            FetchAndReload()
            return "reloading"
        end
        return "queued"
    end

    -------- the window

    local function Text(parent, x, y, font, width)
        local fs = parent:CreateFontString(nil, "OVERLAY", font or "GameFontHighlightSmall")
        fs:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
        fs:SetJustifyH("LEFT")
        if width then
            fs:SetWidth(width)
        end
        return fs
    end

    local function ListButton(parent, x, y, width, onClick)
        local b = CreateFrame("Button", nil, parent)
        b:SetSize(width, 16)
        b:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
        b:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
        b.label = b:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        b.label:SetPoint("LEFT", b, "LEFT", 4, 0)
        b.label:SetJustifyH("LEFT")
        b:SetScript("OnClick", onClick)
        return b
    end

    local function PanelButton(parent, text, width, onClick)
        local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
        b:SetSize(width, 22)
        b:SetText(text)
        b:SetScript("OnClick", onClick)
        return b
    end

    local Show -- below

    local function DoSearch(text)
        local full = CanonicalName(text)
        if not full then
            Print("search: type a name, e.g. |cffffff00/kp search Name-Realm|r (realm optional = yours).")
            return
        end
        Remember(full)
        local result
        if NeedsLookup(full) then
            result = Fetch(full)
        end
        Show(full, result)
    end

    local function CreateSearchFrame()
        local name = "KeyParseSearch"
        local ok, f = pcall(CreateFrame, "Frame", name, UIParent, "BasicFrameTemplateWithInset")
        if not ok or not f then
            f = CreateFrame("Frame", name, UIParent, "BackdropTemplate")
        end
        f:SetSize(620, 470)
        f:SetPoint("CENTER", UIParent, "CENTER", 0, 40)
        f:SetFrameStrata("HIGH")
        f:SetToplevel(true)
        f:SetClampedToScreen(true)
        f:EnableMouse(true)
        f:SetMovable(true)
        f:RegisterForDrag("LeftButton")
        f:SetScript("OnDragStart", f.StartMoving)
        f:SetScript("OnDragStop", f.StopMovingOrSizing)
        local title = type(f.TitleText) == "table" and f.TitleText or Text(f, 10, -6, "GameFontNormal")
        title:SetText("KeyParse search")
        if type(UISpecialFrames) == "table" then
            table.insert(UISpecialFrames, name) -- Esc closes it
        end
        local body = CreateFrame("Frame", nil, f) -- above the template's Inset, like the test queue
        body:SetAllPoints(f)
        body:SetFrameLevel((f:GetFrameLevel() or 0) + 5)
        f.body = body

        -- search box
        local box = CreateFrame("EditBox", nil, body, "InputBoxTemplate")
        box:SetSize(200, 20)
        box:SetPoint("TOPLEFT", body, "TOPLEFT", 20, -32)
        box:SetAutoFocus(false)
        box:SetScript("OnEnterPressed", function(self)
            self:ClearFocus()
            DoSearch(self:GetText())
        end)
        box:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
        f.box = box
        f.searchButton = PanelButton(body, "Search", 80, function() DoSearch(box:GetText()) end)
        f.searchButton:SetPoint("LEFT", box, "RIGHT", 6, 0)
        f.hint = Text(body, 320, -36, "GameFontDisableSmall", 280)
        f.hint:SetText("Name-Realm (no realm = yours), then Enter")

        -- recent searches (left)
        Text(body, 14, -64, "GameFontNormalSmall"):SetText("Recent")
        f.recent = {}
        for i = 1, SEARCH_RECENT do
            local b = ListButton(body, 10, -64 - i * 17, 140, function(self)
                if self.full then
                    Show(self.full)
                end
            end)
            f.recent[i] = b
        end

        -- the player (right)
        local X = 166
        f.header = Text(body, X, -62, "GameFontNormalLarge", 430)
        f.sub = Text(body, X, -84, "GameFontHighlightSmall", 430)
        f.status = Text(body, X, -100, "GameFontHighlightSmall", 430)
        f.roleButtons = {}
        for i, role in ipairs({ "dps", "tank" }) do
            local b = PanelButton(body, ROLE_LABEL[role], 60, function()
                shown.role, shown.lvl = role, nil
                RefreshSearch()
            end)
            b:SetPoint("TOPLEFT", body, "TOPLEFT", X + 330 + (i - 1) * 64, -60)
            b.role = role
            f.roleButtons[role] = b
        end

        f.keysTitle = Text(body, X, -120, "GameFontNormalSmall")
        f.keysTitle:SetText("Key   avg   runs")
        f.keyRows = {}
        for i = 1, SEARCH_KEYS do
            f.keyRows[i] = ListButton(body, X - 4, -122 - i * 17, 130, function(self)
                if self.lvl then
                    shown.lvl = self.lvl
                    RefreshSearch()
                end
            end)
        end

        local DX = X + 140
        f.dungeonTitle = Text(body, DX, -120, "GameFontNormalSmall", 300)
        f.dungeonRows = {}
        for i = 1, SEARCH_DUNGEONS do
            local y = -122 - i * 17
            f.dungeonRows[i] = {
                name = Text(body, DX, y - 2, "GameFontHighlightSmall", 150),
                avg = Text(body, DX + 152, y - 2, "GameFontHighlightSmall", 40),
                runs = Text(body, DX + 190, y - 2, "GameFontHighlightSmall", 40),
                time = Text(body, DX + 230, y - 2, "GameFontHighlightSmall", 90),
            }
        end
        f.specs = Text(body, DX, -122 - (SEARCH_DUNGEONS + 1) * 17 - 4, "GameFontHighlightSmall", 300)
        f.history = {}
        for i = 1, 1 + HISTORY_SHOWN do
            f.history[i] = Text(body, DX, -122 - (SEARCH_DUNGEONS + 2 + i) * 17, "GameFontHighlightSmall", 300)
        end

        -- footer
        f.points = Text(body, 14, -440, "GameFontDisableSmall", 380)
        f.fetchButton = PanelButton(body, "Refresh", 110, function()
            if shown.full then
                local result = Fetch(shown.full)
                Show(shown.full, result)
            end
        end)
        f.fetchButton:SetPoint("BOTTOMRIGHT", body, "BOTTOMRIGHT", -14, 10)
        return f
    end

    -- Text of the status line for players without numbers to show (and after a fetch attempt).
    local function StatusText(full, state, result)
        if result == "reloading" or (state == "queued" and fetching) then
            return "|cffffff00Fetching from Warcraft Logs...|r"
        elseif result == "queued" and InCombatLockdown() then
            return "|cffffff00Queued. Leave combat, then /reload to fetch.|r"
        elseif state == "queued" then
            return "|cffffff00Queued: /reload (or Fetch now) to look them up. The companion app must be running.|r"
        elseif state == "none" then
            return "|cff888888Not looked up yet.|r"
        elseif state == "error" then
            return "|cffff5555Lookup failed (wrong name or realm?). Try again in a few minutes.|r"
        elseif state == "missing" then
            return "|cff888888No public M+ DPS or tank logs this season (healers aren't looked up).|r"
        end
        return ""
    end

    RefreshSearch = function(result)
        local f = searchFrame
        if not f or not f:IsShown() then
            return
        end
        local db = SearchDB()
        for i, b in ipairs(f.recent) do
            local full = db.recent[i]
            b.full = full
            b.label:SetText(full and ((full == shown.full and "|cffffd100" or "|cffffffff") .. full .. "|r") or "")
            b:SetShown(full ~= nil)
        end
        f.points:SetText(PointsText() or "")

        local full = shown.full
        local p = full and GetPlayer(full)
        local state = full and Summarize(full) or "none"
        f.header:SetText(full or "Search a player")
        local roles = p and not p.missing and not p.error and p.roles or {}
        local role = (shown.role and roles[shown.role]) and shown.role or MainRole({ roles = roles })
        shown.role = role
        for r, b in pairs(f.roleButtons) do
            b:SetShown(roles[r] ~= nil and CountKeys(roles) > 1)
            if b.LockHighlight then
                if r == role then b:LockHighlight() else b:UnlockHighlight() end
            end
        end

        local keys = role and roles[role]
        if p and p.t and not p.missing and not p.error then
            f.sub:SetText(format("%s%s  |cff888888looked up %s|r", ROLE_LABEL[role] or "",
                p.spec and (" - " .. p.spec) or "", AgoText(p.t)))
        else
            f.sub:SetText(full and "" or "Type a name above. Results stay here after a reload.")
        end
        local status = StatusText(full, state, result)
        f.status:SetText(status)
        local needs = full and NeedsLookup(full)
        f.fetchButton:SetText(state == "queued" and "Fetch now" or ((p and not p.error) and "Refresh" or "Get parses"))
        f.fetchButton:SetShown(full ~= nil and result ~= "reloading" and (needs or state == "queued" or p ~= nil))

        -- key levels
        local levels = {}
        for k in pairs(keys or {}) do
            levels[#levels + 1] = k
        end
        table.sort(levels, function(a, b) return a > b end)
        if keys and not (shown.lvl and keys[shown.lvl]) then
            shown.lvl = PickKey(keys, TargetKey()) or levels[1]
        end
        local minRuns = KeyParseDB.settings.minRuns
        f.keysTitle:SetShown(keys ~= nil)
        for i, b in ipairs(f.keyRows) do
            local k = levels[i]
            b.lvl = k
            if k then
                local n, avg = keys[k][1], keys[k][2]
                local dim = n < minRuns and "|cff888888" or "|cffffffff"
                b.label:SetText(format("%s+%d|r   |cff%s%.1f|r   %s%d|r%s", dim, k, ParseColor(avg), avg, dim, n,
                    k == shown.lvl and "  |cffffd100<|r" or ""))
            end
            b:SetShown(k ~= nil)
        end

        -- the selected key's dungeons
        local entry = keys and shown.lvl and keys[shown.lvl]
        local dungeons = Dungeons()
        local timed, ran = 0, 0
        for i, row in ipairs(f.dungeonRows) do
            local dg = entry and dungeons[i]
            local d = dg and entry.d and entry.d[dg[1]]
            row.name:SetText(dg and dg[2] or "")
            if d then
                ran = ran + 1
                row.avg:SetText(format("|cff%s%.1f|r", ParseColor(d[2]), d[2]))
                row.runs:SetText(format("|cffaaaaaa%d run%s|r", d[1], d[1] == 1 and "" or "s"))
                local timer = DungeonTimer(dg[1])
                if d[3] and timer then
                    local inTime = d[3] <= timer
                    timed = timed + (inTime and 1 or 0)
                    row.time:SetText(format("|cff%s%s|r |cff888888/ %s|r", inTime and "33ff99" or "ff5555", Clock(d[3]), Clock(timer)))
                elseif d[3] then
                    row.time:SetText("|cffaaaaaa" .. Clock(d[3]) .. "|r")
                else
                    row.time:SetText("")
                end
            else
                row.avg:SetText(dg and "|cff888888-|r" or "")
                row.runs:SetText(dg and "|cff888888no parses|r" or "")
                row.time:SetText("")
            end
        end
        if entry and not entry.d then
            f.dungeonTitle:SetText(format("+%d: no dungeon detail yet (Refresh)", shown.lvl))
        elseif entry then
            f.dungeonTitle:SetText(format("+%d dungeons   |cff888888fastest run, timed %d of %d|r", shown.lvl, timed, ran))
        else
            f.dungeonTitle:SetText("")
        end

        -- specs played (this role)
        local specs = p and p.specs and role and p.specs[role]
        if specs and next(specs) then
            local names = {}
            for spec in pairs(specs) do
                names[#names + 1] = spec
            end
            table.sort(names, function(a, b) return specs[a] > specs[b] end)
            for i, spec in ipairs(names) do
                names[i] = format("%s |cffaaaaaa%d|r", spec, specs[spec])
            end
            f.specs:SetText("|cffffd100Specs played:|r " .. table.concat(names, ", "))
        else
            f.specs:SetText("")
        end

        -- played with you
        local h = full and History().players[full]
        for i, fs in ipairs(f.history) do
            fs:SetText("")
        end
        if h and (h.n or 0) > 0 then
            f.history[1]:SetText(format("|cffffd100Played with you:|r %d key%s, %d timed", h.n, h.n == 1 and "" or "s", h.timed or 0))
            local runs = h.runs or {}
            local line = 2
            for i = #runs, math.max(1, #runs - HISTORY_SHOWN + 1), -1 do
                local r = runs[i]
                f.history[line]:SetText(format("   +%d %s - %s, %s", r.lvl or 0, DungeonName(r.map),
                    r.timed and "|cff33ff99timed|r" or "|cffff5555depleted|r", AgoText(r.t)))
                line = line + 1
            end
        elseif full then
            f.history[1]:SetText("|cff888888No keys with you this season.|r")
        end
    end

    Show = function(full, result)
        searchFrame = searchFrame or CreateSearchFrame()
        if full ~= shown.full then
            shown.full, shown.role, shown.lvl = full, nil, nil
        end
        if full then
            searchFrame.box:SetText(full)
        end
        searchFrame:Show()
        RefreshSearch(result)
    end

    -- /kp search [name]: no name = just open the window.
    local function OpenSearchNow(text)
        if text and text:match("%S") then
            DoSearch(text)
        else
            Show(shown.full or SearchDB().recent[1])
        end
    end

    -- After a reload started by a search: open the window on that player again.
    local function ReopenAfterReload()
        local db = SearchDB()
        local r = db.reopen
        db.reopen = nil
        if type(r) == "table" and r.full and r.at and time() - r.at < REOPEN_FOR then
            Show(r.full)
        end
    end

    -- stillLoading: more data slots are coming (keep saying "Fetching").
    local function Refresh(stillLoading)
        if not stillLoading then
            fetching = false
        end
        RefreshSearch()
    end

    return { Open = OpenSearchNow, Refresh = Refresh, Reopen = ReopenAfterReload }
end)()

-------------------------------------------------------------------- settings panel
-- Esc > Options > AddOns > KeyParse. Every setting lives in KeyParseDB.settings (same values the /kp
-- commands change). Proxy settings, so changing one can redraw what it affects right away.

local settingsCategory

local function RegisterSettingsPanel()
    if settingsCategory or not Settings or not Settings.RegisterVerticalLayoutCategory then
        return
    end
    local s = KeyParseDB.settings
    local category, layout = Settings.RegisterVerticalLayoutCategory("KeyParse")

    local function Header(text)
        if layout and CreateSettingsListSectionHeaderInitializer then
            layout:AddInitializer(CreateSettingsListSectionHeaderInitializer(text))
        end
    end
    local function Redraw()
        if RefreshApplicantLabels then
            RefreshApplicantLabels()
        end
    end
    -- get/set default to KeyParseDB.settings[key]; after() runs when the value changes
    local function Proxy(key, varType, name, default, get, set, after)
        return Settings.RegisterProxySetting(category, "KeyParse_" .. key, varType, name, default,
            get or function() return s[key] end,
            function(v)
                if set then set(v) else s[key] = v end
                if after then after() end
            end)
    end
    local function Checkbox(key, name, tooltip, after)
        Settings.CreateCheckbox(category, Proxy(key, Settings.VarType.Boolean, name, DEFAULT_SETTINGS[key], nil, nil, after),
            tooltip)
    end
    local function Slider(key, name, tooltip, min, max, default, get, set, label, after)
        local options = Settings.CreateSliderOptions(min, max, 1)
        if options.SetLabelFormatter and MinimalSliderWithSteppersMixin then
            options:SetLabelFormatter(MinimalSliderWithSteppersMixin.Label.Right, label or function(v) return tostring(v) end)
        end
        Settings.CreateSlider(category, Proxy(key, Settings.VarType.Number, name, default, get, set, after), options, tooltip)
    end

    Header("Parses")
    Slider("targetKey", "Key you're pushing",
        "Show each player's average on the keys below this one (e.g. 16 = their +15s). Auto = your listing's +N, "
            .. "or each player's highest key with enough runs.", 0, 30, 0,
        function() return s.targetKey or 0 end,
        function(v) s.targetKey = (v >= 2) and v or nil end,
        function(v) return v >= 2 and ("+" .. v) or "Auto" end, Redraw)
    Slider("minRuns", "Runs needed per average", "An average from fewer runs gets a red * (low sample).",
        1, 10, DEFAULT_SETTINGS.minRuns, nil, nil, nil, Redraw)
    Checkbox("showInCombat", "Show parses in combat", "Add KeyParse lines to player tooltips while you're in combat.")

    Header("Group Finder")
    Checkbox("wideGroupFinder", "Parse column", "Widen the Group Finder and show applicants' parses in their own column.",
        function() ApplyWidth() Redraw() end)
    Checkbox("sortApplicants", "Sort applicants by parse",
        "Healers first, then best parse first, then no logs. Takes effect the next time the list updates.")
    Checkbox("showChecklist", "Group checklist (Lust / Brez)",
        "Show Lust/Brez on your listing and +BL/+BR on applicants who'd fill a gap.", Redraw)
    Checkbox("autoQueueApplicants", "Look up applicants automatically", "Queue everyone who applies to your group.")
    Checkbox("reloadOnLookup", "Reload right after Get M+ parses", "Fetch right away instead of waiting for your next reload.")
    Checkbox("reopenGroupFinder", "Reopen Group Finder after a fetch", "Bring back the Group Finder after the reload.")
    Checkbox("pinParsedGroup", "Pin the parsed group", "Keep the group you parsed at the top of the search list for 15 min.")

    Header("Strong and weak applicants")
    Checkbox("alertStrong", "Alert after a fetch",
        "One chat line and a taskbar flash after the reload that fetched parses, when an applicant is strong.")
    Checkbox("strongIcon", "Star on strong applicants", "A star in front of their parse, and a line in their tooltip.", Redraw)
    Slider("strongParse", "Strong parse", "Strong = the number on their row is this or higher: the average of all "
        .. "their runs from 2 keys below yours up to your key (listing +18: +16 to +18).", 50, 99, DEFAULT_SETTINGS.strongParse,
        nil, nil, function(v) return v .. "+" end, Redraw)
    Checkbox("weakIcon", "Skull on weak applicants",
        "A skull in front of their number when it's below 25 (grey on Warcraft Logs). Only for keys up to +19.", Redraw)

    Header("Tooltips and chat")
    Checkbox("showHistory", "Played-with history", "Show the keys you ran with a player in their tooltip.")
    Checkbox("quietChat", "Quiet chat",
        "Skip info-only chat lines (sorting note, Fetching N players, Parses updated, key remembered). Warnings still show.")

    Header("Testing")
    if layout and CreateSettingsButtonInitializer then -- own pcall: a failure here mustn't cost the whole panel
        pcall(function()
            layout:AddInitializer(CreateSettingsButtonInitializer("Test queue", "Open test queue", OpenTestQueue,
                "Fake applicants in KeyParse's own window, to try the Parse column, icons and tooltips without real "
                    .. "applicants. Never looked up or saved. Same as /kp test.", true))
        end)
    end

    Settings.RegisterAddOnCategory(category)
    settingsCategory = category
end

local function OpenSettings()
    if settingsCategory and Settings.OpenToCategory then
        Settings.OpenToCategory(settingsCategory:GetID())
    else
        Print("the options panel isn't available; use the /kp commands.")
    end
end

-------------------------------------------------------------------- slash commands

local function ShowHelp()
    Print("commands:")
    print("  |cffffff00/kp options|r - open the KeyParse options (also Esc > Options > AddOns)")
    print("  |cffffff00/kp key 16|r - you're pushing +16: show each player's average on the keys below it")
    print("  |cffffff00/kp key auto|r - use your listing's +N, or each player's highest key with enough runs")
    print("  |cffffff00/kp min 3|r - runs needed before an average counts (now " .. KeyParseDB.settings.minRuns .. ")")
    print("  |cffffff00/kp auto on/off|r - auto-queue people who apply to your group (now "
        .. (KeyParseDB.settings.autoQueueApplicants and "on" or "off") .. ")")
    print("  |cffffff00/kp wide on/off|r - wider Group Finder with a Parse column (now "
        .. (KeyParseDB.settings.wideGroupFinder and "on" or "off") .. ")")
    print("  |cffffff00/kp autoreload on/off|r - reload right after Get M+ parses (now "
        .. (KeyParseDB.settings.reloadOnLookup and "on" or "off") .. ")")
    print("  |cffffff00/kp group|r - queue everyone in your party/raid")
    print("  |cffffff00/kp applicants|r - queue everyone applying to your group")
    print("  |cffffff00/kp fetch|r - reload to fetch everything queued")
    print("  |cffffff00/kp reopen on/off|r - reopen the Group Finder after a fetch (now "
        .. (KeyParseDB.settings.reopenGroupFinder and "on" or "off") .. ")")
    print("  |cffffff00/kp pin on/off|r - pin the group you parsed to the top of the search list (now "
        .. (KeyParseDB.settings.pinParsedGroup and "on" or "off") .. ")")
    print("  |cffffff00/kp sort on/off|r - sort people applying to your group by parse (now "
        .. (KeyParseDB.settings.sortApplicants and "on" or "off") .. ")")
    print("  |cffffff00/kp status|r - data age and pending lookups")
    print("  |cffffff00/kp search Name-Realm|r - a player's parses per key and dungeon, timed runs, specs (one reload to fetch)")
    print("  |cffffff00/kp test|r - test queue: fake applicants to try KeyParse on (never looked up or saved)")
    print("  Hold |cffffff00Shift|r on a tooltip to see every key level.")
end

SLASH_KEYPARSE1 = "/kp"
SLASH_KEYPARSE2 = "/keyparse"
SlashCmdList.KEYPARSE = function(msg)
    local cmd, arg = (msg or ""):lower():match("^%s*(%S*)%s*(.-)%s*$")
    local s = KeyParseDB.settings
    if cmd == "key" then
        local n = tonumber(arg)
        s.targetKey = (n and n >= 2) and n or nil
        Print(s.targetKey and format("Pushing +%d: showing averages from +%d and below.", s.targetKey, s.targetKey - 1)
            or "Auto: using your listing's +N, or each player's highest key with enough runs.")
        RefreshApplicantLabels()
    elseif cmd == "min" then
        local n = tonumber(arg)
        if n and n >= 1 then
            s.minRuns = math.floor(n)
        end
        Print("Minimum runs per average: " .. s.minRuns)
        RefreshApplicantLabels()
    elseif cmd == "auto" then
        s.autoQueueApplicants = arg ~= "off"
        Print("Auto-queue applicants: " .. (s.autoQueueApplicants and "on" or "off"))
    elseif cmd == "group" then
        Print(format("Queued %d group members. /reload to fetch.", QueueGroup()))
    elseif cmd == "applicants" then
        Print(format("Queued %d applicants. /reload to fetch.", QueueApplicants(false)))
    elseif cmd == "fetch" then
        FetchAndReload()
    elseif cmd == "wide" then
        s.wideGroupFinder = arg ~= "off"
        Print("Wider Group Finder with a Parse column: " .. (s.wideGroupFinder and "on" or "off"))
        ApplyWidth()
    elseif cmd == "autoreload" then
        s.reloadOnLookup = arg ~= "off"
        Print("Reload right after Get M+ parses: " .. (s.reloadOnLookup and "on" or "off"))
    elseif cmd == "reopen" then
        s.reopenGroupFinder = arg ~= "off"
        Print("Reopen Group Finder after fetching: " .. (s.reopenGroupFinder and "on" or "off"))
    elseif cmd == "sort" then
        s.sortApplicants = arg ~= "off"
        Print("Sort applicants by parse: " .. (s.sortApplicants and "on" or "off")
            .. " (takes effect the next time the applicant list updates)")
    elseif cmd == "pin" then
        s.pinParsedGroup = arg ~= "off"
        Print("Pin the parsed group to the top of the search list: " .. (s.pinParsedGroup and "on" or "off"))
    elseif cmd == "search" or cmd == "s" then
        PlayerSearch.Open((msg or ""):match("^%s*%S+%s*(.-)%s*$")) -- the name as typed (cmd/arg are lowercased)
    elseif cmd == "test" then
        OpenTestQueue()
    elseif cmd == "options" or cmd == "config" or cmd == "settings" then
        OpenSettings()
    elseif cmd == "status" then
        local gen = KeyParse_Data.generated or 0
        local target = TargetKey()
        Print(format("%d players in data (%s), %d lookups pending. Mode: %s, min runs %d.",
            CountKeys(KeyParse_Data.players), gen > 0 and date("%b %d %H:%M", gen) or "never updated",
            PendingCount(), target and ("pushing +" .. target) or "auto", s.minRuns))
        print("  " .. (PointsText() or "WCL points: unknown until the companion has looked someone up")
            .. " |cff808080(Warcraft Logs also has an unreported database limit; it clears within minutes)|r")
        if CompanionProblem() then
            print("  |cffff5555Companion: " .. CompanionProblem() .. "|r")
        end
    else
        ShowHelp()
    end
end

-------------------------------------------------------------------- startup

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")
frame:SetScript("OnEvent", function(_, event, arg1)
    if event == "ADDON_LOADED" and arg1 == ADDON_NAME then
        KeyParseDB = KeyParseDB or {}
        KeyParseDB.requests = KeyParseDB.requests or {}
        KeyParseDB.fromApplicants = KeyParseDB.fromApplicants or {}
        KeyParseDB.settings = KeyParseDB.settings or {}
        for k, v in pairs(DEFAULT_SETTINGS) do
            if KeyParseDB.settings[k] == nil then
                KeyParseDB.settings[k] = v
            end
        end
        -- 0.11.1: the strong default went from 90 (one key level) to 80 (the row's range average)
        if not KeyParseDB.settings.strongRangeAvg then
            KeyParseDB.settings.strongRangeAvg = true
            if KeyParseDB.settings.strongParse == 90 then
                KeyParseDB.settings.strongParse = 80
            end
        end
    elseif event == "ADDON_LOADED" and arg1 == "Blizzard_GroupFinder" then
        HookGroupFinder()
    elseif event == "PLAYER_LOGIN" then
        KeyParseDB.region = REGION_KEYS[GetCurrentRegion()] or "us"
        TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Unit, OnUnitTooltip)
        if Menu and Menu.GetManager then
            local manager = Menu.GetManager()
            hooksecurefunc(manager, "OpenMenu", InitMenus)
            hooksecurefunc(manager, "OpenContextMenu", InitMenus)
        end
        HookGroupFinder()
        local okPanel, panelErr = pcall(RegisterSettingsPanel)
        if not okPanel then
            Print("couldn't add the options panel (" .. tostring(panelErr) .. "); the /kp commands still work.")
        end
        frame:RegisterEvent("LFG_LIST_APPLICANT_LIST_UPDATED")
        frame:RegisterEvent("LFG_LIST_ACTIVE_ENTRY_UPDATE") -- you listed, edited or delisted a group
        frame:RegisterEvent("LFG_LIST_APPLICANT_UPDATED")
        frame:RegisterEvent("PLAYER_REGEN_DISABLED")
        frame:RegisterEvent("PLAYER_REGEN_ENABLED")
        frame:RegisterEvent("GROUP_ROSTER_UPDATE") -- someone joined/left: group checklist + row tags
        frame:RegisterEvent("CHALLENGE_MODE_COMPLETED") -- a key finished: played-with history
        local quiet = KeyParseDB.settings.quietChat -- skip the info-only lines; warnings still show
        if KeyParseDB.settings.sortApplicants and not quiet then
            Print("applicants to your group are sorted: healers first, then best parse first, then no logs. "
                .. "|cffff9933!|r = new to your key level or applied on a spec without logs (hover for details). "
                .. "|cff888888/kp sort off|r")
        end
        local pending = PendingCount()
        if pending > 0 and not quiet then
            Print(format("Fetching %d player%s...", pending, pending == 1 and "" or "s"))
        end
        C_Timer.After(pending > 0 and SLOT_DELAYS[1] or 0, LoadNextSlot)
        local reopenAt, ret = KeyParseDB.reopenAt, KeyParseDB.returnTo
        KeyParseDB.reopenAt, KeyParseDB.returnTo = nil, nil
        if reopenAt and time() - reopenAt < RETURN_WINDOW then
            if type(ret) == "table" and ret.at and time() - ret.at < RETURN_WINDOW then
                returnState = ret
                returnState.untilTime = time() + RETURN_FOR
            end
            C_Timer.After(1, ReopenGroupFinder)
            C_Timer.After(3, ReopenGroupFinder) -- second try in case the UI closed it while starting up
            C_Timer.After(5, CheckReopened)
        end
        C_Timer.After(1, PlayerSearch.Reopen) -- a search's reload: show that player again
    elseif event == "LFG_LIST_APPLICANT_LIST_UPDATED" or event == "LFG_LIST_APPLICANT_UPDATED" then
        OnApplicantsChanged()
    elseif event == "PLAYER_REGEN_DISABLED" then
        -- hide the secure back-to-search button while it still can be (fires just before combat lockdown)
        if returnButton and returnButton:IsShown() then
            returnButton:Hide()
        end
    elseif event == "PLAYER_REGEN_ENABLED" then
        UpdateReturnButton()
    elseif event == "CHALLENGE_MODE_COMPLETED" then
        local n = RecordCompletedKey()
        if n > 0 and not KeyParseDB.settings.quietChat then
            Print(format("remembered this key with %d player%s (shown in their tooltips).", n, n == 1 and "" or "s"))
        end
    elseif event == "GROUP_ROSTER_UPDATE" then
        local viewer = LFGListFrame and LFGListFrame.ApplicationViewer
        if viewer and viewer:IsShown() then
            RefreshApplicantLabels()
        end
    elseif event == "LFG_LIST_ACTIVE_ENTRY_UPDATE" then
        DropOldApplicantRequests()
        UpdateFetchButton()
    end
end)
