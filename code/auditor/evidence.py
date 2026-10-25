"""Evidence store: turns every supplied evidence file into normalized observations.

Observation = "file F (captured at C) shows resource R in system S in state X at record time T, mentioning identity keys K".
States: PRESENT ABSENT PII CLEAN ACTIVE DISABLED RESTORABLE BLOCKED RETAINED.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from . import config, events

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RID_RE = re.compile(r"\b(account|search|analytics|support|export|data_flow|backup|audit_record|tombstone|legal_hold|marketing|object)_\d+\b")
USER_RE = re.compile(r"\buser_\d+\b")
KV = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=("(?:[^"\\]|\\.)*"|\S+)')
TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)")
PHONE_LIKE = re.compile(r"^\+?\d[\d\s().-]{7,}\d$")
NULLS = {"", "null", "none", "-", "—", "no direct identifier"}


def norm_key(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if s.lower() in NULLS:
        return None
    if PHONE_LIKE.match(s) and len(re.sub(r"\D", "", s)) >= 9:       # phones in any formatting compare by digits (E.164 without '+')
        return "tel:" + re.sub(r"\D", "", s)
    return s.lower()


def keys_from(*vals) -> set[str]:
    out: set[str] = set()
    for v in vals:
        k = norm_key(v)
        if k:
            out.add(k)
            out |= {e.lower() for e in EMAIL_RE.findall(str(v))}
    return out


@dataclass
class Obs:
    fid: str
    fcap: str          # file capture time (citation eligibility)
    t: str             # record time (state timeline)
    sys: str
    rid: str
    state: str
    kind: str = ""
    keys: set = field(default_factory=set)
    note: str = ""
    attrs: dict = field(default_factory=dict)      # static facts about the record (retention_until / retained_until)


ID_FIELDS = ("email", "owner_email", "customer_email", "requester_email", "subject_reference", "customer_reference", "user_id",
             "subject_selector", "uploaded_by", "email_hash", "phone", "owner_phone", "requester_phone", "full_name",
             "display_name", "requester_name", "name", "lookup_value")
PII_FIELDS = ("email", "owner_email", "customer_email", "requester_email", "email_hash", "phone", "owner_phone",
              "requester_phone", "full_name", "display_name", "requester_name", "name")

RESULT_STATE = {
    ("USER_PROFILE", "FOUND"): "PRESENT", ("USER_PROFILE", "NOT_FOUND"): "ABSENT",
    ("SEARCH_INDEX_ENTRY", "FOUND"): "PRESENT", ("SEARCH_INDEX_ENTRY", "NOT_FOUND"): "ABSENT",
    ("ANALYTICS_PROFILE", "IDENTIFIABLE"): "PII", ("ANALYTICS_PROFILE", "ANONYMIZED"): "CLEAN",
    ("SUPPORT_MESSAGE", "IDENTIFIABLE"): "PII", ("SUPPORT_MESSAGE", "REDACTED"): "CLEAN",
    ("SUPPORT_ATTACHMENT", "FOUND"): "PRESENT", ("USER_EXPORT", "FOUND"): "PRESENT",
    ("BACKUP_ARCHIVE", "ACTIVE"): "RESTORABLE", ("BACKUP_ARCHIVE", "BLOCKED"): "BLOCKED",
    ("DATA_FLOW", "ACTIVE"): "ACTIVE", ("DATA_FLOW", "DISABLED"): "DISABLED",
    ("SECURITY_AUDIT_LOG", "FOUND"): "RETAINED", ("LEGAL_HOLD_RECORD", "FOUND"): "RETAINED",
}
COLLECTION_KIND = {  # collection -> (state rule)
    "customer_profiles": "present", "customer_search_documents": "present", "search_documents_primary": "present",
    "customer_analytics_reports": "pii", "customer_analytics_profiles": "pii", "profiles": "pii",
    "support_conversations": "pii", "support_records": "pii", "tickets": "pii", "deleted_customer_references": "pii",
    "ticket_attachments": "present", "customer_export_jobs": "present", "customer_exports": "present", "exports": "present",
    "connector_configurations": "flow", "connector_subscriptions": "flow", "connectors": "flow",
    "backup_catalog": "backup", "backup_restore_entries": "backup", "restore_entries": "backup",
    "security_audit_events": "retained", "security_audit_records": "retained", "audit_records": "retained",
    "retained_order_records": "retained",
}
TABLE_SYSTEM = {"customer_profiles": "account_service", "customer_search_documents": "search_service",
                "customer_analytics_profiles": "analytics_platform", "support_records": "support_platform",
                "customer_exports": "export_service", "connector_subscriptions": "integration_service",
                "backup_restore_entries": "backup_service", "security_audit_records": "security_service"}


RETENTION_FIELDS = ("retention_until", "retained_until")


def retention_attrs(*srcs) -> dict:
    out = {}
    for src in srcs:
        for f in RETENTION_FIELDS:
            v = (src or {}).get(f)
            if v and re.match(r"\d{4}-\d{2}-\d{2}", str(v)):
                out[f] = str(v)
    return out


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def store_obs(fid, fcap, t, system, coll, r, note="") -> Obs:
    keys = set()
    doc = r.get("document") or {}
    for f in ID_FIELDS:
        keys |= keys_from(r.get(f)) | keys_from(doc.get(f))
    msg = r.get("message_text") or r.get("message_excerpt") or ""
    keys |= {e.lower() for e in EMAIL_RE.findall(msg)}
    pii = any(norm_key(r.get(f)) for f in PII_FIELDS) or any(norm_key(doc.get(f)) for f in PII_FIELDS) or bool(EMAIL_RE.search(msg))
    rule = COLLECTION_KIND.get(coll, "present")
    if coll == "profile_lookups":
        st = "PRESENT" if r.get("status_code") == 200 else "ABSENT"
        keys |= keys_from(*(r.get("profile") or {}).values())
    elif coll == "index_queries":
        st = "PRESENT" if (r.get("hits") or {}).get("total", 0) else "ABSENT"
        keys |= keys_from(r.get("query"))
        for d in (r.get("hits") or {}).get("documents", []):
            for f in ID_FIELDS:
                keys |= keys_from(d.get(f))
    elif rule == "pii":
        st = "PII" if pii else "CLEAN"
    elif rule == "flow":
        st = "ACTIVE" if _truthy(r.get("enabled")) else "DISABLED"
    elif rule == "backup":
        st = "RESTORABLE" if _truthy(r.get("restore_allowed")) else "BLOCKED"
    elif rule == "retained":
        st = "RETAINED"
    else:
        st = "PRESENT"
    return Obs(fid, fcap, t or fcap, system, r.get("resource_id"), st, coll, keys, note, retention_attrs(r, doc))


def lookup_obs(fid, fcap, r) -> Obs:
    st = RESULT_STATE.get((r["record_type"], r["result"]), r["result"])
    return Obs(fid, fcap, r.get("recorded_at") or fcap, r["system"], r["resource_id"], st, r["record_type"],
               keys_from(r.get("subject_reference"), r.get("lookup_value")), attrs=retention_attrs(r))


# ------------------------------------------------------------------ logs
def parse_log_line(line: str):
    line = line.rstrip("\n")
    m = TS.match(line)
    ts = m.group(1) if m else None
    rest = line[m.end():] if m else line
    attrs: dict = {}
    j = rest.find("{")
    if j != -1 and rest.strip().startswith("{"):
        try:
            attrs.update(json.loads(rest[j:]))
        except Exception:
            pass
    for k, v in KV.findall(rest):
        if v.startswith('"'):
            v = v[1:-1].replace('\\"', '"')
        if k == "message" and "=" in v:
            for k2, v2 in KV.findall(v):
                attrs[k2] = v2.strip('"')
        else:
            attrs.setdefault(k, v)
    mb = re.match(r"\s*\[(\w+)\]\s*\[([\w-]+)\]\s*\[([\w-]+)\]\s*(\w+):", rest)
    if mb:
        attrs.setdefault("service", mb.group(2)); attrs.setdefault("trace_id", mb.group(3)); attrs.setdefault("event", mb.group(4))
    mp = re.match(r"\s*\|\s*(\w+)\s*\|\s*([\w-]+)\s*\|\s*([\w-]+)\s*\|\s*(\w+)\s*\|", rest)
    if mp:
        attrs.setdefault("service", mp.group(2)); attrs.setdefault("trace_id", mp.group(3)); attrs.setdefault("event", mp.group(4))
    ms = re.match(r"\s*<\d+>1 \S+ (\S+) (\S+) - -", rest)
    if ms:
        attrs.setdefault("service", ms.group(1)); attrs.setdefault("trace_id", ms.group(2))
    for src, dst in (("requestId", "trace_id"), ("function", "service"), ("logger", "service")):
        if src in attrs:
            attrs.setdefault(dst, attrs[src])
    return ts, attrs


SERVICE_ALIAS = {"profile_service": "account_service", "support_replica": "support_platform"}
KEY_FIELDS = ("lookup_key", "subject_key", "scan_key", "match_key", "subject_ref", "owner_key", "correlation_key")
OTHER_KEY_FIELDS = ("matched_value", "email", "customer_email", "customer_reference", "subject_reference", "requester_email", "owner_email")


def _log_state(ev: str, a: dict):
    g = a.get
    if ev == "profile_lookup_completed":
        return "PRESENT" if str(g("rows")) != "0" else "ABSENT"
    if ev == "index_query_completed":
        return "PRESENT" if g("result") == "hit" else "ABSENT"
    if ev in ("analytics_profile_read", "analytics_profile_read_completed"):
        pii = any(norm_key(g(f)) for f in ("email", "phone", "email_hash")) or str(g("direct_identifiers", "0")) != "0"
        return "PII" if pii else "CLEAN"
    if ev in ("analytics_identity_scan", "message_pii_scan"):
        return "PII"
    if ev in ("contact_lookup_completed", "attachment_pii_scan"):
        return "PRESENT"
    if ev == "message_read":
        return "CLEAN" if "REDACTED" in str(g("message_text")) else "PII"
    if ev == "support_ticket_read_completed":
        return "PII" if any(norm_key(g(f)) for f in ("requester_name", "requester_email", "requester_phone")) else "CLEAN"
    if ev in ("export_download_check_completed", "export_metadata_read_completed"):
        return "PRESENT" if _truthy(g("available")) else "ABSENT"
    if ev in ("connector_config_read_completed", "connector_heartbeat", "connector_config_loaded"):
        return "ACTIVE" if _truthy(g("enabled")) else "DISABLED"
    if ev == "restore_policy_read_completed":
        return "RESTORABLE" if _truthy(g("restore_allowed")) else "BLOCKED"
    if ev == "restore_candidate_evaluated":
        return "RESTORABLE" if _truthy(g("eligible")) and not _truthy(g("deletion_block")) else "BLOCKED"
    if ev == "restore_authorization_completed":
        return "RESTORABLE" if str(g("decision")).lower() in ("allow", "allowed", "approved", "permit") else "BLOCKED"
    if ev == "audit_record_read_completed":
        return "RETAINED" if str(g("rows")) != "0" else "ABSENT"
    if ev == "retained_order_loaded":
        return "RETAINED"
    if ev == "contact_query_completed":
        return "PRESENT" if str(g("rows")) != "0" else "ABSENT"
    return None


def parse_log(fid, fcap, path) -> list[Obs]:
    out, traces = [], defaultdict(list)
    for n, line in enumerate(open(path, encoding="utf-8")):
        ts, a = parse_log_line(line)
        if "record_type" in a:
            r = dict(a); r.setdefault("recorded_at", ts)
            out.append(lookup_obs(fid, fcap, r))
            continue
        traces[a.get("trace_id") or f"__{n}"].append((ts, a))
    for evs in traces.values():
        keys = set()
        for _, a in evs:
            for k in KEY_FIELDS:
                keys |= keys_from(a.get(k))
        for ts, a in evs:                                   # join identity (started) with resource (completed) by trace_id
            ev, rid = a.get("event", ""), a.get("resource_id")
            if not rid or ev.endswith("_started"):
                continue
            st = _log_state(ev, a)
            if st is None:
                continue
            svc = SERVICE_ALIAS.get(a.get("service"), a.get("service"))
            k2 = set(keys)
            for f in KEY_FIELDS + OTHER_KEY_FIELDS:
                k2 |= keys_from(a.get(f))
            out.append(Obs(fid, fcap, ts, svc, rid, st, ev, k2, attrs=retention_attrs(a)))
    return out


# ------------------------------------------------------------------ other formats
def parse_json(fid, fcap, path) -> list[Obs]:
    d = json.load(open(path, encoding="utf-8")); out = []
    if "snapshots" in d:
        for s in d["snapshots"]:
            for r in s["records"]:
                out.append(lookup_obs(fid, fcap, r) if "record_type" in r else store_obs(fid, fcap, s["captured_at"], s["data_store"], s["collection"], r))
    elif "service_exports" in d:
        for system, colls in d["service_exports"].items():
            for coll, items in colls.items():
                out += [store_obs(fid, fcap, r.get("observed_at"), system, coll, r) for r in items]
    elif d.get("records") and "record_type" in d["records"][0]:
        out += [lookup_obs(fid, fcap, r) for r in d["records"]]
    elif "collection" in d:
        system = {"customer_analytics_reports": "analytics_platform", "customer_export_jobs": "export_service"}[d["collection"]]
        out += [store_obs(fid, fcap, d.get("captured_at"), system, d["collection"], r) for r in d["records"]]
    return out


def parse_sql(fid, fcap, path) -> list[Obs]:
    con = sqlite3.connect(":memory:"); con.executescript(open(path, encoding="utf-8").read()); out = []
    for (tname,) in list(con.execute("select name from sqlite_master where type='table'")):
        if tname == "snapshot_scope":
            continue
        cols = [c[1] for c in con.execute(f'pragma table_info("{tname}")')]
        for row in con.execute(f'select * from "{tname}"'):
            rec = dict(zip(cols, row))
            if "record_json" in rec:
                out.append(store_obs(fid, fcap, rec.get("updated_at"), rec["origin_system"], rec["collection_name"], json.loads(rec["record_json"]), tname))
            elif tname.startswith("customer_profiles_"):
                out.append(store_obs(fid, fcap, rec.get("updated_at"), "account_service", "customer_profiles", rec, tname))
            elif tname.startswith("search_documents_"):
                out.append(store_obs(fid, fcap, rec.get("indexed_at"), "search_service", "search_documents_primary", rec, tname))
            else:
                out.append(store_obs(fid, fcap, rec.get("updated_at"), TABLE_SYSTEM[tname], tname, rec, tname))
    return out


def parse_handover(fid, fcap, path) -> list[Obs]:
    out = []
    for line in open(path, encoding="utf-8"):
        if line.startswith("- "):
            p = [x.strip() for x in line[2:].split("|")]
            out.append(lookup_obs(fid, fcap, {"recorded_at": p[0], "system": p[1], "resource_id": p[2], "record_type": p[3], "result": p[4], "subject_reference": p[5]}))
    return out


def pdf_text(path) -> str:
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def parse_pdf(fid, fcap, path) -> list[Obs]:
    """Documents are business artifacts: pull resource ids + identity keys that co-occur in the text."""
    text = pdf_text(path)
    keys = {e.lower() for e in EMAIL_RE.findall(text)} | {u.lower() for u in USER_RE.findall(text)}
    keys |= {"tel:" + re.sub(r"\D", "", m) for m in re.findall(r"\+\d[\d ()-]{7,}\d", text)}
    out = []
    for m in RID_RE.finditer(text):
        rid = m.group(0); pre = m.group(1)
        if pre == "audit_record":
            out.append(Obs(fid, fcap, fcap, "security_service", rid, "RETAINED", "pdf", keys))
        elif pre == "support":
            out.append(Obs(fid, fcap, fcap, "support_platform", rid, "PRESENT", "SUPPORT_ATTACHMENT", keys))
    # legal register rows: "ORD-... | user_08 | ..." -> retained legal record keyed by user
    return out


# ------------------------------------------------------------------ catalog events (screenshots / documents)
from .taxonomy import PREFIX_STATE, SYS_OF_PREFIX, prefix  # noqa: E402,F401


@lru_cache(maxsize=None)          # pure and called ~600k times during linking
def T(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def catalog_obs(manifest: dict, acts: list[dict], vision: dict | None = None) -> list[Obs]:
    """LINK_RESOURCE_IDENTITY events tie a resource to a person; the artifact is the screenshot/PDF captured just before.
    `vision` (optional) maps file_id -> dict from the vision extractor and refines the state."""
    out = []
    media = [(fid, m) for fid, m in manifest.items() if m["file_path"].endswith((".png", ".pdf"))]
    for a in acts:
        if a["event_type"] != "LINK_RESOURCE_IDENTITY":
            continue
        t = T(a["event_time"])
        cands = [(t - T(m["captured_at"]), fid, m) for fid, m in media if timedelta(0) <= t - T(m["captured_at"]) <= timedelta(minutes=30)]
        if not cands:
            continue
        _, fid, m = min(cands, key=lambda x: x[0])
        rid = a["resource_id"]; pre = prefix(rid)
        det = a["details"]
        keys = {e.lower() for e in EMAIL_RE.findall(det)} | {u.lower() for u in USER_RE.findall(det)}
        st, unverified = PREFIX_STATE.get(pre, "PRESENT"), True          # nobody read the artifact: state is the family default
        if vision and fid in vision and vision[fid].get("state"):
            st, unverified = vision[fid]["state"], False
        out.append(Obs(fid, m["captured_at"], m["captured_at"], a["target_system"], rid, st, "catalog", keys,
                       attrs={"state_unverified": True} if unverified else {}))
    return out


def activity_obs(acts: list[dict]) -> list[Obs]:
    """State *checks* in the activity stream (not operation results) as weak observations, cited by activity_id.

    CHECK_DATA_FLOW "remains enabled" -> ACTIVE;  CHECK_RESTORE_ACCESS "can still be restored" -> RESTORABLE;
    RESTORE_BACKUP -> RESTORABLE. DELETE/REDACT/ANONYMIZE/DISABLE/BLOCK results are claims and are never observations.
    """
    out = []
    for a in acts:
        d, ty = a["details"].lower(), a["event_type"]
        st = None
        if ty == "CHECK_DATA_FLOW" and "remains enabled" in d:
            st = "ACTIVE"
        elif ty == "CHECK_RESTORE_ACCESS" and "can still be restored" in d:
            st = "RESTORABLE"
        if st:
            out.append(Obs(a["activity_id"], a["event_time"], a["event_time"], a["target_system"], a["resource_id"], st, "activity_check",
                           attrs={"weak": True}))
    return out


def load_manifest(data: Path) -> dict:
    return {r["file_id"]: r for r in csv.DictReader(open(data / "evidence_files.csv", encoding="utf-8"))}


def load_activity(data: Path) -> list[dict]:
    return list(csv.DictReader(open(data / "system_activity.csv", encoding="utf-8")))


def load_observations(data: Path, manifest: dict, acts: list[dict], vision: dict | None = None) -> list[Obs]:
    obs: list[Obs] = []
    for n, (fid, m) in enumerate(manifest.items(), 1):
        if n % 10 == 0 or n == len(manifest):
            events.emit("progress", stage="evidence", done=n, total=len(manifest))
        p = data / m["file_path"]
        ext = p.suffix
        if ext == ".json":
            obs += parse_json(fid, m["captured_at"], p)
        elif ext == ".sql":
            obs += parse_sql(fid, m["captured_at"], p)
        elif ext == ".log":
            obs += parse_log(fid, m["captured_at"], p)
        elif ext == ".txt":
            obs += parse_handover(fid, m["captured_at"], p)
        elif ext == ".pdf":
            obs += parse_pdf(fid, m["captured_at"], p)
    obs += catalog_obs(manifest, acts, vision)
    if config.USE_ACTIVITY_CHECKS:
        obs += activity_obs(acts)
    return [o for o in obs if o.rid]
