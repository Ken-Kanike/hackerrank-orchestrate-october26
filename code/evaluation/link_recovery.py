"""Label-free evaluation of the activity-based account linker (limitations A2 / D1 / G1).

For cases whose account is proven by identity (the account record carries the subject's identifiers) we hide that link, let the
linker re-derive the account from workflow activity alone, and compare with the proven account. No gold file is read.
Repeated k-fold hiding keeps the competition realistic (only 1/k of the proven accounts are free at a time).

Usage: python code/evaluation/link_recovery.py [--folds 4] [--repeats 3]
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from auditor import config  # noqa: E402
from auditor.config import DATASET  # noqa: E402
from auditor.engine import Engine  # noqa: E402
from auditor.evidence import load_activity, load_manifest, load_observations, prefix  # noqa: E402
from auditor.intent import classify_many  # noqa: E402
from auditor.pipeline import read_requests  # noqa: E402


def recover(folds: int, repeats: int, seed: int = 7, data: Path = DATASET, progress=None):
    reqs = read_requests("deletion_requests.csv", data) + (read_requests("sample_deletion_requests.csv", data) if (data / "sample_deletion_requests.csv").exists() else [])
    by_text = classify_many([c["request_text"] for c in reqs])
    cases = [c for c in reqs if by_text[c["request_text"]]["final"] == "DELETE"]
    manifest, acts = load_manifest(data), load_activity(data)
    obs = load_observations(data, manifest, acts)
    base = Engine(data, manifest, acts, obs); base.link_all(cases)
    proven = {cid: next(r for r in rids if prefix(r) == "account" and r in base.acc_event)
              for cid, (_, rids, _) in base.info.items() if any(prefix(r) == "account" and r in base.acc_event for r in rids)}
    rng = random.Random(seed); res = []
    for _ in range(repeats):
        ids = sorted(proven); rng.shuffle(ids)
        for k in range(folds):
            hide = set(ids[k::folds])
            e = Engine(data, manifest, acts, obs); e.link_all(cases, hide_accounts=hide)
            ok = sum(1 for cid in hide if proven[cid] in e.extra.get(cid, set()))
            amb = sum(1 for cid in hide if cid in e.ambiguous)
            res.append((len(hide), ok, amb))
            if progress:
                progress(len(res), repeats * folds)
    return len(proven), res


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--folds", type=int, default=4); ap.add_argument("--repeats", type=int, default=3)
    a = ap.parse_args()
    n, res = recover(a.folds, a.repeats)
    acc = [ok / h for h, ok, _ in res]; amb = [m / h for h, _, m in res]
    print(f"identity-proven accounts: {n}; alignment={'on' if config.USE_RUN_ALIGNMENT else 'off'}; tie-break={config.TIE_BREAK}")
    print(f"recovery accuracy: mean {statistics.mean(acc):.4f} +- {statistics.pstdev(acc):.4f} over {len(res)} folds; "
          f"residual-ambiguity rate {statistics.mean(amb):.4f}")


if __name__ == "__main__":
    main()
