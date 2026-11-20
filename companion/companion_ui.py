"""
The KeyParse companion window (Status + Setup pages) and its tray icon.

The page itself is ui/index.html, shown with pywebview (it draws with Microsoft Edge's engine, which is part of
Windows). Nothing here goes online except the companion's own Warcraft Logs lookups. All the data shown and the
saving/checking come from plain functions in companion.py (status_snapshot, save_setup, test_key,
wow_folder_check), which the tests cover; this file only wires them to the window, the tray icon and the watcher.

Closing the window hides it; the companion keeps running in the tray until Quit.
"""
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

TITLE = "M+ KeyParse Companion"
UI_DIR = (Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent) / "ui"
BG = "#0d0a17"


class App:
    def __init__(self, c, hidden=False, page=None):
        self.c = c  # the companion module (passed in: when run as a script it is __main__, not "companion")
        self.cfg = c.load_json(c.CONFIG_PATH, {})
        if not self.cfg.get("wow_retail_path"):
            found = c.find_wow_retail()
            if found:
                self.cfg["wow_retail_path"] = str(found)
        self.cache = c.load_json(c.CACHE_PATH, {})
        self.api = None
        self.stop = threading.Event()
        self.quitting = False
        self.window = None
        self.icon = None
        self.told_tray = False
        self.lastkey = {"state": "idle"}   # Last key page: read in the background (a big log takes a few seconds)
        self._lk_lock = threading.Lock()
        needs_setup = not (self.cfg.get("client_id") and self.cfg.get("client_secret"))
        self.hidden = hidden and not needs_setup  # never hide a first run: it has to be set up
        self.page = page or ("setup" if needs_setup else "status")

    # ---- the watcher (same loop as the console version, in a background thread)
    def start_watcher(self):
        c = self.c
        if not (self.cfg.get("client_id") and self.cfg.get("client_secret")):
            return
        if self.api is not None:  # already running: just use the new key
            if (self.api.client_id, self.api.client_secret) != (self.cfg["client_id"], self.cfg["client_secret"]):
                self.api.client_id, self.api.client_secret, self.api.token = \
                    self.cfg["client_id"], self.cfg["client_secret"], None
                self.api.paused_until = 0
            return
        self.api = c.WCL(self.cfg["client_id"], self.cfg["client_secret"])
        threading.Thread(target=self._watch, daemon=True, name="watcher").start()

    def _watch(self):
        try:
            self.c.watch(self.api, self.cfg, self.cache, self.stop)
        except Exception:
            self.c.log_exception("The watcher stopped because of an error:")
            self.c.STATUS.update(watching=False, error="Lookups stopped because of an error (details in the log "
                                 "file). Quit and start the companion again.", error_at=time.time())

    # ---- Last key (WoW's own combat log)
    def last_key(self, force=False):
        with self._lk_lock:
            busy = self.lastkey.get("state") == "reading"
            stale = force or self.lastkey.get("state") == "idle"
            if not busy and stale:
                old = self.lastkey
                self.lastkey = dict(old, state="reading") if old.get("key") else {"state": "reading"}
                threading.Thread(target=self._read_last_key, daemon=True, name="lastkey").start()
            return self.lastkey

    def _read_last_key(self):
        import lastkey
        c = self.c
        try:
            if not self.cfg.get("wow_retail_path"):
                result = {"state": "none", "reason": "nowow"}
            else:
                result = lastkey.last_key(self.cfg["wow_retail_path"], c.DATA_DIR / "lastkey.json")
                if result.get("key"):
                    result["timed"] = lastkey.timed_from_history(result["key"], c.addon_history(self.cfg))
        except Exception as exc:
            c.log_exception("Couldn't read the last key from the combat log:")
            result = {"state": "error", "text": str(exc)[:200]}
        with self._lk_lock:
            self.lastkey = result

    # ---- window
    def show(self):
        if self.window:
            self.window.show()
            self.window.restore()

    def hide(self):
        if self.window:
            self.window.hide()
        if not self.told_tray and self.icon:
            self.told_tray = True
            try:
                self.icon.notify("Still running in your tray. Right-click the KeyParse icon to quit.", TITLE)
            except Exception:
                pass

    def on_closing(self):
        if self.quitting:
            return True
        threading.Thread(target=self.hide, daemon=True).start()
        return False  # keep the app (and lookups) running

    def on_shown(self):
        dark_title_bar(self.window)

    def quit(self):
        self.quitting = True
        self.stop.set()
        if self.icon:
            self.icon.stop()
        if self.window:
            self.window.destroy()

    # ---- tray icon
    def tray_text(self, _item=None):
        try:
            s = self.c.status_snapshot(self.cache, self.cfg, api=self.api)
        except Exception:
            return "KeyParse"
        text = s["state"]["title"]
        if s["points"]:
            text += f" · {s['points']['left']} points left"
        return text

    def start_tray(self):
        try:
            import pystray
            from PIL import Image
        except ImportError:
            return  # no tray: closing the window just hides it, Quit isn't reachable -> keep the window closable
        image = Image.open(UI_DIR / "hex.png")
        menu = pystray.Menu(
            pystray.MenuItem("Open KeyParse Companion", lambda: self.show(), default=True),
            pystray.MenuItem(self.tray_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: self.quit()))
        self.icon = pystray.Icon("KeyParseCompanion", image, TITLE, menu)
        self.icon.run_detached()

        def keep_title_fresh():
            while not self.stop.wait(30):
                try:
                    self.icon.title = f"{TITLE}\n{self.tray_text()}"[:127]
                except Exception:
                    pass
        threading.Thread(target=keep_title_fresh, daemon=True).start()

    # ---- a second copy (e.g. clicking the Start menu entry while it runs in the tray) asks this one to show
    def listen_for_show(self, guard):
        def loop():
            while not self.stop.is_set():
                try:
                    conn, _ = guard.accept()
                    with conn:
                        if conn.recv(16).startswith(b"show"):
                            self.show()
                except OSError:
                    time.sleep(1)
        threading.Thread(target=loop, daemon=True).start()


