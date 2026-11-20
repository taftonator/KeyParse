# KeyParse changelog

> **Version numbers reset to 0.6.1.** Everything listed below from 0.7.0 to 0.11.2 was a development build
> and now ships as 0.6.1. From here each update goes up by 0.0.01: 0.6.11, 0.6.12, 0.6.13, ...

## 0.6.16 (not released yet)
- **Player search** (`/kp search Name-Realm`, realm optional = yours; `/kp search` alone reopens the window): everything KeyParse knows about one player in its own window, so you don't need the Warcraft Logs site.
  - Every key level (avg, runs; dim = fewer runs than your minimum). Click one to see its dungeons: avg parse, runs, and fastest run vs the timer (green = timed, red = over), plus "timed X of Y".
  - Specs they've logged, DPS/Tank switch when they have both, and your played-with history with them.
  - Recent searches (last 10) on the left; click one to show it again. Refresh / Get parses button, WCL points at the bottom.
  - A player without fresh data is fetched with one reload (same as Get M+ parses); the window reopens on them after the reload. In combat it only queues. Names are matched to the same spelling as menus and applicants, so no double lookups.

## 0.6.15 (not released yet)
- **Quiet chat** now also hides "Parses updated." after a fetch. WCL points left are still in `/kp status` and on the Group Finder; warnings and the strong-applicant line still show.

