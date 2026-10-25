"""Ghost sweep (defence in depth): grep *all* evidence text for each subject's identifiers, independent of the structured parsers.

Every record-sized unit (log line, SQL row, JSON record, handover line, whole PDF) is indexed by the identifiers it mentions
(emails, user refs, sha256 hashes, phones) and the resource ids it names. For a case, a unit that mentions one of the subject's
identifiers, is stamped at or before audit_at, and names a resource that is *not* in the case's resolved set is a ghost hit:
either a parser gap or a resource the linker missed. Hits are review flags, never silent edits.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from .evidence import EMAIL_RE, RID_RE, USER_RE, pdf_text

ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
HASH = re.compile(r"\b[0-9a-f]{64}\b")
PHONE = re.compile(r"\+\d[\d ()-]{7,}\d")
RID_FULL = re.compile(r"\b(?:account|search|analytics|support|export|data_flow|backup|audit_record|tombstone|legal_hold|marketing|object)_\d+\b")


def _unit(fid, fcap, loc, text):
    rids = set(RID_FULL.findall(text))
    if not rids:
        return None
    ids = {e.lower() for e in EMAIL_RE.findall(text)} | {u.lower() for u in USER_RE.findall(text)} | set(HASH.findall(text.lower()))
    ids |= {"tel:" + re.sub(r"\D", "", m) for m in PHONE.findall(text)}
    stamps = ISO.findall(text)
    return {"fid": fid, "loc": loc, "rids": rids, "ids": ids, "ts": max(stamps) if stamps else fcap}


def _json_records(node):
    if isinstance(node, dict):
        if "resource_id" in node:
            yield node
        else:
            for v in node.values():
                yield from _json_records(v)
    elif isinstance(node, list):
        for v in node:
            yield from _json_records(v)


def build_index(data: Path, manifest: dict) -> dict[str, list[dict]]:
    """identifier -> [unit]."""
    index: dict[str, list[dict]] = defaultdict(list)
    for fid, m in manifest.items():
        p = data / m["file_path"]; fcap = m["captured_at"]; units = []
        if p.suffix in (".log", ".txt", ".sql"):
            for n, line in enumerate(open(p, encoding="utf-8"), 1):
                u = _unit(fid, fcap, f"line {n}", line)
                if u:
                    units.append(u)
        elif p.suffix == ".json":
            for n, rec in enumerate(_json_records(json.load(open(p, encoding="utf-8"))), 1):
                u = _unit(fid, fcap, f"record {n}", json.dumps(rec, ensure_ascii=False))
                if u:
                    units.append(u)
        elif p.suffix == ".pdf":
            u = _unit(fid, fcap, "document", pdf_text(p))
            if u:
                units.append(u)
        for u in units:
            for i in u["ids"]:
                index[i].append(u)
    return index


def sweep(index: dict, keys: set[str], audit_at: str, explained: set[str], foreign: set[str]) -> list[dict]:
    """Ghost hits for one subject. explained = resources already resolved for the case; foreign = resources owned by other users."""
    hits, seen = [], set()
    for k in keys:
        for u in index.get(k, ()):
            if u["ts"] > audit_at:
                continue
            for rid in sorted(u["rids"] - explained - foreign):
                if (rid, u["fid"]) not in seen:
                    seen.add((rid, u["fid"])); hits.append({"rid": rid, "fid": u["fid"], "loc": u["loc"], "ts": u["ts"], "via": k if "@" not in k else "email"})
    return sorted(hits, key=lambda h: (h["rid"], h["fid"]))


def clean_leaks(index: dict, obs: list) -> list[dict]:
    """Records the parsers classified CLEAN (redacted / anonymized) whose text still carries a phone number or an email hash.

    A subject-aware PII recognizer (limitations C5) would be needed only if this list is non-empty; on the supplied data it is empty.
    """
    clean = {(o.fid, o.rid) for o in obs if o.state == "CLEAN" and o.kind != "catalog"}
    out, seen = [], set()
    for key, units in index.items():
        if not (key.startswith("tel:") or HASH.fullmatch(key)):
            continue
        for u in units:
            for rid in sorted(u["rids"]):
                if (u["fid"], rid) in clean and (u["fid"], rid) not in seen:
                    seen.add((u["fid"], rid)); out.append({"fid": u["fid"], "rid": rid, "loc": u["loc"], "identifier_type": "phone" if key.startswith("tel:") else "hash"})
    return out
