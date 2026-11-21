"""
Turns CURSEFORGE.md into release\\CurseForge-description.html for pasting into CurseForge's description editor (it shows
raw Markdown, so the page is pasted as formatted text: open the HTML in a browser, Ctrl+A, Ctrl+C, paste).

  python make_curseforge_html.py

Handles only what CURSEFORGE.md uses: # headings, paragraphs, **bold**, *italic*, `code`, bare links, - and 1. lists
(nested by indent), | tables |, and --- lines.
"""
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "CURSEFORGE.md"
OUT = ROOT / "release" / "CurseForge-description.html"

HEAD = """<!doctype html><html><head><meta charset="utf-8"><title>KeyParse description</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:820px;margin:24px auto;line-height:1.5}
.note{background:#fff3c4;padding:10px;border:1px solid #e0c060;margin-bottom:20px}
table{border-collapse:collapse}td,th{border:1px solid #999;padding:4px 8px}</style></head><body>
<div class="note">Click anywhere in the text below, press Ctrl+A then Ctrl+C. (This yellow box gets copied too: delete it after pasting.)</div>
"""


def inline(text):
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append("<code>" + html.escape(part[1:-1]) + "</code>")
            continue
        s = html.escape(part, quote=False)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
        s = re.sub(r"(https?://[^\s<)]+)", r'<a href="\1">\1</a>', s)
        out.append(s)
    return "".join(out)


def convert(md):
    lines = md.splitlines()
    out, para, i = [], [], 0
    stack = []  # open lists: (indent, "ul"/"ol")

    def flush_para():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    def close_lists(to_indent=-1):
        while stack and stack[-1][0] > to_indent:
            out.append(f"</li></{stack.pop()[1]}>")

    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if m and not line.strip().startswith("---"):
            flush_para()
            indent, kind = len(m.group(1)), "ol" if m.group(2)[0].isdigit() else "ul"
            if stack and indent < stack[-1][0]:
                close_lists(indent)
            if stack and indent == stack[-1][0]:
                out.append("</li>")
            elif not stack or indent > stack[-1][0]:
                out.append(f"<{kind}>")
                stack.append((indent, kind))
            out.append("<li>" + inline(m.group(3)))
            i += 1
            continue
        if line.strip() == "":
            flush_para()
            close_lists()
            i += 1
            continue
        if stack and line.startswith(" "):  # continuation of a list item
            out.append(" " + inline(line.strip()))
            i += 1
            continue
        close_lists()
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h:
            flush_para()
            n = len(h.group(1))
            out.append(f"<h{n}>{inline(h.group(2))}</h{n}>")
        elif line.strip() == "---":
            flush_para()
            out.append("<hr>")
        elif line.startswith("|"):
            flush_para()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table>")
            for r, cells in enumerate(rows):
                if r == 1 and all(set(c) <= set("-: ") for c in cells):
                    continue
                tag = "th" if r == 0 else "td"
                out.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
            out.append("</table>")
            continue
        else:
            para.append(line.strip())
        i += 1
    flush_para()
    close_lists()
    return "\n".join(out)


def main():
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_bytes((HEAD + convert(SRC.read_text(encoding="utf-8")) + "\n</body></html>\n").encode("utf-8"))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