class JsApi:
    """What the page can call (window.pywebview.api.*). Names starting with _ are not exposed."""

    def __init__(self, app):
        self._app = app

    def status(self):
        a = self._app
        return a.c.status_snapshot(a.cache, a.cfg, api=a.api)

    def last_key(self, force=False):
        return self._app.last_key(bool(force))

    def open_url(self, url):
        if str(url).startswith("https://www.warcraftlogs.com/"):  # only Warcraft Logs pages
            webbrowser.open(url)

    def setup_info(self):
        return self._app.c.setup_info(self._app.cfg)

    def check_folder(self, path):
        return self._app.c.wow_folder_check(path)

    def test_key(self, client_id, client_secret):
        return self._app.c.test_key(client_id, client_secret, self._app.cfg)

    def save(self, client_id, client_secret, wow_path):
        a = self._app
        result = a.c.save_setup(a.cfg, client_id, client_secret, wow_path)
        if result["ok"]:
            a.c.log("Settings saved from the companion window.")
            a.start_watcher()
        return result

    def browse(self, start=""):
        import webview
        folder = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        start = start if start and Path(start).is_dir() else ""
        picked = self._app.window.create_file_dialog(folder, directory=start)
        return picked[0] if picked else ""

    def open_key_page(self):
        webbrowser.open(self._app.c.KEY_PAGE)

    def open_startup_settings(self):
        os.startfile("ms-settings:startupapps")

    def open_log(self):
        log = self._app.c.LOG_PATH
        if log.exists():
            os.startfile(log)

    def hide(self):
        self._app.hide()


def dark_title_bar(window):
    """Dark title bar in the app's colours (Windows 11; older Windows just keeps its normal title bar)."""
    try:
        import ctypes
        hwnd = window.native.Handle.ToInt64()
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)          # DWMWA_USE_IMMERSIVE_DARK_MODE
        colour = ctypes.c_int(0x00140b0b)                                  # caption colour #0b0b14 (0x00BBGGRR)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colour), 4)      # DWMWA_CAPTION_COLOR
    except Exception:
        pass


def claim_single_instance(port):
    """Hold a local-only port while running. If another copy has it, ask that copy to show its window."""
    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        guard.bind(("127.0.0.1", port))
        guard.listen(2)
        return guard
    except OSError:
        guard.close()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2) as s:
                s.sendall(b"show")
        except OSError:
            # An older companion (0.6.16 and before: black console window) holds the port but doesn't listen.
            # Say so instead of closing silently.
            message_box("An older KeyParse companion is still running (the black console window).\n\n"
                        "Close that window first (or end KeyParseCompanion.exe in Task Manager > Details), "
                        "then start this one again.")
        return None


def message_box(text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x40)  # MB_ICONINFORMATION
    except Exception:
        pass


def run(c, hidden=False, page=None, preview=False):
    """preview=True: only show the window (no lookups, no single-copy check), e.g. while the Store copy runs."""
    guard = None
    if preview:
        c.STATUS["preview"] = True
    else:
        guard = claim_single_instance(c.SINGLE_INSTANCE_PORT)
        if guard is None:
            return
    import webview
    app = App(c, hidden=hidden, page=page)
    if guard:
        app.listen_for_show(guard)
    app.start_tray()
    if not preview:
        app.start_watcher()
    app.window = webview.create_window(
        TITLE, url=(UI_DIR / "index.html").as_uri() + "#" + app.page, js_api=JsApi(app),
        width=1000, height=700, min_size=(860, 600), background_color=BG, hidden=app.hidden)
    app.window.events.closing += app.on_closing
    app.window.events.shown += app.on_shown
    try:
        webview.start(gui="edgechromium", private_mode=True)
    finally:
        app.stop.set()
        if app.icon:
            try:
                app.icon.stop()
            except Exception:
                pass
        if guard:
            guard.close()
