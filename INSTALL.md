# M+ KeyParse Companion: install guide (Windows)

The KeyParse addon shows Warcraft Logs parses in game, but WoW addons can't access the internet.
This small free app does the lookups for it. It needs to be running while you play.

## 1. Get a free Warcraft Logs API key (2 minutes, one time)

The companion's **Setup** page walks you through this too, with Copy buttons for the boxes below.

1. Go to **warcraftlogs.com/api/clients** and sign in. No account? Make a free one there.
2. Click **+ Create Client** (top right of the "Clients" box).
3. Fill in the three boxes exactly like this:
   - **Name:** `M+ KeyParse Companion - looks up Mythic+ parses for my WoW group finder` (Warcraft Logs may cancel keys whose name doesn't say what they're for)
   - **Redirect URLs:** `http://localhost` (KeyParse doesn't use it, but the box can't be empty)
   - **Public Client:** leave the box **empty**. Don't tick it.
4. Click **Create**. You now have two codes:
   - **Client ID**: short, with dashes, like `9f3c1a2e-7b44-4d1e-a0c2-5e8f1b6d9a07`. It's shown under your client's name.
   - **Client Secret**: a long code without dashes. **Copy it right away**: it's shown only once. Lost it? Delete that
     client on the same page and make a new one.

Your key is yours alone. **Never share your Client Secret.**

## 2. Install the companion

1. Get **M+ KeyParse Companion** from the Microsoft Store: https://apps.microsoft.com/detail/9NZ96JDM66PT
2. Open it from the Start menu. The first time, it opens on its **Setup** page:
   - paste the **Client ID** into the left box and the **Client Secret** into the right box,
   - press **Test key**: green "Key works" means you're done with the key,
   - check the WoW folder (it usually finds it itself; **Browse…** if not) and press **Save**.
3. That's it. It starts with Windows from now on and sits in your tray (by the clock, maybe behind the **^**), so
   lookups are ready when you play. To turn that off: Windows **Settings > Apps > Startup**.

## 3. In game

1. Install the **KeyParse** addon (CurseForge app) and make sure **all four** KeyParse entries are enabled in the
   AddOns list (KeyParse plus three small data addons).
2. List a key. When people apply, click **KeyParse: fetch**. Your UI reloads, the Group Finder reopens, and their
   parses appear.
3. Or right-click any player and choose **Get M+ parses**, or type `/kp search Name-Realm`.

## Troubleshooting

- **"The companion app didn't respond"** in chat: the app isn't running. Open it from the Start menu, then `/reload`.
- **The companion says your API key was rejected**: open its **Setup** page and paste both codes again (Client ID left,
  Secret right), or make a new client (step 1) and paste that one. Press **Test key**, then **Save**.
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
