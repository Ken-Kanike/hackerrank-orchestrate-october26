"""Run every custom dataset through the real pipeline and compare with its hand-written expected_output.csv.

python code/evaluation/custom_cases/run_custom_cases.py [-v]     (exit code 1 on any mismatch)
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1])); sys.path.insert(0, str(HERE.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from auditor.llm.router import Router  # noqa: E402
from auditor.pipeline import read_requests, run  # noqa: E402
from main import load_gold, score  # noqa: E402


def run_all(verbose=False):
    results = []
    for d in sorted(p for p in HERE.iterdir() if (p / "expected_output.csv").exists()):
        reqs = read_requests("deletion_requests.csv", d)
        rows, report, eng, _ = run(reqs, reqs, Router(enabled=False), d, use_vision=False, log=lambda *a: None)
        gold = load_gold(d / "expected_output.csv")
        m = score(rows, gold, verbose, eng)
        exact = all(r["deletion_status"] == gold[r["case_id"]]["deletion_status"] and json.loads(r["steps_json"]) == json.loads(gold[r["case_id"]]["steps_json"]) for r in rows)
        results.append((d.name, len(rows), m["status_acc"], m["precision"], m["recall"], m["exact"], exact, report["flags"]))
    return results


def main():
    res = run_all("-v" in sys.argv)
    print(f"{'dataset':34} {'cases':>5} {'status':>6} {'prec':>5} {'recall':>6} {'exact':>5}  validator")
    for name, n, st, p, r, ex, ok, flags in res:
        print(f"{name:34} {n:>5} {st:>6.2f} {p:>5.2f} {r:>6.2f} {ex:>3}/{n:<2} {'PASS' if ok else 'FAIL'} {flags if flags else ''}")
    return 0 if all(r[6] for r in res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
