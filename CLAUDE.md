# KeyParse — project notes for Claude

> **Rule: update this file after every change** (new feature, fix, version bump, setting, Blizzard/WCL
> rule learned, test count). Keep "Current state" and "Pending" accurate. Keep it short: it is loaded
> into every chat, so every line here costs tokens each session.

## What it is
WoW (Midnight, 12.x) addon by Taftonator-Dalaran (US, Ret Paladin). Shows other players' average
Warcraft Logs M+ DPS parses at a key level (e.g. their +15s when pushing a +16) on Group Finder
applicants, tooltips and right-click menus. Goal: share with friends, then CurseForge.
Blanket permission to do whatever is needed in the repo and the installed AddOns folder; walk the
user through anything they must do themselves.

## How it works
- Addons can't use the internet or read files mid-session, so a Python companion (user's own WCL API
  key) does lookups. Addon queues "Name-Realm" in SavedVariables (`KeyParseDB.requests`) -> /reload ->
  companion watches `WTF\...\SavedVariables`, queries WCL v2 GraphQL (encounterRankings, metric dps,
  byBracket: true, zone 55 "Mythic+ Season 2") -> writes load-on-demand addons KeyParse_Data1-3 ->
  addon loads them at 1s/5s/12s after login. One reload total.
- WCL limits: 1000 pts/hr (reported via rateLimitData), ~10 pts per player. Separately, errors
  "no database points remaining": NOT hourly and NOT a per-user count (companion_log Nov 17: hit after
  ~10 lookups, cleared in ~5 min; Nov 18: ~40 lookups/hr, never hit). Looks like WCL server load.
  Companion re-checks every 2 min; addon says "WCL busy (database limit), retrying every 2 min".
  Don't build a lookups-left estimate for it (can't be predicted).
- WCL terms: no permanent copies -> results deleted after 24h (re-queued after 20h).
- Midnight "secret values": names checked with `IsSafe()` and resolved via GUID.

