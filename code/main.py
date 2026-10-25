"""Entry point: python code/main.py [--mode offline|hybrid] [--out output.csv]

Reads dataset/deletion_requests.csv, writes the 518-row output.csv at the repo root.
Modes: hybrid (default) uses LLM providers found in .env for intent cross-check and screenshot reading, falling back to
deterministic logic when none work; offline never calls an LLM.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auditor.config import DATASET, OUTPUT_CSV  # noqa: E402
from auditor.llm.router import Router  # noqa: E402
from auditor.pipeline import read_requests, run, write_csv, write_run_artifacts  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["offline", "hybrid"], default="hybrid")
    ap.add_argument("--out", default=str(OUTPUT_CSV))
    ap.add_argument("--refresh-llm", action="store_true", help="ignore cached LLM answers and call the providers again")
    ap.add_argument("--no-vision", action="store_true")
    ap.add_argument("--data", default=str(DATASET), help="dataset directory (default: dataset/)")
    ap.add_argument("--sort", choices=["numeric", "lexicographic"], default="numeric",
                    help="row order: numeric keeps the input order (case_33 < case_100); lexicographic sorts the id strings")
    ap.add_argument("--no-trace", action="store_true", help="do not write code/runs/<run_id>/trace.jsonl + review.md")
    a = ap.parse_args()
    if a.refresh_llm:
        import os
        os.environ['LLM_REFRESH'] = '1'
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    data = Path(a.data)
    router = Router(enabled=a.mode == "hybrid")
    print(f"LLM providers: {router.providers or 'none (offline deterministic)'}")
    reqs = read_requests("deletion_requests.csv", data)
    samples = data / "sample_deletion_requests.csv"
    pool = reqs + (read_requests("sample_deletion_requests.csv", data) if samples.exists() else [])
    rows, report, _, _ = run(reqs, pool, router, data, use_vision=not a.no_vision)
    assert len(rows) == len(reqs) == len({r["case_id"] for r in rows}), "row count mismatch"
    if a.sort == "lexicographic":
        rows.sort(key=lambda r: r["case_id"])
    write_csv(rows, Path(a.out))
    print(f"wrote {a.out}: {len(rows)} rows {dict(Counter(r['deletion_status'] for r in rows))}")
    print(f"validation flags: {len(report['flags'])}; ambiguous links: {len(report['ambiguous'])}")
    print(f"vision cross-check mismatches: {report['vision_mismatch']}")
    if not a.no_trace:
        run_dir = Path(__file__).resolve().parent / "runs" / router.run_id
        write_run_artifacts(report, run_dir)
        meta = {"run_id": router.run_id, "mode": a.mode, "providers": router.providers, "out": str(a.out), "cases": len(rows),
                "status": dict(Counter(r["deletion_status"] for r in rows)), "validator_flags": len(report["flags"]),
                "ambiguous_links": len(report["ambiguous"]), "llm_calls_fresh": router.calls, "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        print(f"trace + review report: {run_dir}")
    for cid, errs in report["flags"][:10]:
        print("  FLAG", cid, errs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
