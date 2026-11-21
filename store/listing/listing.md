# Microsoft Store listing: M+ KeyParse Companion (English, United States)

## Description
M+ KeyParse Companion is the free desktop helper for KeyParse, a World of Warcraft addon that shows how well other players really play Mythic+ dungeons at the key level you are pushing.

When you list a key, KeyParse shows each applicant's average Warcraft Logs DPS parse on the keys around yours, for example their +16 to +18 runs when you list a +18, right in the Group Finder. It also shows parses in tooltips and right-click menus, flags strong and weak applicants, and tells you if your group still needs Bloodlust or a battle res.

World of Warcraft addons can't go online, so this companion does the lookups:
- It watches for lookup requests the addon saves when you /reload.
- It looks those players up on Warcraft Logs with your own free API key.
- It writes the results back into the addon's data files, ready after the next reload.

Its window shows what it's doing: whether it's watching World of Warcraft, your Warcraft Logs points left this hour, your recent lookups (with a link to each player's Warcraft Logs page) and any problem with what to do about it. Closing the window keeps it running in the tray.

The Last key page reviews your most recent Mythic+ key from WoW's own combat log on your PC: time and whether it was timed, a timeline of boss kills and deaths, damage, healing, interrupts and deaths for the whole group, what killed each player, and your damage by spell. It uses no Warcraft Logs points.

Requirements:
- World of Warcraft (Retail) with the KeyParse addon installed.
- For the Last key page: combat logging on in WoW (/combatlog, or the Warcraft Logs uploader).
- A free Warcraft Logs API client (create one at warcraftlogs.com/api/clients). The first time it starts, the companion opens its Setup page for the client ID and secret.

The companion starts with Windows so lookups are ready when you play. You can turn that off in Settings > Apps > Startup.

Privacy: no accounts, ads or tracking. Your API key stays on your PC, and results are deleted after 24 hours. Full policy: https://taftonator.github.io/KeyParse/privacy.html

KeyParse is a fan-made tool. It is not affiliated with or endorsed by Blizzard Entertainment or Warcraft Logs.

## Product features (one per line)
Average Warcraft Logs M+ parses for group applicants at your key level
Uses your own free Warcraft Logs API key
One /reload per lookup batch
Status window with Warcraft Logs points left and recent lookups
Last key review: timeline, damage, healing, interrupts and deaths from your own combat log
Starts with Windows, runs quietly in the tray
Results deleted after 24 hours, in line with Warcraft Logs' API terms
No accounts, ads or tracking

## What's new in this version (Partner Center: Store listing > "What's new in this version")
Easier first-time setup: the Setup page now walks you through making your free Warcraft Logs key step by step, with Copy buttons for what to type. It also catches common mistakes (codes swapped, the same code twice, stray spaces) and explains them in plain words. Once your key is saved the guide tucks itself away. Your saved key keeps working after this update.

## Search terms (max 7)
World of Warcraft
Mythic Plus
Warcraft Logs
WoW addon
M+ parses
Group Finder
KeyParse

## Copyright and trademark info
© 2026 taftonator. World of Warcraft is a trademark of Blizzard Entertainment, Inc. Warcraft Logs is a trademark of its owners.

## Store logos
9:16 Poster art: store\listing\PosterArt_1440x2160.png
1:1 Box art: store\listing\BoxArt_2160x2160.png
Store display images (hexagon only, transparent): Tile_300x300.png, Tile_150x150.png, Tile_71x71.png
(All redrawn sharp from logo.png by store\make_store_art.py.)

## Screenshots
Desktop, PNG, at least 1366x768 (max 3840x2160), 1 required, up to 10. Ideas: Group Finder with the parse column, an applicant tooltip, the companion window after a lookup.

## Runfulltrust justification (Submission options > restricted capabilities, max 400 characters)
Desktop companion for a World of Warcraft addon. runFullTrust lets it read the addon's saved file and WoW's combat log, and write data files into the user's WoW AddOns folder (outside the package), and look up public rankings on Warcraft Logs with the user's own API key. It has a window and tray icon and starts with Windows via a startup task the user can turn off.
