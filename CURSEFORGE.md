# KeyParse

**See how people actually play before you invite them.** KeyParse shows each Group Finder applicant's average **Warcraft Logs M+ DPS parse on the keys around yours**, right next to their name.

List a +18 and every applicant gets one number: the average of all their logged +16, +17 and +18 runs, for the role they applied as.

## Why same-key parses?

Warcraft Logs' usual M+ percentile mostly reflects **key level**: almost every high key lands near the top, no matter how the player did. KeyParse uses Warcraft Logs' *same key level* rankings instead, so each player is compared only to the same spec at the same key level. That's the number that actually separates good players from carried ones.

## Features

**Your applicants**
- **Parse column**: one number per applicant, in Warcraft Logs colors. Click the ▼ for every key level, and every dungeon at each level.
- **Sorted for you**: healers first, then best parse first, then players without logs.
- **Warnings**: a red `*` means too few runs to trust the number. An orange `!` means new to your key level, never timed it, or applied on a spec they have no logs on. Hover for details.
- **Strong and weak**: a star on strong applicants, with one chat line and a taskbar flash so you can tab out while your group fills. A skull on very weak ones (keys up to +19).
- **Lust / Brez checklist**: your listing shows whether your group has Bloodlust and a battle res, and applicants who'd fill the gap get a green `+BL` / `+BR`.
- **Auto-fetch**: everyone who applies is queued. Click **KeyParse: fetch**, the UI reloads, the Group Finder reopens and the parses are there.

**Everyone else**
- **Player search**: `/kp search Name-Realm` opens a window with every key level, each dungeon's parse, their fastest run vs the timer, the specs they play, and your history with them. No need to open the Warcraft Logs site.
- **Right-click any player**: **Get M+ parses**. Once fetched, their summary and full breakdown are right in the menu.
- **Your party**: right-click yourself, **Show group parses**.
- **Groups you might join**: right-click a listing, **Show leader parse**. After the reload you're taken back to your search, with that group pinned to the top.
- **Tooltips**: hover a player for their parse. Hold **Shift** for every key level.
- **Played with you**: every key you finish is remembered per player (timed or depleted) and shown in their tooltip, until the season ends.

**Setup and testing**
- **Options panel**: Esc > Options > AddOns > KeyParse (or `/kp options`). Key level, runs needed, star/skull thresholds, sorting, quiet chat and more.
- **Test queue**: `/kp test` shows fake applicants so you can see every marker without listing a key. Fakes are never looked up or saved.

## Requirements: M+ KeyParse Companion (free, Windows)

WoW addons can't access the internet, so KeyParse needs a small free companion app running on your PC while you play. It looks players up on Warcraft Logs with **your own free Warcraft Logs API key** and hands the results to the addon.

1. Install this addon. Make sure all four KeyParse entries are enabled in the AddOns list (KeyParse plus three small data addons).
2. Get **M+ KeyParse Companion** from the Microsoft Store: https://apps.microsoft.com/detail/9NZ96JDM66PT
3. The first time, it asks for a Warcraft Logs API key. Create one free at warcraftlogs.com/api/clients (any name, redirect URL `http://localhost`, leave "Public Client" unchecked) and paste the Client ID and Secret.
4. It starts with Windows from then on, so lookups are ready when you play.

## Commands

`/kp` (or `/keyparse`) shows help. Most of these are also in the options panel.

| Command | What it does |
|---|---|
| `/kp search Name-Realm` | Look a player up (realm optional = yours) |
| `/kp options` | Open the options panel |
| `/kp key 18` / `key auto` | Set the key you're pushing, or use your listing's +N (default) |
| `/kp min 3` | Runs needed before an average counts |
| `/kp applicants` / `group` | Queue everyone applying / in your group |
| `/kp fetch` | Reload to fetch everything queued |
| `/kp test` | Open the test queue |
| `/kp status` | Data age, pending lookups, Warcraft Logs points left |

## Good to know

- **DPS and tanks only.** Healers aren't looked up (they show as "healer"), which keeps lookups cheap.
- **Only public logs.** Players who hide their logs on Warcraft Logs show as "no logs".
- **One reload per batch.** Addons can't go online, so fetching always takes a `/reload`; KeyParse brings you back to where you were.
- **Lookup limits.** Each Warcraft Logs API key gets 1000 points an hour, about 100 lookups. Your friends' keys are separate. If Warcraft Logs itself is busy, KeyParse says so and retries every 2 minutes.
- **Nothing stored long-term.** Results are deleted after 24 hours, as Warcraft Logs' API terms require.
- **Not affiliated with Warcraft Logs or Blizzard.** Parse data comes from the Warcraft Logs API.

## Feedback

Found a bug, got confused, or have an idea? Tell me in the **2-minute feedback form** (no sign-in, email not collected): https://docs.google.com/forms/d/e/1FAIpQLSeNU-tufRSgHTKupklbQQ1YlSjCZ8FT9VCet0o5vWWukdsjIA/viewform

---
Feedback: https://docs.google.com/forms/d/e/1FAIpQLSeNU-tufRSgHTKupklbQQ1YlSjCZ8FT9VCet0o5vWWukdsjIA/viewform · Companion app: https://apps.microsoft.com/detail/9NZ96JDM66PT · Privacy policy: https://taftonator.github.io/KeyParse/privacy.html · GitHub: https://github.com/taftonator/KeyParse
