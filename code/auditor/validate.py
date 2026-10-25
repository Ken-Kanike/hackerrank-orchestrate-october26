"""Output contract validation (schema, ordering, citation rules). Violations are reported, never silently emitted."""
from __future__ import annotations

import json

from .engine import OP_ORDER, OP_STATE, PHASE, PHASES
from .evidence import T

STATUSES = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}
FIELDS = {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}


# observation states that support each step state (a cited file whose observations of the resource are ALL outside this set contradicts it)
SUPPORTS = {"PRESENT": {"PRESENT", "PII", "RETAINED"}, "ACTIVE": {"ACTIVE", "RESTORABLE"}, "ABSENT": {"ABSENT"},
            "REDACTED": {"CLEAN"}, "ANONYMIZED": {"CLEAN"}, "DISABLED": {"DISABLED"}, "BLOCKED": {"BLOCKED"}}


FIX = {"REPORT_REMAINING_RECORD": ({"DELETE_RECORD"}, {"VERIFY_RECORD_ABSENT"}),
       "REPORT_EXPOSED_PII": ({"REDACT_RECORD", "ANONYMIZE_RECORD"}, {"VERIFY_RECORD_REDACTED", "VERIFY_RECORD_ANONYMIZED"}),
       "REPORT_ACTIVE_DATA_FLOW": ({"DISABLE_DATA_FLOW"}, {"VERIFY_DATA_FLOW_DISABLED"}),
       "REPORT_RESTORE_RISK": ({"BLOCK_RESTORE"}, {"VERIFY_RESTORE_BLOCKED"})}


def validate_row(row: dict, manifest: dict, case: dict | None = None, obs_index: dict | None = None,
                 activities: dict | None = None) -> list[str]:
    """obs_index: (fid, rid) -> [Obs]; enables the 'cited evidence must not contradict the step' rule."""
    errs = []
    if row["deletion_status"] not in STATUSES:
        errs.append("bad status")
    try:
        steps = json.loads(row["steps_json"])
    except Exception:
        return errs + ["steps_json not JSON"]
    if row["deletion_status"] == "NOT_APPLICABLE":
        return errs + ([] if steps == [] else ["NA must be []"])
    last = (-1, -1)
    for i, s in enumerate(steps, 1):
        if set(s) != FIELDS:
            errs.append(f"step {i} fields")
        if s.get("step_no") != i:
            errs.append(f"step {i} numbering")
        op = s.get("operation")
        if op not in OP_ORDER or PHASE.get(op) != s.get("phase") or OP_STATE.get(op) != s.get("state"):
            errs.append(f"step {i} op/phase/state")
            continue
        key = (PHASES.index(s["phase"]), OP_ORDER.index(op))
        if key < last:
            errs.append(f"step {i} order")
        last = key
        ev = s.get("evidence_id", "")
        if s["phase"] == "FINDING" or (row["deletion_status"] == "COMPLETE"):
            if ev and activities and ev in activities:            # activity_id / audit_id citations are allowed (problem statement 6.6)
                if case and activities[ev]["event_time"] > case["audit_at"]:
                    errs.append(f"step {i} evidence after audit_at")
            elif not ev or ev not in manifest:
                errs.append(f"step {i} missing/unknown evidence")
            elif case and manifest[ev]["captured_at"] > case["audit_at"]:
                errs.append(f"step {i} evidence after audit_at")
            elif obs_index is not None and case:
                seen = [o for o in obs_index.get((ev, s["resource_id"]), []) if o.t <= case["audit_at"]]
                if seen and not any(o.state in SUPPORTS.get(s["state"], ()) for o in seen):
                    errs.append(f"step {i} cited {ev} contradicts {s['operation']} for {s['resource_id']}")
        elif ev:
            errs.append(f"step {i} future step must have empty evidence")
    if row["deletion_status"] == "COMPLETE" and any(s["phase"] != "VERIFICATION" for s in steps):
        errs.append("COMPLETE must be verification-only")
    if row["deletion_status"] == "COMPLETE" and not steps:
        errs.append("COMPLETE must carry verification steps")
    keys = [(s.get("phase"), s.get("system_id"), s.get("resource_id"), s.get("operation")) for s in steps]
    if len(keys) != len(set(keys)):
        errs.append("duplicate step")
    for a, b in zip(steps, steps[1:]):                       # within one operation group: ordered by (system_id, resource_id)
        if a.get("operation") == b.get("operation") and (a.get("system_id"), a.get("resource_id")) > (b.get("system_id"), b.get("resource_id")):
            errs.append(f"step {b.get('step_no')} not sorted within its operation group")
    if row["deletion_status"] == "INCOMPLETE":
        findings = [s for s in steps if s.get("phase") == "FINDING"]
        if not findings:
            errs.append("INCOMPLETE without any finding")
        for f in findings:                                   # every finding needs a remediation and a verification on the same resource
            rems, vers = FIX[f["operation"]]
            rid = f["resource_id"]
            if not any(s["phase"] == "REMEDIATION" and s["resource_id"] == rid and s["operation"] in rems for s in steps):
                errs.append(f"finding on {rid} has no remediation")
            if not any(s["phase"] == "VERIFICATION" and s["resource_id"] == rid and s["operation"] in vers for s in steps):
                errs.append(f"finding on {rid} has no verification")
    return errs