## 0.6.14 (not released yet; not tested in game)
- **Test queue** (`/kp test`, or the "Open test queue" button at the bottom of the options panel): try the Parse column, star/skull, `*`, `!`, `+BL`/`+BR`, the tooltip and the sorting without waiting for real applicants.
  - KeyParse's own window, laid over the Premade Groups panel and drawn like the applicant list, clearly marked: "TEST - not real applicants" banner, "KeyParse test queue" title, a faint TEST watermark. It is not Blizzard's list (that can't hold fake applicants, and writing into it would break Invite/Decline).
  - Rows show name (class colour), role icon, ilvl, M+ rating and KeyParse's label, made by exactly the same code as real rows. Hover for the real tooltip (plus "TEST applicant - not real"), ▼ for every key level, click a row to edit it. Invite and Decline just remove the row.
  - "Your key +N" and "Your group" (classes) at the top drive the key range, the weak cut-off (+19) and +BL/+BR.
  - "Add fake applicant": name-realm, class, applied spec, role, spec and role their logs are on, ilvl, rating, no public logs, three key levels (avg parse, runs, timed), keys played with you (and how many timed).
  - Presets: strong, weak, new to key, wrong spec, too few runs, healer, no logs (or all of them).
  - Fake applicants are never looked up, never saved (gone after a reload), never written into your lookups, history or parse data, and never trigger the strong-applicant chat line or taskbar flash.

## 0.6.13 (not released yet)
- **Microsoft Store package of the companion** ("M+ KeyParse Companion"). `store\build_store.py` builds it: the companion as a folder app (PyInstaller onedir) with the KeyParse hexagon as its icon, Store logos, a manifest that starts it with Windows (switch it in Settings > Apps > Startup), and the `.msix` to upload (Partner Center identity in `store\identity.json`; first package: `KeyParseCompanion_0.6.13.0_x64.msix`).
- Privacy policy page for the Store listing: `store\privacy.html`.
- No addon or companion behaviour changes.

## 0.6.12 (not released yet)
- Companion keeps its files (API key, cache, log) in `%LOCALAPPDATA%\KeyParse` instead of next to the program, which the Microsoft Store version needs. Your existing files are moved there automatically the first time it starts; nothing to re-enter.
- Companion knows when it runs as the Microsoft Store app: start-with-Windows is then switched in Windows Settings > Apps > Startup (it no longer tries the Startup folder there).
- Restart the companion window to pick this up.

## 0.6.11 (not released yet)
- **Companion doesn't stop on errors anymore.** It used to close (silently, when started with Windows) if Warcraft Logs rejected your API key, if a data file was briefly locked by antivirus or OneDrive, or on any unexpected error. Now it:
  - keeps running and tries again, writing the full error to `companion_log.txt`;
  - retries a locked data file for a moment, and otherwise skips that write until the next one;
  - with a rejected API key: keeps your lookups queued, says so in game (chat once per login, red line on your listing, `/kp status`), checks every 5 minutes, and picks up a new key as soon as you run setup;
  - if it can't even start, leaves the window open with the reason.
- `/kp status` no longer calls Warcraft Logs' database limit "hourly".
- Restart the companion window to pick this up.

## 0.6.1 (not released yet)
- New addon icon (the KeyParse hexagon) in the AddOns list, for all four KeyParse entries. The full logo ships too (`KeyParse\media\`).
- Includes everything listed below from 0.7.0 to 0.11.2.

## 0.11.2 (not released yet; not tested in game)
- **Weak applicants**: a skull in front of an applicant's number when it's below 25 (grey on Warcraft Logs), plus a tooltip line. Only when the key you're pushing is +19 or lower (anyone applying to 20s is assumed good), and only from at least your "runs needed". Turn it off in the options ("Skull on weak applicants").

## 0.11.1 (not released yet; not tested in game)
- **Applicant rows show one number**: the average of all their runs from 2 keys below your key up to it (listing +18: every +16, +17 and +18 run together). No more `50/70 +15 (4)` text, which leaves room for the icons (star, `+BL`/`+BR`, `*`, `!`).
  - A grey `-` when they have logs but no runs in that range (with the orange `!`).
  - Hover for what the number is: "avg of 12 DPS runs on +16 to +18". Their dungeon and per-key details are still in the tooltip.
  - The orange `!` now also shows when the number comes from another role (applied as tank, only DPS logs).
  - Applicant sorting uses the same number.
- **Strong applicants** now follow that number: star and alert when it's **80 or higher** (adjustable; was 90 on a single key level). A saved 90 from 0.11.0 is moved to 80 once.
- Search-list and right-click labels are unchanged.

## 0.11.0 (not released yet; not tested in game)
- **Options panel**: Esc > Options > AddOns > KeyParse, or `/kp options`. Every `/kp` setting as checkboxes and sliders (key you're pushing, runs needed, Parse column, sorting, auto look-ups, reload/reopen/pin, show in combat), plus new ones:
  - Group checklist on/off, played-with history on/off.
  - **Quiet chat**: skips info-only lines (the sorting note at login, "Fetching N players…", "remembered this key"). Warnings still show.
- **Strong applicants**: someone averaging 90+ on one of the two key levels just below the key you're pushing (listing +18: their +16s or +17s), in the role they applied as, with enough runs.
  - A star in front of their parse and a line in their tooltip.
  - After the reload that fetched parses: one chat line (e.g. "1 strong applicant (90+ on +16/+17): Star-Thrall 95 on +17") and WoW's taskbar icon flashes.
  - The 90 is adjustable (50-99); star and alert can each be turned off.

## 0.10.1 (not released yet)
- Clearer message when Warcraft Logs answers "no database points remaining". That limit isn't your hourly points and usually clears within minutes, so it now reads `WCL busy (database limit), retrying every 2 min` (search list and your listing) and "Warcraft Logs is busy (its database limit, not your points)…" in chat, instead of "hourly limit used up, resumes in N min".
- Companion: re-checks every 2 minutes in that case and no longer counts down to the hourly reset. Restart the companion window to pick this up.

## 0.10.0 (not released yet; not tested in game)
- **Played-with history**: every key you finish (timed or depleted; practice runs skipped) is remembered for each player in your group. Their tooltip then shows `Played with you: 2 keys, 1 timed` and your 3 most recent keys together, e.g. `+17 Den of Nalorakk  depleted, 2d ago`.
  - Shows on applicant tooltips, player mouseover tooltips and search-list leader tooltips. Nothing is added to the rows.
  - Saved with your addon settings, so it survives logout and PC shutdown. Cleared when a new M+ season starts. Keys abandoned before the end aren't recorded.
  - A short chat line confirms each recorded key.

## 0.9.2 (not released yet; not tested in game)
- Group Finder search list: Warcraft Logs points now read `WCL points: 983/1000 (resets in 49 min)` on their own, no longer prefixed "KeyParse:". KeyParse hints (type 18-18 + Enter, pinned group, etc.) still show on the line above.

## 0.9.1 (not released yet; not tested in game)
- Your own listing: the top-right corner of the dungeon picture is now one right-aligned stack, so nothing runs into the title as it gets longer:
  1. `Lust ✓  Brez ✗` (moved here from next to the title)
  2. KeyParse notices, e.g. "KeyParse: 3 lookups waiting (reload to fetch)"
  3. `WCL points: 983/1000 (resets in 49 min)` (no longer prefixed "KeyParse:")
  Empty lines are skipped and the rest move up.

## 0.9.0 (not released yet; not tested in game)
- **Group checklist** on your own listing, right after the title: `Lust ✓  Brez ✗`, green when someone in your group brings it, red when nobody does. Worked out from your group's classes (no Warcraft Logs points). Hover it to see which classes count.
  - Bloodlust: Shaman, Mage, Hunter (needs the right pet), Evoker. Battle res: Druid, Death Knight, Warlock, Paladin.
- Applicants who'd fill a missing one get a green `+BL` or `+BR` in front of their parse, and a line in their tooltip. Updates when someone joins or leaves your group.

## 0.8.0 (not released yet; tested in game)
- **Your dungeon's parse**: when you list a dungeon, applicants show `<that dungeon>/<overall> +15` (e.g. `50/70 +15` = 50 on your dungeon, 70 overall, at +15). The tooltip spells it out.
- **Experience warning**: an orange `!` when an applicant has no logged runs at your key level or higher, or has runs there but never in time (fastest run vs Blizzard's dungeon timer). Hover for which one.
- **Spec check**: the same `!` when someone applies on a spec they have no logs on (e.g. applied Frost, logs are Fire). Hover for details.
- **Applicants sorted by parse**: healers first (they're never looked up), then best parse first, then everyone without logs. A chat line explains it after every reload. `/kp sort off` turns it off.
- Companion: also sends each dungeon's fastest run time and which specs a player has logs on. Players looked up before this update get the timed check and spec check after their next refresh. Restart the companion window to pick this up.

## 0.7.5 (not released yet)
- Your own listing: Warcraft Logs points left are shown in the top-right corner of the dungeon picture (same green-to-grey colour).
- "Show group parses" / "Refresh group parses" no longer carry the red "(uses significant search points)" note.
- Raider.IO's round "copy group" button no longer sits on top of Delist on your own listing: KeyParse moves it just right of Delist while the listing shows, and puts it back afterwards.

## 0.7.4 (not released yet)
- **Warcraft Logs points left**: shown in the Group Finder search list (on a second line under any KeyParse hint, otherwise as "KeyParse: WCL points: 688/1000 (resets in 23 min)"), after "Parses updated." in chat, and in `/kp status`. The number fades from vibrant green to grey as the hour's points run out.
- When Warcraft Logs' hidden hourly database limit is used up, the line turns grey and says when lookups resume. That hidden limit isn't reported, so it can't be counted down.
- Companion: records the points from every Warcraft Logs answer and passes them to the addon (kept across companion restarts). Restart the companion window to pick this up.

## 0.7.3 (not released yet)
- Back to your search: the group you parsed is now **pinned to the top** of the search results, so you don't have to scroll to it. The hint says "parsed group pinned to the top". Turn it off with `/kp pin off`.
- Still can't re-run your search text (e.g. `15-15`) for you: Blizzard reads the search box directly and blocks addons from typing in it. Type it and press Enter; the pin takes effect when the results arrive.

## 0.7.2 (not released yet)
- Group Finder listings: right-click a group > **"Show leader parse"** (leader only). Blizzard gives the other members' names without their realm, so they were being looked up on your own realm and always came back "no logs". The ▼ on a listing now shows the leader's keys > dungeons.
- Party: right-click **your own character** > **"Show group parses" (uses significant search points)** in red. After the lookup it opens members > key levels > dungeons. No longer offered when right-clicking other party members, or in raids.
- Healers are never looked up: not as applicants, party members, listing leaders or with /kp group. They show as "healer" / "healer, not looked up".
- Companion: drops healer runs and no longer makes the extra HPS query.

## 0.7.1 (not released yet)
- Parsing a group (or player) while browsing Group Finder search results: after the reload, Premade Groups reopens with a **"KeyParse: back to your Dungeons search"** button. One click runs Blizzard's own Dungeons > Find Group (a secure click, so no addon-blocked popup).
- Your search text (e.g. `18-18`) is shown above the list until you've searched it again. Blizzard locks that box, so addons can't type it for you.
- The group you parsed is highlighted in the list (blue bar). If it's scrolled off, the hint says where it is ("#7, scroll down"). Lasts 15 minutes.
- Says so in chat if the Group Finder didn't come back after the reload.

## 0.7.0 (not released yet)
- Party: right-click anyone in your party (yourself too) > "Parse entire party". Afterwards "Party parses (n/m)" lists everyone, each with the key/dungeon dropdown. Not offered in raids.
- Group Finder listings: right-click a group > "Show group parses". After the reload a ▼ appears on that listing with each member and their dropdown.
- Blizzard sometimes hides non-leader names on listings; those members show as "name hidden by Blizzard" and only the visible names are looked up.
- After a fetch while you're applied to someone else's group: one chat line saying how to get the list back (Blizzard blocks addons from re-running the search).

## 0.6.1
- Right-click > Get M+ parses (and Refresh / try again) now reloads right away so the lookup starts immediately. Not in combat. `/keyparse autoreload off` to turn off.

## 0.6.0 (first release candidate)
- Group Finder: Parse column with each applicant's same-key average for the role they applied as.
- ▼ dropdown: every key level, and each key's 8 dungeons in Warcraft Logs order ("no parses" where empty).
- Right-click menu: "Get M+ parses", then the player's summary with the same dropdown.
- Tooltips with the average; hold Shift for every key level.
- Auto-queue applicants; "KeyParse: fetch" button (greys out when there's nothing to fetch); the Group Finder reopens after the reload.
- Key detection from a "+N" at the start of your group title, or your own keystone; `/keyparse key N` to override.
- Low-sample marker, different-role marker ("dps"), "none <+N", "no logs", "failed".
- Companion: parallel lookups with retry/backoff; pauses when Warcraft Logs' hourly limit is used up and tells you in game.
- Companion: realm name normalization, duplicate-run removal, new-season reset, results deleted after 24 hours.
- Companion: start with Windows option; only one copy runs at a time.
