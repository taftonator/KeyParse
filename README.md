# KeyParse

A World of Warcraft (Midnight) addon that shows each Group Finder applicant's average **Warcraft Logs same-key M+ DPS parse** on the keys around the one you're running, plus a small Windows companion app (M+ KeyParse Companion, on the Microsoft Store) that does the Warcraft Logs lookups.

- **Players:** see [`INSTALL.md`](INSTALL.md) for setup, and [`CURSEFORGE.md`](CURSEFORGE.md) (the CurseForge page) for features and commands.
- **Changes:** see [`CHANGELOG.md`](CHANGELOG.md).

## Download

- **Addon:** CurseForge (search "KeyParse"), or `KeyParse-<version>.zip` from Releases. Unzip into `World of Warcraft\_retail_\Interface\AddOns`.
- **Companion app:** M+ KeyParse Companion on the Microsoft Store (Windows): https://apps.microsoft.com/detail/9NZ96JDM66PT

## How it works

WoW addons can't use the internet or read files mid-session, so:

1. **Addon to app:** the addon queues lookups in its SavedVariables, which WoW writes on `/reload`.
2. **App fetches:** the companion watches that file and looks players up with the user's own Warcraft Logs API key (`encounterRankings`, `metric: dps`, `byBracket: true`; healers are skipped).
3. **App to addon:** it writes the results into `KeyParse_Data1..3`, small load-on-demand addons. The main addon loads them a few seconds after login, so one reload is enough.

## Repository layout

```
addon/      KeyParse, KeyParse_Data1-3  (what goes in Interface\AddOns)
companion/  companion.py, build_exe.bat (PyInstaller one-file build)
store/      build_store.py, AppxManifest template, listing text/art (Microsoft Store MSIX)
tests/      harness.py + edge_tests.py  (runs the real Lua against stubbed WoW APIs, and the app against a fake Warcraft Logs)
build_release.py                        (makes the release zips and checks them)
```

## Building a release

```
python build_release.py
```

This checks every `.toc` has the same version, the data addons only contain placeholders, and nothing executable or private (`config.json`, `cache.json`) is in the addon zip. It then writes `release/KeyParse-<version>.zip` (the CurseForge upload). The Store package is built separately with `python store/build_store.py`.

## Tests

```
pip install lupa requests
python tests/edge_tests.py
```

## License

MIT. Not affiliated with Warcraft Logs (RPGLogs) or Blizzard Entertainment.
