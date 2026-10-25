"""Builds the single-file web UI: python webui/build.py  ->  docs/index.html (GitHub Pages serves /docs).

Inlines: stylesheet, the Python sources of the real auditor package (run in-browser by Pyodide), the 8 synthetic demo datasets,
the engine worker, Preact + htm (vendored), Lucide icons and the app code. The only runtime downloads are the Pyodide runtime
(jsDelivr), pypdf (PyPI, for PDF evidence) and web fonts.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = HERE / "src"
OUT = ROOT / "docs" / "index.html"
APP_ORDER = ["core.js", "ui.js", "actions.js", "views_run.js", "views_inputs.js", "views_data.js", "views_vault.js", "app.js"]


def js_safe(s: str) -> str:
    """Make JSON safe inside <script>: no raw '<' (blocks '</script>' and '<!--')."""
    return s.replace("<", "\u003c")


def collect_python() -> dict:
    src = {"service.py": (HERE / "py" / "service.py").read_text(encoding="utf-8"), "browser_io.py": (HERE / "py" / "browser_io.py").read_text(encoding="utf-8")}
    for p in sorted((ROOT / "code" / "auditor").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        src["code/" + p.relative_to(ROOT / "code").as_posix()] = p.read_text(encoding="utf-8")
    for n in ("main.py", "link_recovery.py"):
        src["code/evaluation/" + n] = (ROOT / "code" / "evaluation" / n).read_text(encoding="utf-8")
    return src


def collect_demo() -> dict:
    demo = {}
    base = ROOT / "code" / "evaluation" / "custom_cases"
    for d in sorted(p for p in base.iterdir() if (p / "expected_output.csv").exists()):
        files = {}
        for f in sorted(d.rglob("*")):
            if f.is_file():
                files[f.relative_to(d).as_posix()] = f.read_text(encoding="utf-8")
        demo[d.name] = files
    return demo


def collect_icons() -> dict:
    icons = {}
    for f in sorted((HERE / "vendor" / "icons").glob("*.svg")):
        t = f.read_text(encoding="utf-8")
        inner = re.sub(r"<!--.*?-->", "", t, flags=re.S)
        inner = re.sub(r"^.*?<svg[^>]*>", "", inner, flags=re.S)
        inner = re.sub(r"</svg>\s*$", "", inner.strip())
        icons[f.stem] = re.sub(r"\s+", " ", inner).strip()
    return icons


def main():
    css = (SRC / "styles.css").read_text(encoding="utf-8")
    vendor = "\n".join((HERE / "vendor" / n).read_text(encoding="utf-8") for n in ("preact.js", "hooks.js", "htm.js"))
    app = "\n".join((SRC / n).read_text(encoding="utf-8") for n in APP_ORDER)
    worker = (SRC / "worker.js").read_text(encoding="utf-8")
    assert "</script" not in worker.lower() and "</script" not in app.lower() and "</script" not in vendor.lower(), "unsafe </script> in inlined code"
    fav = "data:image/svg+xml," + "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%233b82f6' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E" + \
          "%3Cpath d='M9 10h.01M15 10h.01M12 2a8 8 0 0 0-8 8v12l3-3 2.5 2.5L12 19l2.5 2.5L17 19l3 3V10a8 8 0 0 0-8-8z'/%3E%3C/svg%3E"
    tpl = (SRC / "template.html").read_text(encoding="utf-8")
    html = (tpl.replace("{{BUILD}}", time.strftime("%Y-%m-%d")).replace("{{FAVICON}}", fav).replace("{{CSS}}", css)
            .replace("{{PYSRC}}", js_safe(json.dumps(collect_python(), ensure_ascii=True)))
            .replace("{{DEMO}}", js_safe(json.dumps(collect_demo(), ensure_ascii=True)))
            .replace("{{WORKER}}", worker).replace("{{VENDOR}}", vendor)
            .replace("{{ICONS}}", json.dumps(collect_icons())).replace("{{APP}}", app))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    (OUT.parent / ".nojekyll").write_text("", encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
