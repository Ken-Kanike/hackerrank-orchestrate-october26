"""Build code.zip (README.md + code/) without caches, secrets, datasets, runs or nested archives.

python code/package.py [--out code.zip]
Prints the archive listing and total size. Fails if a forbidden path would be included.
"""
import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE_DIRS = {".cache", "runs", "__pycache__", ".venv", "venv", "dataset", ".git"}
EXCLUDE_NAMES = {".env", "log.txt"}
EXCLUDE_SUFFIX = {".pyc", ".zip"}
EXCLUDE_FILES = {"_gate_out.csv", "_off.csv", "_hybrid.csv"}


def include(p: Path) -> bool:
    rel = p.relative_to(ROOT)
    return not (set(rel.parts) & EXCLUDE_DIRS or p.name in EXCLUDE_NAMES or p.suffix in EXCLUDE_SUFFIX or p.name in EXCLUDE_FILES)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default=str(ROOT / "code.zip"))
    a = ap.parse_args()
    files = [ROOT / "README.md"] + sorted(p for p in (ROOT / "code").rglob("*") if p.is_file() and include(p))
    bad = [f for f in files if f.name == ".env" or "dataset" in f.relative_to(ROOT).parts]
    if bad:
        sys.exit(f"refusing to package: {bad}")
    with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.relative_to(ROOT).as_posix())
        # the task asks for evaluation/ at the archive root as well as code/evaluation/
        for f in sorted((ROOT / "code" / "evaluation").glob("*.md")):
            z.write(f, "evaluation/" + f.name)
    with zipfile.ZipFile(a.out) as z:
        for i in z.infolist():
            print(f"{i.file_size:>9}  {i.filename}")
    print(f"\n{len(files)} files -> {a.out} ({Path(a.out).stat().st_size / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
