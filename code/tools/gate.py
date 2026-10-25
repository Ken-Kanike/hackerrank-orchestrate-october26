"""Regression gate: python code/tools/gate.py  (offline; must pass after every change).

Runs the sample evaluation, the unit tests, and a full 518-row run, then diffs against the frozen baseline output.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def sh(*args):
    r = subprocess.run([PY, *args], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    return r.returncode, r.stdout + r.stderr


def main():
    ok = True
    code, out = sh("code/evaluation/main.py", "--mode", "offline")
    import json
    m = json.loads(out[out.index(chr(10) + "{") + 1 : out.rindex("}") + 1] if not out.startswith("{") else out[: out.rindex("}") + 1])
    gate = m["status_acc"] == 1.0 and m["precision"] >= 0.98 and m["recall"] >= 0.965
    print(f"[samples] status {m['status']}/{m['n']} precision {m['precision']} recall {m['recall']} exact {m['exact']}  -> {'OK' if gate else 'FAIL'}")
    ok &= gate
    code, out = sh("-m", "unittest", "discover", "-s", "code/tests", "-t", "code")
    print("[unit tests]", "OK" if code == 0 else "FAIL\n" + out[-1500:]); ok &= code == 0
    code, out = sh("code/evaluation/custom_cases/test_custom_cases.py")
    print("[custom cases]", "OK" if code == 0 else "FAIL\n" + out[-1500:]); ok &= code == 0
    code, out = sh("code/evaluation/custom_cases/run_custom_cases.py")
    print("[end-to-end custom datasets]", "OK" if code == 0 else "FAIL" + chr(10) + out[-1500:]); ok &= code == 0
    tmp = Path(tempfile.gettempdir()) / "gate_out.csv"
    code, out = sh("code/main.py", "--mode", "offline", "--out", str(tmp))
    print([l for l in out.splitlines() if l.startswith(("wrote", "validation"))])
    flags0 = "validation flags: 0" in out and "wrote" in out
    ok &= flags0
    code, out = sh("code/tools/diff_outputs.py", "code/evaluation/accepted_output.csv", str(tmp))
    print("[diff vs accepted]", out.splitlines()[-1] if out else "?")
    print("GATE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
