"""Job API used by the web UI (runs in Pyodide, but is plain CPython-compatible so it can be tested locally).

Every function takes and returns JSON strings/dicts. The audit itself is `auditor.pipeline.run` - the same code path as the CLI - wrapped
with: runtime flag overrides, event streaming (auditor.events), scoring against an optional gold file, per-case diffs and artifact export.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent                       # /app in the browser; webui/py when run locally
CODE = ROOT / "code" if (ROOT / "code").exists() else ROOT.parents[1] / "code"
sys.path.insert(0, str(CODE))

from auditor import config, events  # noqa: E402
from auditor.llm.router import PRICES, Router, usage_summary  # noqa: E402
from auditor.pipeline import INFO_FLAGS, natural, read_requests, run, write_csv, write_run_artifacts  # noqa: E402

FLAG_DEFAULTS = {"STRICT_TIME": True, "USE_LINEAGE": True, "USE_ACTIVITY_CHECKS": True, "USE_RUN_ALIGNMENT": True, "USE_GHOST_SWEEP": True,
                 "PARTITION_SINGLE_CASE_USERS_ONLY": True, "USE_INVESTIGATOR": True, "INVESTIGATOR_APPLY": False}
ENV_KEYS = ("ANTHROPIC", "OPENAI", "GEMINI", "GROQ", "CUSTOM")


def _load_eval():
    spec = importlib.util.spec_from_file_location("eval_main", CODE / "evaluation" / "main.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


_EVAL = None


def eval_main():
    global _EVAL
    if _EVAL is None:
        _EVAL = _load_eval()
    return _EVAL


# ----------------------------------------------------------------------------------------------- environment / vault bridge
def set_env(env_json: str) -> str:
    """Install provider credentials for this session only (memory). Keys never touch disk or logs."""
    env = json.loads(env_json)
    for pre in ENV_KEYS:
        for suffix in ("_API_KEY", "_BASE_URL", "_MODEL1", "_MODEL2", "_VISION_MODEL"):
            os.environ.pop(pre + suffix, None)
        for i in range(1, 21):
            os.environ.pop(f"{pre}_API_KEY_{i}", None)
    os.environ.pop("LLM_PROVIDER_ORDER", None)
    for k, v in env.items():
        if v:
            os.environ[k] = str(v)
    return json.dumps({"providers": Router(enabled=True).providers})


def providers_json() -> str:
    return json.dumps({"providers": Router(enabled=True).providers})


# ----------------------------------------------------------------------------------------------- dataset helpers
def unzip_to(zip_path: str, out_dir: str) -> str:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        # strip a single top-level folder (e.g. dataset/...)
        tops = {n.split("/")[0] for n in names}
        strip = len(tops) == 1 and all("/" in n for n in names)
        for n in names:
            rel = n.split("/", 1)[1] if strip else n
            t = out / rel; t.parent.mkdir(parents=True, exist_ok=True); t.write_bytes(z.read(n))
    return json.dumps({"files": len(names)})


def dataset_info(data_dir: str) -> str:
    d = Path(data_dir)
    need = ["deletion_requests.csv", "user_identities.csv", "user_audit_log.csv", "system_activity.csv", "deletion_rules.csv", "evidence_files.csv"]
    present = {n: (d / n).exists() for n in need}
    gold = [n for n in ("sample_output.csv", "expected_output.csv", "_gold.csv") if (d / n).exists()]
    out = {"present": present, "ok": all(present.values()), "gold": gold, "requests": 0, "evidence_files": 0,
           "extra_requests": [n for n in ("sample_deletion_requests.csv",) if (d / n).exists()]}
    if present["deletion_requests.csv"]:
        out["requests"] = len(read_requests("deletion_requests.csv", d))
    if present["evidence_files.csv"]:
        out["evidence_files"] = len(list(csv.DictReader(open(d / "evidence_files.csv", encoding="utf-8"))))
        out["evidence_present"] = sum(1 for r in csv.DictReader(open(d / "evidence_files.csv", encoding="utf-8")) if (d / r["file_path"]).exists())
    if (d / "sample_deletion_requests.csv").exists():
        out["sample_requests"] = len(read_requests("sample_deletion_requests.csv", d))
    return json.dumps(out)


def dataset_preview(data_dir: str) -> str:
    """Input explorer payload: requests, policy rules, evidence manifest, activity and identity counts."""
    from collections import Counter
    d = Path(data_dir)
    rd = lambda n: list(csv.DictReader(open(d / n, encoding="utf-8"))) if (d / n).exists() else []
    manifest = rd("evidence_files.csv")
    for m in manifest:
        fp = d / m["file_path"]; m["size"] = fp.stat().st_size if fp.exists() else None; m["ext"] = fp.suffix.lstrip(".")
    acts = rd("system_activity.csv")
    reqs = rd("deletion_requests.csv")
    out = {"requests": reqs, "sample_requests": rd("sample_deletion_requests.csv"), "rules": rd("deletion_rules.csv"), "manifest": manifest,
           "activity": {"total": len(acts), "by_type": Counter(a["event_type"] for a in acts).most_common(), "by_source": Counter(a["source_system"] for a in acts).most_common(8),
                        "results": Counter(a["reported_result"] for a in acts).most_common()},
           "identities": len(rd("user_identities.csv")), "audit_log": len(rd("user_audit_log.csv")),
           "reported_status": Counter(r["reported_status"] for r in reqs).most_common()}
    return json.dumps(out, ensure_ascii=False)


# ----------------------------------------------------------------------------------------------- scoring helpers
def _gold_for(d: Path, gold_name: str | None):
    if not gold_name:
        return None
    p = d / gold_name
    return eval_main().load_gold(p) if p.exists() else None


def _case_diff(row: dict, g: dict | None) -> dict | None:
    if g is None:
        return None
    ps, gs = json.loads(row["steps_json"]), json.loads(g["steps_json"])
    key = lambda s: (s["phase"], s["system_id"], s["resource_id"], s["operation"])
    pk, gk = {key(s): s for s in ps}, {key(s): s for s in gs}
    return {"status_ok": row["deletion_status"] == g["deletion_status"], "gold_status": g["deletion_status"],
            "exact": ps == gs and row["deletion_status"] == g["deletion_status"],
            "missing": [list(k) + [gk[k]["evidence_id"]] for k in sorted(set(gk) - set(pk))],
            "extra": [list(k) + [pk[k]["evidence_id"]] for k in sorted(set(pk) - set(gk))],
            "evidence_diff": [list(k) + [pk[k]["evidence_id"], gk[k]["evidence_id"]] for k in sorted(set(pk) & set(gk)) if pk[k]["evidence_id"] != gk[k]["evidence_id"]],
            "gold_steps": gs}


def _apply_flags(flags: dict | None) -> dict:
    old = {k: getattr(config, k) for k in FLAG_DEFAULTS}
    for k, v in {**FLAG_DEFAULTS, **(flags or {})}.items():
        if k in FLAG_DEFAULTS:
            setattr(config, k, bool(v))
    return old


def _restore_flags(old: dict) -> None:
    for k, v in old.items():
        setattr(config, k, v)


def _price(model: str, tin: int, tout: int) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return tin / 1e6 * pin + tout / 1e6 * pout


def _llm_summary(router: Router) -> dict:
    agg = usage_summary(router.ledger_path, router.run_id)
    rows, calls = [], []
    for (prov, model), a in sorted(agg.items()):
        rows.append({"provider": prov, "model": model, **a, "cost_fresh": _price(model, a["in"], a["out"]),
                     "cost_if_uncached": _price(model, a["in"] + a["cached_in"], a["out"] + a["cached_out"])})
    if router.ledger_path.exists():
        for line in router.ledger_path.read_text(encoding="utf-8").splitlines():
            m = json.loads(line)
            if m.get("run_id") == router.run_id:
                calls.append(m)
    return {"by_model": rows, "calls": calls, "fresh_calls": router.calls}


# ----------------------------------------------------------------------------------------------- main job
def run_audit(opts_json: str) -> str:
    """opts: data (dir), mode offline|hybrid, vision, flags{}, gold (file name inside dir or null), limit (int|null), refresh_llm, sort, artifacts."""
    o = json.loads(opts_json)
    d = Path(o["data"])
    old = _apply_flags(o.get("flags"))
    t0 = time.perf_counter()
    try:
        os.environ["LLM_REFRESH"] = "1" if o.get("refresh_llm") else "0"
        os.environ["LLM_MAX_SECONDS"] = str(o.get("max_seconds", 900))
        router = Router(enabled=o.get("mode") == "hybrid")
        router.workers = 1
        events.log("info", f"engine start: mode={o.get('mode')} providers={router.providers or 'none (offline deterministic)'}")
        reqs = read_requests("deletion_requests.csv", d)
        extra = read_requests("sample_deletion_requests.csv", d) if (d / "sample_deletion_requests.csv").exists() and o.get("pool_samples", True) else []
        rf = o.get("requests_file") or "deletion_requests.csv"          # which requests to answer; the pool always holds both (global link constraints)
        answer = extra if rf == "sample_deletion_requests.csv" and extra else reqs
        if o.get("limit"):
            answer = answer[: int(o["limit"])]
        rows, report, eng, intents = run(answer, reqs + extra, router, d, use_vision=bool(o.get("vision", True)), log=lambda m: events.log("warn", m))
        if o.get("sort") == "lexicographic":
            rows.sort(key=lambda r: r["case_id"])
        gold = _gold_for(d, o.get("gold"))
        metrics = None
        if gold:
            scored = [r for r in rows if r["case_id"] in gold]
            if scored:
                with events.stage("scoring") as st:
                    metrics = eval_main().score(scored, gold, False, eng)
                    metrics["scored_cases"] = len(scored)
                    st.update(cases=len(scored))
        by_req = {c["case_id"]: c for c in reqs + extra}
        flags_by_case = {cid: errs for cid, errs in report["flags"]}
        cases = []
        for r in rows:
            c = by_req[r["case_id"]]
            it = intents[r["case_id"]]
            cases.append({"case_id": r["case_id"], "status": r["deletion_status"], "steps": json.loads(r["steps_json"]),
                          "request": {k: c[k] for k in ("email", "requested_at", "reported_status", "reported_at", "audit_at", "request_text")},
                          "intent": {k: it[k] for k in ("rule", "strength", "rights", "llm", "llm_conf", "final", "disagree")},
                          "trace": report["trace"].get(r["case_id"]), "validator": flags_by_case.get(r["case_id"], []),
                          "gold": _case_diff(r, gold.get(r["case_id"]) if gold else None),
                          "investigator": report["investigator"].get(r["case_id"])})
        files = {}
        if o.get("artifacts", True):
            tmp = Path(tempfile.mkdtemp())
            write_csv(rows, tmp / "output.csv")
            write_run_artifacts(report, tmp / "run")
            files = {"output.csv": (tmp / "output.csv").read_text(encoding="utf-8"), "trace.jsonl": (tmp / "run" / "trace.jsonl").read_text(encoding="utf-8"),
                     "review.md": (tmp / "run" / "review.md").read_text(encoding="utf-8")}
        status = {}
        for r in rows:
            status[r["deletion_status"]] = status.get(r["deletion_status"], 0) + 1
        flag_counts = {}
        for t in report["trace"].values():
            for f in t["flags"]:
                flag_counts[f] = flag_counts.get(f, 0) + 1
        from collections import Counter, defaultdict
        per = defaultdict(lambda: {"observations": 0, "resources": set(), "kinds": Counter()})
        for ob in eng.obs:
            x = per[ob.fid]; x["observations"] += 1; x["resources"].add(ob.rid); x["kinds"][ob.kind] += 1
        evidence = []
        for fid, m in eng.manifest.items():
            x = per.get(fid)
            fp = d / m["file_path"]
            evidence.append({"file_id": fid, "path": m["file_path"], "origin": m["origin"], "captured_at": m["captured_at"], "size": fp.stat().st_size if fp.exists() else None,
                             "observations": x["observations"] if x else 0, "resources": len(x["resources"]) if x else 0, "kinds": dict(x["kinds"].most_common(4)) if x else {}})
        out = {"evidence": evidence, "summary": {"cases": len(rows), "status": status, "validator_flags": len(report["flags"]), "ambiguous": len(report["ambiguous"]),
                           "ambiguous_ids": report["ambiguous"], "mode": o.get("mode"), "providers": router.providers, "run_id": router.run_id,
                           "duration_ms": round((time.perf_counter() - t0) * 1000), "flag_counts": flag_counts, "info_flags": sorted(INFO_FLAGS),
                           "ghost_cases": sum(1 for t in report["trace"].values() if t.get("ghost_hits")), "clean_leaks": len(report["clean_leaks"]),
                           "dataset": str(d), "requests_file": rf, "config": {k: getattr(config, k) for k in FLAG_DEFAULTS}},
               "cases": cases, "metrics": metrics, "catalog": report["catalog"], "vision_mismatch": report["vision_mismatch"],
               "llm": _llm_summary(router), "files": files}
        return json.dumps(out, ensure_ascii=False, default=list)
    finally:
        _restore_flags(old)


def run_ablation(opts_json: str) -> str:
    """configs: [{name, flags}] - each runs the full pipeline offline; output compared with the first config."""
    o = json.loads(opts_json)
    results, base = [], None
    for i, cfg in enumerate(o["configs"], 1):
        events.emit("progress", stage="ablation", done=i - 1, total=len(o["configs"]), label=cfg["name"])
        d = Path(o["data"])
        res = json.loads(run_audit(json.dumps({"data": o["data"], "gold": o.get("gold"), "requests_file": o.get("requests_file"), "mode": "offline", "vision": False,
                                                "flags": cfg.get("flags", {}), "artifacts": False, "pool_samples": True})))
        metrics = res["metrics"]
        if metrics is None and (d / "sample_deletion_requests.csv").exists() and (d / "sample_output.csv").exists():      # score on the public samples, as the report does
            metrics = json.loads(run_audit(json.dumps({"data": o["data"], "gold": "sample_output.csv", "requests_file": "sample_deletion_requests.csv", "mode": "offline",
                                                       "vision": False, "flags": cfg.get("flags", {}), "artifacts": False})))["metrics"]
        steps = {c["case_id"]: (c["status"], json.dumps(c["steps"])) for c in res["cases"]}
        base = base or steps
        changed = sum(1 for cid, v in steps.items() if v != base.get(cid))
        results.append({"name": cfg["name"], "flags": cfg.get("flags", {}), "metrics": metrics, "summary": res["summary"], "changed": changed, "cases": len(steps)})
    events.emit("progress", stage="ablation", done=len(o["configs"]), total=len(o["configs"]))
    return json.dumps({"results": results})


def run_recovery(opts_json: str) -> str:
    o = json.loads(opts_json)
    sys.path.insert(0, str(CODE / "evaluation"))
    import link_recovery
    old = _apply_flags(o.get("flags"))
    try:
        t0 = time.perf_counter()
        n, res = link_recovery.recover(int(o.get("folds", 4)), int(o.get("repeats", 1)), data=Path(o["data"]),
                                       progress=lambda i, tot: events.emit("progress", stage="recovery", done=i, total=tot))
        acc = [ok / h for h, ok, _ in res if h]; amb = [m / h for h, _, m in res if h]
        mean = lambda xs: sum(xs) / len(xs) if xs else 0
        return json.dumps({"proven_accounts": n, "folds": len(res), "accuracy": mean(acc), "ambiguity": mean(amb),
                           "per_fold": [{"hidden": h, "recovered": ok, "ambiguous": m} for h, ok, m in res], "ms": round((time.perf_counter() - t0) * 1000)})
    finally:
        _restore_flags(old)


def run_custom_suite(root: str) -> str:
    """Runs every dataset folder under `root` that has expected_output.csv; returns one metrics block per dataset."""
    out = []
    for d in sorted(p for p in Path(root).iterdir() if (p / "expected_output.csv").exists()):
        res = json.loads(run_audit(json.dumps({"data": str(d), "mode": "offline", "vision": False, "gold": "expected_output.csv", "artifacts": False})))
        exact = all(c["gold"] and c["gold"]["exact"] for c in res["cases"])
        out.append({"name": d.name, "cases": res["summary"]["cases"], "metrics": res["metrics"], "exact": exact, "validator_flags": res["summary"]["validator_flags"],
                    "duration_ms": res["summary"]["duration_ms"]})
    return json.dumps({"datasets": out})


def test_key(provider: str, key: str, base_url: str = "") -> str:
    """Browser only: list models to check that a key works. Returns {ok, count|error}. The key is never logged."""
    import browser_io
    try:
        ms = browser_io.list_models(provider, key, base_url)
        return json.dumps({"ok": True, "count": len(ms), "models": ms[:12]})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:160]})