## Files
- Repo: `C:\Users\tafto\GIT\ParseAddon\` = git repo (branch main) for github.com/taftonator/KeyParse (public; Pages
  serves repo-root `privacy.html` = copy of `store\privacy.html`, keep both identical). Local main was based on the
  GitHub history (README + privacy.html) so the first push is a normal push. `.gitattributes`: LF everywhere,
  `.bat` CRLF on disk (cmd needs it).
  - `addon\KeyParse\KeyParse.lua` (~3770 lines), sections (search for the `----...---- <name>` banners):
    helpers, tooltip lines, played-with history, lookup queue, loading data slots, right-click menus, Group Finder,
    back to your search after a reload (return button, pin, search hint), test queue, player search, settings panel, slash commands, startup.
    **Main chunk is at Lua's 200-local limit**: put new sections inside a function scope like the test queue
    (`local X = (function() ... return X end)()`); a `do` block does NOT help (its locals still count).
  - `addon\KeyParse\media\icon.tga` (64x64, hexagon cropped from repo-root `logo.png`) = IconTexture of
    all four .toc files; `media\logo.tga` (256x256 full logo). build_release ships each folder's
    `media` folder (not listed in .tocs) and fails if an IconTexture points at a missing texture.
  - `addon\KeyParse_Data1..3\Data.lua`: placeholders in the repo; the installed copies hold live
    companion output, so they differ from the repo on purpose.
  - `companion\companion.py` (+ "Start KeyParse Companion.bat", "Start with Windows - ON/OFF.bat",
    `build_exe.bat` -> `dist\KeyParseCompanion.exe`). Window (0.6.17): `companion\companion_ui.py` (pywebview + pystray) +
    `companion\ui\index.html` (page, all CSS/JS inline) + `ui\hex.png`; `companion\lastkey.py` (combat log reader). Deps in `companion\requirements.txt`.
  - `store\`: `build_store.py` (Store MSIX: onedir exe, logos, manifest, PRI, pack; `--skip-exe` reuses the exe),
    `AppxManifest.template.xml`, `identity.json` (Partner Center values; not secret), `privacy.html`,
    `make_store_art.py` (redraws logo.png sharp, Verdana Bold, -> `listing\` Box/Poster art), `listing\listing.md` (Store text).
    Output `store\build\layout\` (local test) and `store\out\*.msix` (only packed when identity.json is filled in).
  - `build_release.py/.bat` -> `release\*.zip`; README.md, CURSEFORGE.md, INSTALL.md, CHANGELOG.md,
    LICENSE (MIT), API_FINDINGS.md
  - `tests\harness.py` + `tests\edge_tests.py`: run `python tests\edge_tests.py` (needs `pip install lupa`).
    Real KeyParse.lua runs against stubbed WoW APIs; companion against a fake WCL. 55 tests, all pass. Test 43 stubs Blizzard Settings (SETTINGS_STUB).
    Stub frames return a no-op FUNCTION for any unknown field (check `type(x) == "table"`, not truthiness). `UIParent` is a
    stub frame; menu stub has CreateCheckbox (LASTBTN[text] = setter). Test 45 only dry-runs ("Wrote release\...zip" is printed, nothing written).
    Applicant stub entries are `{ name, role, specID, classFile }`; PARTY/SELF [4] = class (UnitClass).
    `hooksecurefunc("Name", fn)` hooks are captured in `GHOOKS[Name]`; `FakeWCL.spent` sets points used.
    The search hint is one fontstring (`SEARCHPANEL._label`), the points line is a 2nd line in it.
- Installed: `C:\Program Files (x86)\World of Warcraft\_retail_\Interface\AddOns\KeyParse` (+ Data1..3)

## Rules
- NEVER share/commit `config.json` (API secret) or `cache.json` (now in %LOCALAPPDATA%\KeyParse; older copies may sit in companion\). Release zips: no exes, no data.
- After every change: copy to the installed AddOns folder and md5-check repo vs installed
  (all files except Data.lua must match).
- After editing companion.py the user must close and restart the companion window.
- Don't rebuild release zips until the user says. `build_release.py` takes NO flags: running it at all
  builds (it overwrote the old 0.6.1 zips once by accident). Test 45 dry-runs it with a fake ZipFile.
  `release\KeyParse-0.6.16.zip` rebuilt 2026-11-19 on the user's OK (10 files, md5 = repo = installed; Data.lua placeholders).
  It still also writes a KeyParseCompanion zip when companion\dist has the exe: ignore it (companion is Store-only).
- **Versioning (user's rule):** never near 1.0. Current is 0.6.1 (reset from 0.11.2; 0.7.0-0.11.2 below
  were dev builds). Each update / batch of work done together: +0.0.01 -> 0.6.11, 0.6.12, 0.6.13, ...
  Set `## Version` in ALL FOUR .toc files (KeyParse + Data1-3; build_release.py needs them equal) and add
  a CHANGELOG entry. Add a test for each new behaviour.
- Pre-release: rebuild release zip before upload (only when the user says). Companion exe/zip no longer shipped (Store).
- Files use LF line endings. Python `write_text` on Windows writes CRLF: use `write_bytes`/`newline="\n"`.
  Lua tests run on lupa (Lua 5.4): `format("%x")` needs integers (math.floor), unlike WoW's Lua 5.1.
- End each reply with exactly one bolded next step for the user.
- Say plainly when something can't be done because of Blizzard/WCL rules instead of faking it.

## Blizzard constraints learned (don't re-try)
- `C_LFGList.Search` has HasRestrictions: addons can't start a search (taint popup).
- Don't write Blizzard LFGListFrame fields from addon code (taints the search path). Reading is fine.
- Don't set the search selection (`selectedResult`) from addon code (could block Sign Up).
- Blizzard_GroupFinder is not load-on-demand in this client.
- Search box is `securityDisableSetText` and the search reads it directly: addons/macros can't fill
  in or re-run "15-15". User must type it + Enter.
- Scrolling the search list from addon code would taint the rows Sign Up reads. Scroll-bar steppers
  only react to OnMouseDown, so a secure `/click` on them does nothing.
- Works: secure macro button `/click` proxies (type=click, useOnKeyDown=false) on Blizzard's category
  and Find Group buttons; post-hooking `LFGListUtil_SortSearchResults` to reorder `panel.results`
  (pin and Sign Up on a pinned group both confirmed in game).
- `C_LFGList.GetSearchResultPlayerInfo` names have no realm -> only listing leaders (info.leaderName has
  the realm) can be looked up. partyGUID is NeverSecret (used to match listings).
- Blizzard UI source for checking: github.com/Gethe/wow-ui-source (branch `live`), e.g.
  `Interface/AddOns/Blizzard_GroupFinder/Mainline/LFGList.lua`.

