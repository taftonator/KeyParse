"""
Build KeyParse release zips and check them before upload.

  python build_release.py

Writes:
  release/KeyParse-<version>.zip            the addon (upload this to CurseForge)
  release/KeyParseCompanion-<version>.zip   the companion app (GitHub Releases), if dist/KeyParseCompanion.exe exists
"""
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ADDON_DIR = ROOT / "addon"
FOLDERS = ["KeyParse", "KeyParse_Data1", "KeyParse_Data2", "KeyParse_Data3"]
ALLOWED = {".lua", ".toc", ".xml", ".tga", ".blp", ".txt", ".md"}       # what may ship inside the addon
PRIVATE = {"config.json", "cache.json", "companion_log.txt"}             # must never ship anywhere
PLACEHOLDER = "KeyParse_Slot = { done = true, generated = 0, season = \"\", players = {} }"


def fail(msg):
    sys.exit(f"RELEASE CHECK FAILED: {msg}")


def toc_version(folder):
    toc = ADDON_DIR / folder / f"{folder}.toc"
    if not toc.exists():
        fail(f"missing {toc}")
    m = re.search(r"^## Version:\s*(\S+)", toc.read_text(encoding="utf-8"), re.M)
    if not m:
        fail(f"no ## Version in {toc.name}")
    return m.group(1)


def main():
    versions = {f: toc_version(f) for f in FOLDERS}
    if len(set(versions.values())) != 1:
        fail(f"versions differ: {versions}")
    version = versions["KeyParse"]

    files = []
    for folder in FOLDERS:
        toc = ADDON_DIR / folder / f"{folder}.toc"
        # Ship only the .toc and the files it lists, so leftovers in the folder never end up in a release.
        listed = [line.strip() for line in toc.read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#")]
        for name in listed:
            if not (ADDON_DIR / folder / name).exists():
                fail(f"{toc.name} lists {name}, which doesn't exist")
        # Textures aren't listed in a .toc: also ship the folder's media\ (the addon icon and logo).
        media = sorted((ADDON_DIR / folder / "media").glob("*")) if (ADDON_DIR / folder / "media").is_dir() else []
        for p in [toc] + [ADDON_DIR / folder / name for name in listed] + media:
            if p.name in PRIVATE:
                fail(f"private file in addon: {p}")
            if p.suffix.lower() not in ALLOWED:
                fail(f"file type not allowed in the addon (CurseForge rejects executables): {p}")
            files.append(p)
        if folder != "KeyParse":
            data = (ADDON_DIR / folder / "Data.lua").read_text(encoding="utf-8")
            if PLACEHOLDER not in data:
                fail(f"{folder}/Data.lua contains real lookup data - restore the placeholder before releasing")
    # every .toc's IconTexture must point at a texture that ships
    for folder in FOLDERS:
        for line in (ADDON_DIR / folder / f"{folder}.toc").read_text(encoding="utf-8").splitlines():
            if line.startswith("## IconTexture:") and "AddOns\\" in line:
                rel = line.split("AddOns\\", 1)[1].strip().replace("\\", "/")
                if not any(p.relative_to(ADDON_DIR).as_posix() in (rel + ".tga", rel + ".blp") for p in files):
                    fail(f"{folder}.toc IconTexture points at {rel}, which isn't in the release")

    out_dir = ROOT / "release"
    out_dir.mkdir(exist_ok=True)
    addon_zip = out_dir / f"KeyParse-{version}.zip"
    with zipfile.ZipFile(addon_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.relative_to(ADDON_DIR).as_posix())   # folders at the zip's top level
    print(f"Wrote {addon_zip.relative_to(ROOT)}  ({len(files)} files)")

    exe = ROOT / "companion" / "dist" / "KeyParseCompanion.exe"
    if exe.exists():
        comp_zip = out_dir / f"KeyParseCompanion-{version}.zip"
        with zipfile.ZipFile(comp_zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(exe, "KeyParseCompanion/KeyParseCompanion.exe")
            for doc in ("INSTALL.md", "LICENSE"):
                if (ROOT / doc).exists():
                    z.write(ROOT / doc, f"KeyParseCompanion/{doc}")
        print(f"Wrote {comp_zip.relative_to(ROOT)}")
    else:
        print("Companion zip skipped: run companion\\build_exe.bat first to create dist\\KeyParseCompanion.exe")
    print(f"KeyParse {version}: release checks passed.")


if __name__ == "__main__":
    main()
