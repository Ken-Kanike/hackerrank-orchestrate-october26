"""Compare two output.csv files case by case: python code/tools/diff_outputs.py A.csv B.csv

Prints, for every changed case, the status change and the steps added/removed (keyed by phase, system, resource, operation,
evidence). Exit code 0 always; the last line is the number of changed cases.
"""
import csv
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load(p):
    return {r["case_id"]: r for r in csv.DictReader(open(p, encoding="utf-8"))}


def keyset(r):
    return {(s["phase"], s["system_id"], s["resource_id"], s["operation"], s["evidence_id"]) for s in json.loads(r["steps_json"])}


def main(a, b):
    A, B = load(a), load(b)
    changed = 0
    for cid in sorted(set(A) | set(B), key=lambda c: [int(x) if x.isdigit() else x for x in __import__("re").split(r"(\d+)", c)]):
        ra, rb = A.get(cid), B.get(cid)
        if ra is None or rb is None:
            print(f"{cid}: only in {'B' if ra is None else 'A'}"); changed += 1; continue
        ka, kb = keyset(ra), keyset(rb)
        order_changed = ra["steps_json"] != rb["steps_json"] and ka == kb
        if ra["deletion_status"] == rb["deletion_status"] and ka == kb and not order_changed:
            continue
        changed += 1
        print(f"== {cid}: {ra['deletion_status']} -> {rb['deletion_status']}" + ("  (order/step_no only)" if order_changed else ""))
        for k in sorted(ka - kb): print("   - removed", k)
        for k in sorted(kb - ka): print("   + added  ", k)
    print(f"changed cases: {changed}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
