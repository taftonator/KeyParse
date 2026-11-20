"""
Builds the Microsoft Store (MSIX) package of the KeyParse companion.

  python store\\build_store.py              build exe + layout, and pack the .msix if identity.json is filled in
  python store\\build_store.py --skip-exe   reuse the last PyInstaller build (only redo logos/manifest/pack)

Output:
  store\\build\\layout\\   the unpacked app (exe folder + Assets + AppxManifest.xml + resources.pri).
                         Local test (Developer Mode on): Add-AppxPackage -Register store\\build\\layout\\AppxManifest.xml
  store\\out\\KeyParseCompanion_<version>_x64.msix   the file to upload in Partner Center (the Store signs it).

Importing this file does nothing; tests call its functions.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

STORE = Path(__file__).resolve().parent
ROOT = STORE.parent
TOC = ROOT / "addon" / "KeyParse" / "KeyParse.toc"
COMPANION = ROOT / "companion" / "companion.py"
TEMPLATE = STORE / "AppxManifest.template.xml"
IDENTITY = STORE / "identity.json"
LOGO = ROOT / "logo.png"
BUILD = STORE / "build"
LAYOUT = BUILD / "layout"
OUT = STORE / "out"
EXE_NAME = "KeyParseCompanion"
# Same exe under a second name for the Windows startup task (startup tasks can't pass arguments; the companion
# starts hidden in the tray when its file name ends in "Startup").
STARTUP_EXE = EXE_NAME + "Startup"
UI = ROOT / "companion" / "ui"
SDK_BIN = Path(r"C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64")

# Hexagon in logo.png (gold outline spans x 103-296, y 38-261), cropped to a square with a transparent outside.
HEX_CROP = (84, 34, 316, 266)
HEX = dict(cx=199.5, top=37, bottom=262, left=102, right=297)

# Asset name -> list of (file name, pixel size). Plain names are the fallback; qualified ones go into resources.pri.
ASSETS = {
    "Square44x44Logo": [("Square44x44Logo.png", 88), ("Square44x44Logo.scale-100.png", 44),
                        ("Square44x44Logo.scale-200.png", 88)]
    + [(f"Square44x44Logo.targetsize-{s}.png", s) for s in (16, 24, 32, 48, 256)]
    + [(f"Square44x44Logo.targetsize-{s}_altform-unplated.png", s) for s in (16, 24, 32, 48, 256)],
    "Square150x150Logo": [("Square150x150Logo.png", 300), ("Square150x150Logo.scale-100.png", 150),
                          ("Square150x150Logo.scale-200.png", 300)],
    "StoreLogo": [("StoreLogo.png", 100), ("StoreLogo.scale-100.png", 50), ("StoreLogo.scale-200.png", 100)],
}


def toc_version(toc=TOC):
    m = re.search(r"^## Version:\s*(\S+)", Path(toc).read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit(f"No '## Version:' in {toc}")
    return m.group(1)


def msix_version(v):
    """0.6.13 -> 0.6.13.0. The Store needs 4 numbers, each <= 65535, and the last one 0."""
    parts = v.split(".")
    if not 1 <= len(parts) <= 3 or not all(p.isdigit() and int(p) <= 65535 for p in parts):
        raise ValueError(f"Can't turn version {v!r} into an MSIX version")
    return ".".join(str(int(p)) for p in parts + ["0"] * (4 - len(parts)))


def identity_problems(ident):
    """What's wrong with identity.json (empty list = ready for the Store)."""
    probs = []
    for key in ("name", "publisher", "publisher_display_name"):
        val = str(ident.get(key, "")).strip()
        if not val or "PASTE" in val:
            probs.append(f"{key} is not filled in")
    if not probs:
        if not str(ident["publisher"]).startswith("CN="):
            probs.append("publisher must start with CN=")
        if not re.fullmatch(r"[A-Za-z0-9.\-]{3,50}", ident["name"]):
            probs.append("name may only use letters, digits, '.' and '-' (3-50 characters)")
    return probs


def xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def render_manifest(ident, version, template=TEMPLATE):
    """Fill in the manifest. With a placeholder identity it uses a local-test identity so the layout still installs."""
    local = bool(identity_problems(ident))
    vals = {
        "NAME": "KeyParse.Companion.LocalTest" if local else ident["name"],
        "PUBLISHER": "CN=KeyParseLocalTest" if local else ident["publisher"],
        "PUBLISHER_DISPLAY_NAME": "KeyParse (local test)" if local else ident["publisher_display_name"],
        "DISPLAY_NAME": ident.get("display_name") or "M+ KeyParse Companion",  # must match the reserved Store name
        "VERSION": msix_version(version),
    }
    text = Path(template).read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->\s*", "", text, count=1, flags=re.S)  # drop the template's own help comment
    for k, v in vals.items():
        text = text.replace("{{" + k + "}}", xml_escape(v))
    if "{{" in text:
        raise ValueError("Manifest template has an unknown {{...}} field")
    return text