## Current state: v0.6.19 (repo + sent to GitHub 2026-11-20 with the user's OK; tested by the user in the build-folder copy; Store upload of 0.6.19.0 pending; installed addon = CurseForge copy during the new-user test; version labels below are dev builds)
- Applicants: Parse column in Group Finder (wide mode) with ▼ (key levels -> 8 dungeons); auto-queue +
  "KeyParse: fetch N (reload)" button; Group Finder reopens after the reload.
- Right-click any player: "Get M+ parses" (queues + auto-reloads, not in combat); tooltips (Shift = all keys).
- Party (not raid): right-click your own character -> "Show group parses" (cost note removed in 0.7.5) -> after reload
  submenu members -> keys -> dungeons.
- Search listings: right-click a group -> "Show leader parse"; ▼ on the listing after reload.
- Healers are never looked up (shown as "healer"); companion drops healer-spec runs, no HPS query.
  Gap: "Get M+ parses" on a stranger with unknown role still costs a lookup.
- After a reload from the search list: secure "KeyParse: back to your Dungeons search" button
  (tested in game, works), "type 18-18 + Enter" hint, parsed group highlighted and **pinned to the
  top** of results (0.7.3, `/kp pin on/off`, tested in game, works). Lasts 15 min.
- WCL points left (0.7.4, not tested in game): companion records rateLimitData (`POINTS`, `note_points`,
  kept in cache.json) and writes `points = { spent, limit, reset }` into the data slots. Addon
  `PointsText()` shows it in the search list (2nd line under a KeyParse hint, else "KeyParse: WCL
  points: 688/1000 (resets in 23 min)"), after "Parses updated.", and in /kp status. Color fades vibrant
  green -> grey as points run out; grey "WCL busy (database limit), retrying every 2 min" (0.10.1).
  Only as fresh as the last reload. 0.7.5: also on your own listing, top-right of the dungeon picture
  (`UpdateViewerPoints`, called from RefreshApplicantLabels).
- Other addons: Raider.IO's `RaiderIO_ExportButton` (16px round, parent LFGListFrame, own anchor
  BOTTOMRIGHT at LFGListFrame BOTTOM -12,7) overlapped Delist. `PlaceRaiderIOButton` moves it right of
  `viewer.RemoveEntryButton` on viewer OnShow and restores it on OnHide. Raider.IO source is in AddOns\RaiderIO.
  Confirmed in game 2026-11-19: sits right of Delist, clear of Edit. Decided: keep moving Raider.IO's icon, NOT Blizzard's Delist (Blizzard re-anchors Delist on every
  listing update in LFGListApplicationViewer_UpdateInfo, and the bottom row has little room).
