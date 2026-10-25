"""End-to-end pipeline: requests -> rows(case_id, deletion_status, steps_json)."""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

from . import config, events
from .config import DATASET
from .corroborate import corroborate
from .engine import Directory, Engine
from .ghost import build_index, clean_leaks, sweep
from .evidence import load_activity, load_manifest, load_observations
from .intent import classify_many
from .llm.investigator import investigate
from .llm.router import Router
from .validate import validate_row


INFO_FLAGS = {"category_inferred", "retention_unknown"}      # expected for resources seen only through logs; not actionable


def natural(cid: str):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", cid)]


def read_requests(name: str, data: Path = DATASET) -> list[dict]:
    return list(csv.DictReader(open(data / name, encoding="utf-8")))


def build_engine(data: Path, router: Router, use_vision: bool = True):
    manifest, acts = load_manifest(data), load_activity(data)
    vision = None
    if use_vision and router.available:
        from .vision import extract_all
        with events.stage("vision") as st:
            vision = extract_all(data, manifest, router)
            st["images"] = len(vision)
    with events.stage("evidence") as st:
        obs = load_observations(data, manifest, acts, vision)
        st.update(files=len(manifest), observations=len(obs), activities=len(acts))
    with events.stage("catalog") as st:
        obs, catalog_flags = corroborate(obs, vision, Directory(data))
        st["flags"] = len(catalog_flags)
    eng = Engine(data, manifest, acts, obs)
    eng.vision = vision or {}
    eng.catalog_flags = catalog_flags
    return eng


def run(requests: list[dict], pool: list[dict], router: Router, data: Path = DATASET, use_vision: bool = True, log=print, learn_exclude=frozenset()):
    """requests: cases to answer. pool: all participant-visible cases (used for global resource-link constraints)."""
    eng = build_engine(data, router, use_vision)
    with events.stage("intent") as st:
        by_text = classify_many([c["request_text"] for c in pool], router)
        intents = {c["case_id"]: by_text[c["request_text"]] for c in pool}
        delete_cases = [c for c in pool if intents[c["case_id"]]["final"] == "DELETE"]
        st.update(texts=len(by_text), deletion_cases=len(delete_cases), llm_answered=sum(1 for v in by_text.values() if v["llm"] is not None),
                  disagreements=sum(1 for v in by_text.values() if v["disagree"]))
    with events.stage("linking") as st:
        eng.link_all(delete_cases, learn_exclude)
        st.update(cases=len(delete_cases), ambiguous=len(eng.ambiguous))
    investigator = {}
    if router.available and config.USE_INVESTIGATOR:       # flagged cases only; advisory unless config.INVESTIGATOR_APPLY
        wanted = {c["case_id"] for c in requests}
        by_id = {c["case_id"]: c for c in pool}
        todo = sorted(eng.ambiguous & wanted, key=natural)
        with events.stage("investigator", total=len(todo)) as st:
            for cid in todo:
                cands = eng.account_cands.get((cid, "account"), [])
                current = next((r for r in eng.extra.get(cid, ()) if r.startswith("account")), None)
                res = investigate(eng, by_id[cid], cands, router, current)
                if not res:
                    continue
                investigator[cid] = res
                taken = {r for k, rs in eng.extra.items() if k != cid for r in rs}
                if config.INVESTIGATOR_APPLY and res["choose"] and res["choose"] != current and res["choose"] not in taken:
                    eng.extra[cid] = (eng.extra[cid] - {current}) | {res["choose"]}
            st.update(investigated=len(investigator), agreed=sum(1 for r in investigator.values() if r["agrees"]))
    with events.stage("ghost") as st:
        ghost_index = build_index(data, eng.manifest) if config.USE_GHOST_SWEEP else None
        st["indexed_identifiers"] = len(ghost_index) if ghost_index is not None else 0
    rows, report = [], {"ambiguous": [], "flags": [], "vision_mismatch": [], "catalog": eng.catalog_flags, "trace": {}, "investigator": investigator,
                      "clean_leaks": clean_leaks(ghost_index, eng.obs) if ghost_index is not None else []}
    for o in eng.obs:      # screenshot cross-check: the catalog-linked resource must be visible in the image
        v = eng.vision.get(o.fid)
        if o.kind == "catalog" and v and v["ids"] and o.rid not in v["ids"]:
            report["vision_mismatch"].append((o.fid, o.rid, v["ids"]))
    ordered = sorted(requests, key=lambda c: natural(c["case_id"]))
    events.emit("stage_start", id="solve", total=len(ordered))
    import time as _time
    _t0 = _time.perf_counter()
    for n, c in enumerate(ordered, 1):
        cid = c["case_id"]
        if n % 10 == 0 or n == len(ordered):
            events.emit("progress", stage="solve", done=n, total=len(ordered))
        if intents[cid]["final"] != "DELETE":
            rows.append({"case_id": cid, "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"})
            continue
        r = eng.solve(c)
        if cid in eng.ambiguous:
            report["ambiguous"].append(cid)
        report["trace"][cid] = trace_entry(c, r, intents[cid], eng)
        if ghost_index is not None:
            keys = eng.dir.users[r["uid"]]["keys"]
            foreign = {rid for k in keys for u in ghost_index.get(k, ()) for rid in u["rids"] if eng.rid_owners.get(rid, set()) - {r["uid"]}}
            hits = sweep(ghost_index, keys, c["audit_at"], set(r["resources"]), foreign)
            if hits:
                t = report["trace"][cid]; t["ghost_hits"] = hits[:10]; t["flags"] = sorted(set(t["flags"]) | {"ghost_hit"})
        row = {"case_id": cid, "deletion_status": r["status"], "steps_json": json.dumps(r["steps"], ensure_ascii=False, separators=(",", ":"))}
        errs = validate_row(row, eng.manifest, c, eng.obs_index, eng.acts_by_id)
        if errs:
            report["flags"].append((cid, errs)); log(f"[validate] {cid}: {errs}")
        rows.append(row)
    events.emit("stage_end", id="solve", ms=round((_time.perf_counter() - _t0) * 1000), ok=True, cases=len(ordered),
                incomplete=sum(1 for r in rows if r["deletion_status"] == "INCOMPLETE"), validator_flags=len(report["flags"]))
    return rows, report, eng, intents