def hex_icon(size, logo=LOGO):
    """The KeyParse hexagon from logo.png, size x size, transparent outside the hexagon."""
    from PIL import Image, ImageDraw
    src = Image.open(logo).convert("RGBA")
    h = HEX["bottom"] - HEX["top"]
    pts = [(HEX["cx"], HEX["top"]), (HEX["right"], HEX["top"] + h / 4), (HEX["right"], HEX["bottom"] - h / 4),
           (HEX["cx"], HEX["bottom"]), (HEX["left"], HEX["bottom"] - h / 4), (HEX["left"], HEX["top"] + h / 4)]
    # Draw the mask 4x bigger then shrink it, for a smooth edge.
    mbig = Image.new("L", (src.size[0] * 4, src.size[1] * 4), 0)
    ImageDraw.Draw(mbig).polygon([(x * 4, y * 4) for x, y in pts], fill=255)
    mask = mbig.resize(src.size, Image.LANCZOS)
    src.putalpha(mask)
    return src.crop(HEX_CROP).resize((size, size), Image.LANCZOS)


def make_assets(dest, logo=LOGO):
    """Writes every logo in ASSETS into dest (the layout's Assets folder). Returns the file names."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    made = []
    for files in ASSETS.values():
        for name, size in files:
            hex_icon(size, logo).save(dest / name)
            made.append(name)
    return made


def make_ico(path, logo=LOGO):
    hex_icon(256, logo).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def run(cmd):
    print("> " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def build_exe():
    """PyInstaller onedir build (a folder, not one big exe: starts faster and the Store expects plain files).
    --windowed: no console window (the companion has its own window and tray icon); ui\ holds the window's page."""
    BUILD.mkdir(parents=True, exist_ok=True)
    ico = BUILD / "KeyParse.ico"
    make_ico(ico)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
         "--add-data", f"{UI};ui",
         "--name", EXE_NAME, "--icon", ico, "--distpath", BUILD / "dist", "--workpath", BUILD / "work",
         "--specpath", BUILD, COMPANION])


def pri_config(xml):
    """Index only Assets\\ (not the exe's Python files) and keep one resources.pri (no split scale-200 packs)."""
    xml = re.sub(r"\s*<packaging>.*?</packaging>", "", xml, flags=re.S)
    return re.sub(r'(<index\b[^>]*\bstartIndexAt=")[^"]*(")', r"\1Assets\2", xml, count=1)


def make_pri(layout):
    makepri = SDK_BIN / "makepri.exe"
    cfg = BUILD / "priconfig.xml"
    run([makepri, "createconfig", "/cf", cfg, "/dq", "en-US", "/pv", "10.0.0", "/o"])
    cfg.write_bytes(pri_config(cfg.read_bytes().decode("utf-8-sig")).encode("utf-8"))
    run([makepri, "new", "/pr", layout, "/cf", cfg, "/mn", layout / "AppxManifest.xml",
         "/of", layout / "resources.pri", "/o"])


def main():
    args = sys.argv[1:]
    version = toc_version()
    ident = json.loads(IDENTITY.read_text(encoding="utf-8"))
    probs = identity_problems(ident)
    if "--skip-exe" not in args or not (BUILD / "dist" / EXE_NAME).exists():
        build_exe()
    if LAYOUT.exists():
        shutil.rmtree(LAYOUT)
    shutil.copytree(BUILD / "dist" / EXE_NAME, LAYOUT)
    shutil.copy2(LAYOUT / f"{EXE_NAME}.exe", LAYOUT / f"{STARTUP_EXE}.exe")
    make_assets(LAYOUT / "Assets")
    (LAYOUT / "AppxManifest.xml").write_bytes(render_manifest(ident, version).encode("utf-8"))
    make_pri(LAYOUT)
    print(f"\nLayout ready: {LAYOUT}")
    print(f"Local test (Developer Mode on):  Add-AppxPackage -Register \"{LAYOUT / 'AppxManifest.xml'}\"")
    if probs:
        print("\nNot packing the .msix yet - identity.json: " + "; ".join(probs))
        print("(The layout uses a local-test identity, so the local test still works.)")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    msix = OUT / f"{EXE_NAME}_{msix_version(version)}_x64.msix"
    run([SDK_BIN / "makeappx.exe", "pack", "/d", LAYOUT, "/p", msix, "/o"])
    print(f"\nUpload this in Partner Center > Packages: {msix}")


if __name__ == "__main__":
    main()
