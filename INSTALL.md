# M+ KeyParse Companion: install guide (Windows)

The KeyParse addon shows Warcraft Logs parses in game, but WoW addons can't access the internet.
This small free app does the lookups for it. It needs to be running while you play.

## 1. Get a free Warcraft Logs API key (2 minutes, one time)

1. Log in at **warcraftlogs.com** (a free account works).
2. Go to **warcraftlogs.com/api/clients** and click **Create Client**.
3. Name: anything (e.g. "KeyParse"). Redirect URL: `http://localhost`. Leave **Public Client** unchecked.
4. Click **Create**. Copy the **Client ID** and **Client Secret**. The secret is shown only once.

Your key is yours alone. **Never share your Client Secret.**

## 2. Install the companion

1. Get **M+ KeyParse Companion** from the Microsoft Store: https://apps.microsoft.com/detail/9NZ96JDM66PT
2. Open it once from the Start menu. It asks for:
   - your **Client ID** and **Client Secret**,
   - your WoW `_retail_` folder (it usually finds this itself; press Enter to accept).
3. That's it. It starts with Windows from now on, so lookups are ready when you play.
   To turn that off: Windows **Settings > Apps > Startup**.

## 3. In game

1. Install the **KeyParse** addon (CurseForge app) and make sure **all four** KeyParse entries are enabled in the
   AddOns list (KeyParse plus three small data addons).
2. List a key. When people apply, click **KeyParse: fetch**. Your UI reloads, the Group Finder reopens, and their
   parses appear.
3. Or right-click any player and choose **Get M+ parses**, or type `/kp search Name-Realm`.

## Troubleshooting

- **"The companion app didn't respond"** in chat: the app isn't running. Open it from the Start menu, then `/reload`.
- **The companion says your API key was rejected**: create a new client (step 1). Then close the companion, delete
  `config.json` in the folder below, and open the companion again: it asks for the key again.
- **"failed"** next to a name: wrong name or realm, or Warcraft Logs had a problem. KeyParse retries after 10 minutes.
  The reason is in `companion_log.txt` in the folder below.
- **"Warcraft Logs is busy"**: their database limit, not yours. The companion retries every 2 minutes.
- **"no logs"**: that player has no public Mythic+ DPS or tank logs this season, or hides their logs.

The companion's files (`config.json`, `companion_log.txt`) are in this folder (paste it into Explorer's address bar):

```
%LOCALAPPDATA%\Packages\taftonator.MKeyParseCompanion_mfmz6hgt608aw\LocalCache\Local\KeyParse
```

## Running from source (advanced)

With Python 3 installed: `pip install -r companion\requirements.txt`, then `python companion\companion.py`
(`setup` to re-enter your key, `lookup Name-Realm` to test a lookup, `autostart on|off`). Its files go to
`%LOCALAPPDATA%\KeyParse`.
