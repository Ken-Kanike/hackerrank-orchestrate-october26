"""Ablation table: toggle one design element at a time and measure sample metrics + how many of the 518 outputs change.

Usage: python code/evaluation/ablation.py [--md code/evaluation/ablation.md]
Each row = full pipeline (offline) with one config flag flipped. 'changed cases' diffs the 518-row output against the default config.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from auditor import config  # noqa: E402
from auditor.config import DATASET  # noqa: E402
from auditor.llm.router import Router  # noqa: E402
from auditor.pipeline import read_requests, run  # noqa: E402
from main import load_gold, score  # noqa: E402

CONFIGS = [("default (all on)", {}),
           ("no run-alignment (USE_RUN_ALIGNMENT=0)", {"USE_RUN_ALIGNMENT": False}),
           ("lenient time (STRICT_TIME=0)", {"STRICT_TIME": False}),
           ("no lineage (USE_LINEAGE=0)", {"USE_LINEAGE": False}),
           ("no activity checks (USE_ACTIVITY_CHECKS=0)", {"USE_ACTIVITY_CHECKS": False})]


def run_once(flags: dict):
    old = {k: getattr(config, k) for k in flags}
    for k, v in flags.items():
        setattr(config, k, v)
    try:
        router = Router(enabled=False)
        samples, reqs = read_requests("sample_deletion_requests.csv"), read_requests("deletion_requests.csv")
        rows, rep, eng, _ = run(samples, reqs + samples, router, DATASET, use_vision=False, log=lambda *a: None)
        m = score(rows, load_gold(DATASET / "sample_output.csv"), False, eng)
        full, rep2, _, _ = run(reqs, reqs + samples, router, DATASET, use_vision=False, log=lambda *a: None)
        return m, {r["case_id"]: r for r in full}, len(rep2["ambiguous"]), len(rep2["flags"])
    finally:
        for k, v in old.items():
            setattr(config, k, v)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--md", default=None)
    a = ap.parse_args()
    base_rows, lines = None, ["| configuration | status acc | step precision | step recall | exact seq | changed cases (of 518) | ambiguous links | validator flags |",
                              "|---|---|---|---|---|---|---|---|"]
    for name, flags in CONFIGS:
        m, full, amb, nflags = run_once(flags)
        if base_rows is None:
            base_rows = full
        changed = sum(1 for cid, r in full.items() if r["steps_json"] != base_rows[cid]["steps_json"] or r["deletion_status"] != base_rows[cid]["deletion_status"])
        lines.append(f"| {name} | {m['status_acc']:.3f} | {m['precision']:.3f} | {m['recall']:.3f} | {m['exact']}/{m['n']} | {changed} | {amb} | {nflags} |")
        print(lines[-1])
    if a.md:
        Path(a.md).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
