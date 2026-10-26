"""Builds install.html (the drag-to-bookmarks page) from horseiq-kaydet.js.

    python tools/tjk-kit/build.py
"""
import re
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def bookmarklet() -> str:
    src = (HERE / "horseiq-kaydet.js").read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)  # block comments
    lines = [ln.strip() for ln in src.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("//")]
    code = "\n".join(lines)
    return "javascript:" + urllib.parse.quote(code, safe="()[]{};,=.!_~*'")


def main() -> None:
    page = (HERE / "install.template.html").read_text(encoding="utf-8")
    href = bookmarklet().replace("&", "&amp;").replace('"', "&quot;")
    (HERE / "install.html").write_text(page.replace("{{BOOKMARKLET}}", href), encoding="utf-8")
    print("install.html yazıldı,", len(href), "karakter")


if __name__ == "__main__":
    main()
