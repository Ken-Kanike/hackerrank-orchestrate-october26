"""Evaluation harness: score predictions against a gold CSV (default: the 32 public samples).

Usage:
  python code/evaluation/main.py [--mode offline|hybrid] [-v] [--record "description"]
  python code/evaluation/main.py --data code/evaluation/custom_cases/<name> --gold expected_output.csv
  python code/evaluation/main.py --folds 2 --repeats 5          # held-out estimate (see run_folds)

Metrics: status accuracy; step precision/recall/F1 on (phase, system, resource, operation); per-field accuracy on steps aligned by
(resource_id, phase); position accuracy; sequence metrics (exact array match, normalised Kendall tau, LCS ratio); and the
'unreachable' ceiling (gold resources that appear nowhere in participant-visible data).
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import subprocess
import sys
import time
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from auditor.config import DATASET  # noqa: E402
from auditor.llm.router import Router  # noqa: E402
from auditor.pipeline import read_requests, run  # noqa: E402

EXPERIMENTS = Path(__file__).resolve().parent / "experiments.jsonl"
FIELDS = ("system_id", "operation", "state", "evidence_id")


def lcs_len(a: list, b: list) -> int:
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[-1]))
        prev = cur
    return prev[-1]


def kendall_norm(order_p: list, order_g: list) -> float | None:
    """Normalised Kendall tau in [0,1] over the keys both sequences contain (1 = same relative order)."""
    common = [k for k in order_g if k in set(order_p)]
    if len(common) < 2:
        return None
    pos = {k: i for i, k in enumerate(order_p)}
    pairs = list(combinations(common, 2))
    conc = sum(1 for a, b in pairs if pos[a] < pos[b])
    return conc / len(pairs)


def score(rows, gold, verbose=False, eng=None):
    m = dict(n=0, status=0, exact=0, tp=0, np=0, ng=0, unreach=0, pos_ok=0, pos_total=0, lcs=0, lcs_total=0)
    fld = {f: 0 for f in FIELDS}
    aligned = 0
    taus = []
    for r in rows:
        g = gold[r["case_id"]]; m["n"] += 1
        ps, gs = json.loads(r["steps_json"]), json.loads(g["steps_json"])
        m["status"] += r["deletion_status"] == g["deletion_status"]
        m["exact"] += ps == gs and r["deletion_status"] == g["deletion_status"]
        key = lambda s: (s["phase"], s["system_id"], s["resource_id"], s["operation"])
        pk, gk = {key(s): s for s in ps}, {key(s): s for s in gs}
        m["np"] += len(pk); m["ng"] += len(gk); m["tp"] += len(set(pk) & set(gk))
        # alignment by (resource_id, phase): compare each field separately
        pa, ga = {(s["resource_id"], s["phase"]): s for s in ps}, {(s["resource_id"], s["phase"]): s for s in gs}
        for k in set(pa) & set(ga):
            aligned += 1
            for f in FIELDS:
                fld[f] += pa[k][f] == ga[k][f]
            m["pos_total"] += 1; m["pos_ok"] += pa[k]["step_no"] == ga[k]["step_no"]
        order_p = [(s["resource_id"], s["phase"]) for s in ps]; order_g = [(s["resource_id"], s["phase"]) for s in gs]
        t = kendall_norm(order_p, order_g)
        if t is not None:
            taus.append(t)
        m["lcs"] += lcs_len([key(s) for s in ps], [key(s) for s in gs]); m["lcs_total"] += len(gs)
        if eng:
            for k in set(gk) - set(pk):
                if not eng.by_rid.get(k[2]) and not any(a["resource_id"] == k[2] for a in eng.acts):
                    m["unreach"] += 1
        if verbose and (ps != gs):
            print("==", r["case_id"], r["deletion_status"], "gold", g["deletion_status"])
            for k in sorted(set(gk) - set(pk)): print("   MISSING", k)
            for k in sorted(set(pk) - set(gk)): print("   EXTRA  ", k)
            for k in sorted(set(pk) & set(gk)):
                if pk[k]["evidence_id"] != gk[k]["evidence_id"]: print("   EVID", k, pk[k]["evidence_id"], "gold", gk[k]["evidence_id"])
    p = m["tp"] / max(m["np"], 1); rec = m["tp"] / max(m["ng"], 1)
    m.update(precision=p, recall=rec, f1=2 * p * rec / max(p + rec, 1e-9), status_acc=m["status"] / m["n"],
             exact_acc=m["exact"] / m["n"], aligned_steps=aligned,
             field_acc={f: fld[f] / max(aligned, 1) for f in FIELDS},
             position_acc=m["pos_ok"] / max(m["pos_total"], 1),
             kendall_tau=sum(taus) / len(taus) if taus else 1.0,
             lcs_ratio=m["lcs"] / max(m["lcs_total"], 1))
    return m


def rounded(m: dict) -> dict:
    out = {}
    for k, v in m.items():
        out[k] = {a: round(b, 4) for a, b in v.items()} if isinstance(v, dict) else (round(v, 4) if isinstance(v, float) else v)
    return out


def load_gold(path: Path) -> dict:
    return {r["case_id"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def run_folds(samples, pool, gold, data, folds: int, repeats: int):
    """Repeated k-fold. Every learned parameter (workflow-run alignment) is fitted on evidence links of the *training* cases only
    (pool minus the held-out samples); no parameter ever reads gold labels. Reports mean +- std over the held-out halves."""
    rng = random.Random(20261025)
    router = Router(enabled=False)
    table = []
    for rep in range(repeats):
        order = [c["case_id"] for c in samples]; rng.shuffle(order)
        parts = [order[i::folds] for i in range(folds)]
        for fi, test_ids in enumerate(parts):
            test = set(test_ids)
            rows, _, eng, _ = run([c for c in samples if c["case_id"] in test], pool, router, data, use_vision=False,
                                  learn_exclude=test, log=lambda *a: None)
            m = score(rows, gold, False, eng)
            table.append((rep, fi, m))
    return table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="offline"); ap.add_argument("-v", action="store_true")
    ap.add_argument("--data", default=str(DATASET), help="dataset directory (default: dataset/)")
    ap.add_argument("--gold", default="sample_output.csv", help="gold CSV inside --data")
    ap.add_argument("--requests", default=None, help="requests CSV to score (default: sample_deletion_requests.csv, or deletion_requests.csv for custom dirs)")
    ap.add_argument("--record", default=None, help="append this run's metrics to experiments.jsonl with the given description")
    ap.add_argument("--refresh-llm", action="store_true", help="ignore cached LLM answers and call the providers again")
    ap.add_argument("--folds", type=int, default=0); ap.add_argument("--repeats", type=int, default=5)
    a = ap.parse_args()
    if a.refresh_llm:
        import os
        os.environ['LLM_REFRESH'] = '1'
    data = Path(a.data)
    router = Router(enabled=a.mode == "hybrid")
    custom = data.resolve() != DATASET.resolve()
    req_name = a.requests or ("deletion_requests.csv" if custom else "sample_deletion_requests.csv")
    samples = read_requests(req_name, data)
    pool = samples if custom else read_requests("deletion_requests.csv", data) + samples
    gold = load_gold(data / a.gold)
    if a.folds:
        table = run_folds(samples, pool, gold, data, a.folds, a.repeats)
        print(f"{'rep':>3} {'fold':>4} {'n':>3} {'status':>7} {'prec':>6} {'recall':>6} {'f1':>6} {'exact':>6}")
        for rep, fi, m in table:
            print(f"{rep:>3} {fi:>4} {m['n']:>3} {m['status_acc']:>7.3f} {m['precision']:>6.3f} {m['recall']:>6.3f} {m['f1']:>6.3f} {m['exact_acc']:>6.3f}")
        for k in ("status_acc", "precision", "recall", "f1", "exact_acc"):
            v = [m[k] for _, _, m in table]
            print(f"{k:>10}: mean {statistics.mean(v):.4f} +- {statistics.pstdev(v):.4f}")
        return
    rows, report, eng, _ = run(samples, pool, router, data)
    m = score(rows, gold, a.v, eng)
    print(json.dumps(rounded(m), indent=1))
    print("validation flags:", report["flags"][:5])
    if a.record:
        try:
            ds = subprocess.run(["git", "diff", "--shortstat"], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2]).stdout.strip()
        except Exception:
            ds = ""
        with open(EXPERIMENTS, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "desc": a.record, "git_diff_stat": ds,
                                "metrics": rounded(m)}, ensure_ascii=False) + "\n")
        print("recorded ->", EXPERIMENTS)


if __name__ == "__main__":
    main()