def trace_entry(c: dict, r: dict, intent: dict, eng: Engine) -> dict:
    """Audit trail for one case: how the subject was resolved, why each resource is linked, what decided its state, which rule applied."""
    res = []
    for rid, (sysid, st, ev, kind, _) in sorted(r["resources"].items()):
        d = r["decisions"][rid]
        res.append({"resource_id": rid, "system_id": sysid, "state": st, "evidence_id": ev, "link": r["reason"].get(rid),
                    "category": d.category, "rule_id": d.rule_id, "action": d.action, "violation": d.violation, "flags": d.flags})
    flags = sorted({f for x in res for f in x["flags"]} | ({"ambiguous_link"} if c["case_id"] in eng.ambiguous else set())
                   | ({"intent_disagreement"} if intent.get("disagree") else set()))
    return {"case_id": c["case_id"], "user_id": r["uid"], "status": r["status"], "intent": {k: intent[k] for k in ("rule", "strength", "llm", "final")},
            "resources": res, "flags": flags}


def write_run_artifacts(report: dict, run_dir: Path) -> None:
    """trace.jsonl (every case) + review.md (flagged cases only)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "trace.jsonl", "w", encoding="utf-8") as f:
        for cid in sorted(report["trace"], key=natural):
            f.write(json.dumps(report["trace"][cid], ensure_ascii=False) + chr(10))
    flagged = [t for cid, t in sorted(report["trace"].items(), key=lambda kv: natural(kv[0])) if set(t["flags"]) - INFO_FLAGS]
    from collections import Counter
    cnt = Counter(fl for t in flagged for fl in t["flags"])
    allcnt = Counter(fl for t in report["trace"].values() for fl in t["flags"])
    lines = ["# Review report", "", f"{len(report['trace'])} audited cases, {len(flagged)} with actionable review flags "
             f"(informational flags {sorted(INFO_FLAGS)} are counted but do not list the case).", "",
             "| flag | cases |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(allcnt.items())]
    if report["catalog"]:
        lines += ["", "## Data-catalog links needing review", ""] + [f"- `{x['fid']}` / `{x['rid']}`: **{x['flag']}** - {x['detail']}" for x in report["catalog"]]
    if report.get("investigator"):
        agree = sum(1 for r in report["investigator"].values() if r["agrees"])
        lines += ["", f"Investigator agreed with the deterministic choice in {agree} of {len(report['investigator'])} cases (its rationale re-derives the engine's "
                      "one-resource-one-case elimination; it adds explanation, not independent evidence)."]
        lines += ["", "## Investigator notes (advisory: model-written rationale, not verified, output unchanged)", ""] + [
            f"- **{cid}**: chose `{r['choose']}` after {r['turns']} turns ({'agrees with' if r['agrees'] else 'differs from'} the engine) - {r['reason']}"
            for cid, r in sorted(report["investigator"].items(), key=lambda kv: natural(kv[0]))]
    lines += ["", f"Redaction check: {len(report.get('clean_leaks', []))} records classified CLEAN still carry a phone/hash identifier."]
    lines += ["", "## Flagged cases", ""]
    for t in flagged:
        lines.append(f"- **{t['case_id']}** ({t['status']}): {', '.join(sorted(set(t['flags']) - INFO_FLAGS))}")
    (run_dir / "review.md").write_text(chr(10).join(lines) + chr(10), encoding="utf-8")


def write_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["case_id", "deletion_status", "steps_json"], lineterminator="\n")
        w.writeheader(); w.writerows(rows)