- 0.8.0 (Tier 1, tested in game: Parse column, tooltip, Invite/Decline on the sorted list all work): applicant label `<listed dungeon>/<overall> +15` (`ListingDungeon`
  matches the listing's activity mapID/fullName to WCL dungeon names via `NormName`); orange `!` from
  `Experience` (no runs at >= target key = "new"; runs but none timed = "untimed", fastest time vs
  `C_ChallengeMode.GetMapUIInfo` timer) or `SpecMismatch` (applied spec from GetApplicantMemberInfo's
  16th return, specID -> GetSpecializationInfoByID, vs `p.specs[role]`); tooltip explains each. Applicants
  sorted (`SortApplicantsByParse`, post-hook of LFGListUtil_SortApplicants): healers first, best parse,
  then no logs; chat note every reload; `/kp sort on/off`. Companion data: dungeon entries are
  `{ runs, avg, fastestSeconds }`, plus `specs = { dps = { ["Fire"] = n } }`. DATA_VERSION kept at 2
  on purpose (bumping it re-fetches every cached player = points); old entries just lack the new fields.
- 0.9.0 (Tier 2 #1, tested in game 2026-11-19): group checklist. User chose: Lust + Brez only, short coloured
  text, from your current group only, plus `+BL`/`+BR` (green, prepended to the label) on applicants who'd
  fill a gap + tooltip line. `GroupHas` (UnitClass of player/party1..4, not in raid), `FillsTag`,
  `UpdateGroupChecklist` (frame `KeyParseGroupChecklist`, hidden in raids). Called from
  RefreshApplicantLabels; GROUP_ROSTER_UPDATE refreshes while the viewer shows. ApplicantMember also
  returns the class file (2nd return).
- 0.9.1: user wants KeyParse notices and WCL points kept separate. Own listing top-right is a
  right-aligned stack built in `UpdateViewerPoints` (runs after UpdateGroupChecklist): checklist >
  `viewerNotice` ("KeyParse: N lookups waiting", from PendingCount) > `viewerPoints` (plain "WCL points:
  ...", no KeyParse prefix). Hidden lines collapse. Was next to the title: would clip into longer titles.
- 0.9.2: search list points line alone is plain "WCL points: ..." too (no "KeyParse:"). Rule: WCL points
  are never shown as a KeyParse notice (chat lines are fine: all KeyParse chat is prefixed anyway).
- 0.10.0 (Tier 2 #2, tested in game 2026-11-20: works): played-with history. User chose: finished keys only (timed/
  depleted, no abandoned), tooltip only (no row marker), cleared each season, shown on applicant +
  mouseover + search-leader tooltips (all go through `AddLines` = `AddParseLines` + `AddHistoryLines`).
  CHALLENGE_MODE_COMPLETED -> `RecordCompletedKey` (C_ChallengeMode.GetChallengeCompletionInfo: members
  {memberGUID, name}, onTime, practiceRun skipped, dedupe by map:level:time) -> `KeyParseDB.history =
  { season, players = { [full] = { n, timed, runs = last 10 {t, map, lvl, timed} } } }`. `History()` clears
  when C_MythicPlus.GetCurrentSeason() (>0) differs. Chat line "remembered this key with N players".
- 0.11.0 (tested in game: works): **options panel** (Esc > Options > AddOns > KeyParse, `/kp options`;
  section "settings panel", `RegisterSettingsPanel` in pcall at PLAYER_LOGIN): Settings.RegisterProxySetting
  per key of KeyParseDB.settings (targetKey slider 0=Auto, minRuns, showInCombat, wide, sort, showChecklist,
  autoQueue, reloadOnLookup, reopen, pin, alertStrong, strongIcon, strongParse slider 50-99, showHistory,
  quietChat); setters redraw. New defaults: showChecklist/showHistory/alertStrong/strongIcon true,
  quietChat false. quietChat hides login sort note, "Fetching N", "remembered this key".
  Strong applicants: raid-star icon prepended to the row label + tooltip line; after a fetch ("Parses
  updated." branch of LoadNextSlot) `AlertStrongApplicants`: one chat line + FlashClientIcon, once per session.
- 0.11.1 (user's design): **applicant row = one number**, `RangeAvg` (after Summarize): run-weighted avg
  of ALL runs TargetKey-2..TargetKey inclusive (listing +18 -> +16,+17,+18), applied role (falls back to
  MainRole like Summarize). No target: PickKey level. "norange" = logs but no runs there -> grey "-".
  `ApplicantLabel` (rows only; LabelText unchanged for search list/menus): number + red * (runs <
  minRuns) + orange ! (Experience / SpecMismatch / other role). Tooltip "KeyParse row: N = avg of X DPS
  runs on +16 to +18". ApplicantScore (sorting) uses RangeAvg. **Strong** = RangeAvg >= strongParse
  (default 80), same role, runs >= minRuns, needs a target key. One-time migration: saved 90 -> 80
  (flag `settings.strongRangeAvg`). The 0.8.0 `<dungeon>/<overall> +15` row text is gone (tooltip keeps it).
- 0.11.2: **weak applicants** (user): `WeakParse` = RangeAvg < 25 (grey), same role, runs >= minRuns, only
  when TargetKey <= 19 ("anyone running 20s will be good"). Skull (UI-RaidTargetingIcon_8) prepended when
  not strong + tooltip line; setting `weakIcon` (default on, options panel). No alert.
- 0.6.11: **companion crash-proofing** (user asked before Store release). `watch` loop body in try/except
  Exception -> `log_exception` (traceback into companion_log.txt), backoff 15s*n (max 300). `AuthError`
  (PermanentError subclass, token 400/401): `process` keeps requests queued, retry in AUTH_RECHECK 300s,
  `PROBLEM["text"]` written to slots as `problem = "..."`; `refresh_credentials` re-reads config.json on
  each retry; cleared on the next good lookup. `replace_with_retry` for Data.lua/cache (PermissionError);
  write_data_lua skips a locked slot; cache save failure only logged. sv_mtime/read_requests ignore OSError.
  `__main__` logs startup failures and waits for Enter. Addon: `CompanionProblem()` -> chat once per login,
  red line in the listing's KeyParse notice, `/kp status`. Test 46.
- 0.6.12 (**Microsoft Store prep**, user verified a free individual Store account 2026-11-19): companion
  files now in `DATA_DIR` = %LOCALAPPDATA%\KeyParse (MSIX install dir is read-only; that folder gets
  virtualized into the package's LocalCache, transparent to the app). `migrate_old_files` moves
  config/cache/log from next to the program once, never overwriting. `is_packaged()` (kernel32
  GetCurrentPackageFullName != 15700): set_autostart/setup print STORE_STARTUP_HINT instead of writing the
  Startup-folder .bat. build_exe.bat no longer copies config.json. Test 47.
  **Store plan, not done yet:** MSIX (Store signs it; MSI/EXE route would need a paid cert). Needs: Windows
  SDK (MakeAppx not installed), PyInstaller onedir, AppxManifest with runFullTrust + StartupTask
  (windows.startupTask), Store logos from logo.png, identity values from Partner Center (reserved app
  name -> Product identity: Package/Identity/Name, Publisher CN=..., PublisherDisplayName), local test
  install (user enables Developer Mode; never change system/security settings ourselves), privacy policy
  URL, listing. Polish later: console window shows at login via StartupTask -> setup window / tray app.
- 0.6.13 (**Store package built**, test 48): `store\build_store.py` works end to end (layout 24 MB, exe smoke-tested,
  test pack with the local-test identity succeeded). Store name reserved: **"M+ KeyParse Companion"** (= manifest
  DisplayName, must match). MSIX version = toc version + ".0" (0.6.13 -> 0.6.13.0); every Store upload must be
  higher, so after 0.6.19 go to 0.6.20, never 0.6.2. makepri indexes only `Assets\` with no split scale packs.
  Packaged app's %LOCALAPPDATA%\KeyParse writes land in %LOCALAPPDATA%\Packages\<family>\LocalCache\Local\KeyParse.
- 0.6.14 (**test queue**, test 49, tested in game 2026-11-19: works): `/kp test` + options button ("Testing" header,
  CreateSettingsButtonInitializer). Section "test queue" = one function scope returning `OpenTestQueue`. Own frames
  `KeyParseTestQueue` / `KeyParseTestEditor` (BasicFrameTemplateWithInset; widgets on `f.body` above the Inset), docked
  TOPLEFT on LFGListFrame when visible, else screen centre. Fakes only in Lua (`testState`, gone on reload). Mechanism:
  file-level `local TEST`, set only inside `WithTest(fn)` (pcall, always restored): GetPlayer/TargetKey/GroupHas/
  History/DungeonTimer/ListingDungeon/DungeonName/Dungeons() read TEST (fake players built like companion data,
  dungeon "KeyParse Test Dungeon" timer 30 min), Summarize never says "queued", Queue() refuses. Shared with real rows:
  `RowText` (label+icons+tags), `AddApplicantLines` (tooltip), `MemberScore` + `SortByScore` (sort). Presets
  relative to "your key": strong/weak/new to key/wrong spec/too few runs/healer/no logs (names *-TestRealm).
- 0.6.15 (user asked, test 50, works in game): quietChat also hides "Parses updated." (LoadNextSlot); warnings + strong alert still show.
- 0.6.16 (user asked, test 51, tested in game 2026-11-19: works): **player search** `/kp search [Name-Realm]` (alias `/kp s`; name read
  from the raw msg, cmd/arg are lowercased). Section "player search": `PlayerSearch = { Open, Refresh, Reopen }` (forward-declared
  local near LoadNextSlot). Frame `KeyParseSearch` (620x470): search box, Recent list (KeyParseDB.search.recent, 10),
  key rows (click -> that key's dungeons: avg, runs, fastest vs DungeonTimer, "timed X of Y"), DPS/Tank buttons, specs
  line, played-with history (always shown here), Refresh/Get parses/Fetch now button, PointsText footer. `CanonicalName`
  capitalizes and matches realm case against yours + known names (no double lookups). Typed search fetches only if
  NeedsLookup (Queue + FetchAndReload, `KeyParseDB.search.reopen = {full, at}` -> reopened 1s after login if < 300s,
  says "Fetching..." until the last data slot); recent click never fetches. In combat: queue only. No options button
  (test 49's stub keeps one CreateSettingsButtonInitializer).
- 0.6.17 (**companion window, step 1**, test 52; user approved the purple design from an Edge-rendered mock-up 2026-11-20):
  pywebview (Edge WebView2, `gui="edgechromium"`, private_mode) shows `ui\index.html`; JS polls `JsApi.status()` every 2s.
  Data/logic are plain functions in companion.py section "window: status + setup" (`wow_folder_check`, `setup_info` (never
  sends the secret), `save_setup` (empty secret keeps the saved one, updates the shared cfg in place, sets `NUDGE`),
  `test_key` (token + rateLimitData query), `player_summary` (main role, run-weighted avg of top 3 key levels),
  `status_snapshot`, `STATUS`). `watch(..., stop=Event)`. `main()`: window unless `lookup|setup|autostart|--console`;
  passes `sys.modules[__name__]` (script runs as __main__!). `--tray` or exe name ending "Startup" = start hidden (manifest
  startupTask runs `KeyParseCompanionStartup.exe`, a copy made by build_store; startup tasks can't pass args).
  `--preview` = window only, no watcher/no single-instance (use it while the Store copy runs: auto mode refused stopping
  the user's Store app). Single instance: port 47613 now listens; a 2nd copy sends "show"; if the
  holder doesn't listen (old console companion, e.g. Store 0.6.13) -> message box "close the black window first". Close = hide to tray (notify
  once); tray: Open (default), status line, Quit. Dark title bar via DwmSetWindowAttribute. Tested: real data in preview,
  packed exe opens (KeyParse icon), Startup exe stays hidden, 2nd copy shows the first. User ran the layout exe 2026-11-20: window
  + real watcher started, tray Quit works. Points ring glow: SVG viewBox -10 -10 120 120 (+ #glow filter) so the glow isn't
  clipped square. Not tested: Save/Browse/Test key clicked (functions tested), a lookup through the window, packaged
  (MSIX) install. Screenshots: shot.py must pick the window by exe (user's copy may share the title). Windows hides new tray icons in the ^ overflow until the user drags them out.
- 0.6.18 (**Last key page = companion window step 2**, tests 53-54; user asked to build it after step 1 worked in game
  2026-11-20): `lastkey.py`: `find_last_start` (reads the log backwards in 8 MB chunks), `read_key` (forward to the
  non-empty CHALLENGE_MODE_END), `last_key` (newest of the 3 newest `Logs\WoWCombatLog*.txt`; finished key cached in
  DATA_DIR\lastkey.json), `timed_from_history` (addon history run with same map (challengeModeID) + lvl, t within 15 min;
  `companion.addon_history` reads it from SavedVariables). Log v22 format: fields after "date time-tz  "; spell events have
  3 spell fields, swings none; then 19 advanced fields (info GUID, owner GUID, ...), amount = field 28+3 / 28, overkill +2;
  heal overheal +2. COMBATANT_INFO spec = field 25. CHALLENGE_MODE_START: name, instance, challengeModeID, level, [affixes];
  END: instance, success, level, ms, score?, rating? (only ms/success used). Damage: *_DAMAGE minus overkill, not
  *_LANDED; pets -> owner via SPELL_SUMMON or advanced owner GUID. "You" = COMBATANT player with flags & 0x1. Real log:
  Murder Row +16 (206 MB file) read in ~5 s. JsApi.last_key(force) reads in a thread (state reading/ready/none/error),
  JS polls 0.7 s. Also: `wow_running()` (Toolhelp32 process list, Wow/WowT/WowB.exe, cached 3 s) -> red "WoW isn't
  running" state (user's request; footer stays "Running"); Recent lookups show selectable "Name-Realm" + hover
  "Warcraft Logs ↗" (`wcl_character_url`, `JsApi.open_url` only opens warcraftlogs.com).
- 0.6.19 (test 55; from the new-user test 2026-11-20, user: "idiot proof"): Setup page `<details id="guide">` (shown
  only when no key saved; after Save `showGuide(false)` hides it and shows the 0.6.18 link + short line again, user's ask; `#guide-open` link reopens it, `show("setup")` re-hides it while `keySaved`): 5 steps, button -> warcraftlogs.com/api/clients, Copy buttons (`JsApi.copy_text` -> `companion_ui.set_clipboard`,
  ctypes CF_UNICODETEXT; tests mock it: never touch the real clipboard) for Name `M+ KeyParse Companion - looks up Mythic+
  parses for my WoW group finder` and `http://localhost`. `clean_key` (strip spaces/quotes), `key_problem` (empty, same code
  twice, swapped = secret has the client-ID shape 8-4-4-4-12 and the ID doesn't, inner whitespace) used by save_setup +
  test_key before any request; `key_hint` on AuthError. WCL facts (user's screenshots): client list shows name, Client ID,
  redirect URL, Edit/Delete; secret not in the list (INSTALL.md says shown only once; user didn't confirm via Edit yet).
  INSTALL.md rewritten for the window; CURSEFORGE.md + release html updated (not pasted into CurseForge yet).
- Slash: `/kp` or `/keyparse` options|key|min|auto|wide|reopen|autoreload|pin|sort|group|applicants|fetch|status|test|search

## Planned features (agreed, NOT built yet; user says when to start, may clarify first)
Tier 2: done (group checklist 0.9.0, played-with history 0.10.0).
Test queue: built in 0.6.14 (see Current state).
Backburner: coaching page (your weakest dungeons vs your average, season trend; ~10 points per self lookup).
Future: desktop dashboard from the companion.
**Companion window:** step 1 BUILT in 0.6.17, step 2 (Last key) BUILT in 0.6.18 (see Current state). Possible later:
past keys history (own data, may be kept all season), per-boss breakdown. Privacy policy line about the combat log: done 0.6.18. Then maybe desktop player search, coaching page.
Never share/pool WCL lookups between users (terms). User drives work from the phone (Remote Control on for all new
sessions): send screenshots with SendUserFile; WoW tests and Store submissions need the PC.
Dropped: crown xN for top DPS (needed a report query per run); Raider.IO/rating vs parse note (user
decided against it, don't re-propose).

## Pending / ideas
- **NEXT (Store):** (1) DONE: identity.json filled (Name taftonator.MKeyParseCompanion, Store ID 9NZ96JDM66PT,
  PFN ..._mfmz6hgt608aw); `store\out\KeyParseCompanion_0.6.13.0_x64.msix` packed (12.7 MB), not uploaded yet.
  (2) DONE 2026-11-19: local test (`Add-AppxPackage -Register store\build\layout\AppxManifest.xml`) starts and
  shows in Settings > Apps > Startup. 2026-11-20: test copy removed, real Store version installed (SignatureKind Store,
  runs from WindowsApps). It reuses the existing %LOCALAPPDATA%\KeyParse\config.json (real folder, not LocalCache), so
  it didn't ask for a key. First-run key prompt on a clean PC is untested with the Store build.
  (3) privacy.html contact = taftonator@gmail.com (user's choice, public). Hosting: user's GitHub, Pages from a
  public repo github.com/taftonator/KeyParse (web upload; user is new to GitHub). DONE, live:
  https://taftonator.github.io/KeyParse/privacy.html (repo holds only README + privacy.html). (4) DONE 2026-11-19: submission 1 filled in, all sections Complete (free, all markets, Utilities & tools,
  IARC 3+, Desktop only, listing text/art in store\listing\, runFullTrust reason <=400 chars written for non-gamers).
  PASSED certification 2026-11-19 (0.6.13.0 msix), publishing. 0.6.17 = first companion change since: build_store
  now --windowed + `--add-data companion\ui;ui` + Startup exe copy; `store\out\KeyParseCompanion_0.6.17.0_x64.msix`
  packed (26.8 MB), then 0.6.18.0 (26.8 MB, packed exe shows Last key OK), SUBMITTED 2026-11-20 as Submission 2 (0.6.18.0 replaced 0.6.13.0 under Packages; new listing text; not mandatory),
  waiting for certification. After it passes: user should quit the build-folder test copy and run the Store app. For the update: privacy.html (both copies) now lists lastkey.json + reading the
  combat log/SavedVariables locally (live since 2026-11-20); listing.md has new description, features,
  "What's new" text and a 367-char runFullTrust note (ask first; listing text may need a line about the new window). Future Store updates: bump version (MSIX version must go up), rebuild, new submission.
  Store link: https://apps.microsoft.com/detail/9NZ96JDM66PT (companion's Store files: %LOCALAPPDATA%\Packages  taftonator.MKeyParseCompanion_mfmz6hgt608aw\LocalCache\Local\KeyParse).
- **New-user test (2026-11-20, in progress):** Store 0.6.18.0 PASSED + auto-updated; addon live on CurseForge (0.6.16).
  User's own setup MOVED (not deleted) to `C:\Users\tafto\KeyParse-backup\` (not Desktop: OneDrive syncs it and
  config.json has the secret): `companion\` (= %LOCALAPPDATA%\KeyParse) and
  `SavedVariables\851325204#1\KeyParse.lua(.bak)` (settings + played-with history). Restore = move back (WoW + companion
  closed). Mistake: the user installed from CurseForge (14:39) BEFORE the move (14:42), so the move took CurseForge's
  0.6.16 copy; moved back the same day (= CurseForge files, fingerprints match). Lesson: check folder dates/versions
  before moving, and do the clean-up before the user installs anything. Uninstalling the Store app does NOT remove %LOCALAPPDATA%\KeyParse.
- **CurseForge (started 2026-11-19):** CURSEFORGE.md (the page text), README.md and INSTALL.md rewritten for 0.6.16 +
  the Store companion (no exe/GitHub-release companion any more). CURSEFORGE.md already links the GitHub repo. Zip
  rebuilt (0.6.16). CurseForge project CREATED 2026-11-19 as **"M+ KeyParse"** ("KeyParse" was taken; in-game name
  unchanged), MIT, 3rd-party distribution allowed. KeyParse-0.6.16.zip UPLOADED 2026-11-19 as Release (game 12.1.x),
  waiting for CurseForge moderation. CurseForge's description editor showed raw Markdown, so the description is
  pasted as formatted text from `release\CurseForge-description.html` (made from CURSEFORGE.md, not in git;
  regenerate it when CURSEFORGE.md changes with `python make_curseforge_html.py` (repo root, added 2026-11-20).
  2026-11-20: Requirements step 3 now walks through Create Client (descriptive name, http://localhost, Public unticked)
  after the new-user test showed the WCL form is confusing. Same guide is on the companion's Setup page + INSTALL.md (0.6.19).
- **Feedback form (2026-11-20, published):** Google Form "M+ KeyParse feedback" in the user's Drive, 7 questions, no
  email collected, anyone with the link: https://docs.google.com/forms/d/e/1FAIpQLSeNU-tufRSgHTKupklbQQ1YlSjCZ8FT9VCet0o5vWWukdsjIA/viewform
  Linked in CURSEFORGE.md ("Feedback" section + footer). Possible later: `/kp feedback` chat link (needs 0.6.17). After approval: change CHANGELOG "not released yet" headers; next uploads use
  the same project (new file, version +0.0.01, rebuild zip only when the user says).
- **GitHub (2026-11-19):** first commit made (repo-local identity taftonator <194296594+taftonator@users.noreply.github.com>;
  GitHub blocks pushes exposing the private email). PUSHED 2026-11-19 (origin/main = 1c5d112, privacy page still 200).
  Repo is public. gh not installed; Git Credential Manager has the login saved. Never push without asking.
  User is new to git: explain in plain words, no jargon ("send to GitHub" not "push to origin").
- Options panel: user tested several settings in game 2026-11-19, they work. Quiet chat hides "Parses updated." since
  0.6.15 (user's request).
- **Confirmed in game 2026-11-20 (user):** strong applicant star + chat line + taskbar flash (0.11.1), played-with
  history after a key (0.10.0), Show group parses in a party (0.7.2). Don't remind about these any more.
- 0.9.1 top-right stack confirmed in game 2026-11-19 (screenshot: "Lust x Brez v" over "WCL points: 975/1000 (resets
  in 41 min)", empty notice line collapsed, no overlap). +BL on a real applicant works (user). Update-on-join
  not tested; user accepts it as is (don't ask again).
- Not confirmed in game yet (low priority, don't block): Show leader parse menu, healer handling, weak skull (0.11.2).
- Options not built yet (possible later): colors, role marker, average vs best, refresh age (<=24h).

## Saving usage (when to start a new chat)
- A new chat costs Claude Code's built-in setup (cached) plus this file, plus re-reading code. Re-reading
  code is the expensive part, so use the section banners above to read only the relevant part.
- Stay in the same chat while working on one feature or fixing what was just built.
- Start a new chat when switching to an unrelated task (e.g. lookup counter, CurseForge) or after a long
  session with many file reads/test runs; long chats re-send all history every message.
- Don't start a new chat for every small question.
- `/explain-usage` shows where a chat's tokens went.
