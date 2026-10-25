"""Core audit engine: identity resolution -> resource linking -> state reconstruction -> policy -> plan.

Deterministic. The LLM layer (intent cross-check, vision) only feeds observations/flags into this engine.
"""
from __future__ import annotations

import csv
import hashlib
from collections import defaultdict, namedtuple
from datetime import timedelta
from pathlib import Path

from . import config
from .evidence import Obs, T, norm_key
from .lineage import build_edges, downstream
from .policy import Policy
from .taxonomy import SYS_OF_PREFIX, prefix

STATUS_RESULT = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL", "NOT_STARTED": "FAILED"}
OP_ORDER = ["REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK",
            "DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD",
            "VERIFY_RECORD_ABSENT", "VERIFY_RECORD_PRESENT", "VERIFY_RECORD_REDACTED", "VERIFY_RECORD_ANONYMIZED",
            "VERIFY_DATA_FLOW_DISABLED", "VERIFY_RESTORE_BLOCKED"]
OP_STATE = {"REPORT_REMAINING_RECORD": "PRESENT", "REPORT_EXPOSED_PII": "PRESENT", "REPORT_ACTIVE_DATA_FLOW": "ACTIVE",
            "REPORT_RESTORE_RISK": "ACTIVE", "DISABLE_DATA_FLOW": "DISABLED", "BLOCK_RESTORE": "BLOCKED",
            "DELETE_RECORD": "ABSENT", "REDACT_RECORD": "REDACTED", "ANONYMIZE_RECORD": "ANONYMIZED",
            "VERIFY_RECORD_ABSENT": "ABSENT", "VERIFY_RECORD_PRESENT": "PRESENT", "VERIFY_RECORD_REDACTED": "REDACTED",
            "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED", "VERIFY_DATA_FLOW_DISABLED": "DISABLED", "VERIFY_RESTORE_BLOCKED": "BLOCKED"}
PHASES = ["FINDING", "REMEDIATION", "VERIFICATION"]
PHASE = {op: ("FINDING" if op.startswith("REPORT") else "VERIFICATION" if op.startswith("VERIFY") else "REMEDIATION") for op in OP_ORDER}
# remediation dependency order: stop flows / block restores first (ops order above already encodes this)

State = namedtuple("State", "state evidence kind system attrs uncited unverified")


class Directory:
    """Current + historical identifiers per user (email chain, hashes, phones)."""

    def __init__(self, data: Path):
        self.users: dict[str, dict] = {}
        for r in csv.DictReader(open(data / "user_identities.csv", encoding="utf-8")):
            self.users[r["user_id"]] = {"uid": r["user_id"], "emails": {r["email"].lower()}, "hashes": {r["email_hash"].lower()},
                                        "phones": {norm_key(r["phone"])}, "names": {r["name"].lower()}}
        for r in csv.DictReader(open(data / "user_audit_log.csv", encoding="utf-8")):
            u = self.users.get(r["user_id"])
            if not u:
                continue
            f = r["field_name"]
            for v in (r["old_value"], r["new_value"]):
                if f == "email": u["emails"].add(v.lower())
                elif f == "email_hash": u["hashes"].add(v.lower())
                elif f == "phone": u["phones"].add(norm_key(v))
                elif f == "name": u["names"].add(v.lower())
        self.owner: dict[str, set[str]] = defaultdict(set)
        for u in self.users.values():
            u["hashes"] |= {hashlib.sha256(e.encode()).hexdigest() for e in u["emails"]}
            u["keys"] = u["emails"] | u["hashes"] | u["phones"] | {u["uid"].lower()}
            for k in u["keys"]:
                self.owner[k].add(u["uid"])

    def resolve(self, email: str) -> list[str]:
        return sorted(self.owner.get(email.strip().lower(), set()))


class Engine:
    def __init__(self, data: Path, manifest: dict, acts: list[dict], obs: list[Obs]):
        self.data, self.manifest, self.acts, self.obs = data, manifest, acts, obs
        self.dir = Directory(data)
        self.policy = Policy.load(data)
        self.by_rid: dict[str, list[Obs]] = defaultdict(list)
        self.files_of_rid: dict[str, set[str]] = defaultdict(set)
        self.rid_owners: dict[str, set[str]] = defaultdict(set)
        for o in obs:
            self.by_rid[o.rid].append(o)
            self.files_of_rid[o.rid].add(o.fid)
            for k in o.keys:
                self.rid_owners[o.rid] |= self.dir.owner.get(k, set())
        self.obs_index: dict[tuple, list[Obs]] = defaultdict(list)
        for o in obs:
            self.obs_index[(o.fid, o.rid)].append(o)
        self.dw = [a for a in acts if a["source_system"] == "deletion_worker"]
        self.acts_by_id = {a['activity_id']: a for a in acts}
        self.edges = build_edges(acts) if config.USE_LINEAGE else []

    # ------------------------------------------------------------ linking
    def direct(self, case):
        uid = self.dir.resolve(case["email"])[0]
        keys = self.dir.users[uid]["keys"]
        lk = [o for o in self.obs if o.t <= case["audit_at"] and o.keys & keys]
        return uid, lk

    def link_all(self, cases: list[dict], learn_exclude=frozenset(), hide_accounts=frozenset()) -> None:
        """Direct identity links, then activity-based links with global one-resource-one-case propagation.

        Phase 1 assigns an account to cases whose identifiers never reach an account record (deletion-worker window + result
        consistent with the claimed status + elimination + co-occurrence, then global uniqueness). Phase 2 assigns policy-action
        resources (analytics/support/flow/backup/...) using a workflow-run alignment model *learned from evidence-confirmed links*.
        """
        slack = timedelta(days=1)
        info, owned = {}, defaultdict(set)
        ncases = defaultdict(int)
        for c in cases:
            ncases[self.dir.resolve(c["email"])[0]] += 1
        for c in cases:
            uid, lk = self.direct(c)
            if ncases[uid] > 1 or not config.PARTITION_SINGLE_CASE_USERS_ONLY:
                lk = [o for o in lk if T(c["requested_at"]) - slack <= T(o.t)]  # older evidence belongs to the user's earlier request
            rids = {o.rid for o in lk}
            if c["case_id"] in hide_accounts:                               # link-recovery experiment: pretend the account is not identity-linked
                rids = {r for r in rids if prefix(r) != "account"}
            info[c["case_id"]] = (uid, rids, {o.fid for o in lk})
            for r in rids:
                owned[r].add(c["case_id"])
        self.info = info
        self.acc_event = {a["resource_id"]: a for a in self.dw if a["event_type"] == "DELETE_RECORD" and a["target_system"] == "account_service"}
        learned = self._learn_alignment(info, learn_exclude)
        self.ambiguous = set(); self.extra = defaultdict(set)

        def window(c, a, p):
            R = T(c["reported_at"]); t = T(a["event_time"])
            if p == "account":
                return a["event_type"] == "DELETE_RECORD" and R - timedelta(minutes=180) <= t <= R + timedelta(minutes=15)
            return R - timedelta(minutes=60) <= t <= R

        def propagate(cands):
            assigned, changed = {}, True
            while changed:
                changed = False
                taken = set(assigned.values())
                for k, rs in cands.items():
                    live = [r for r in rs if r not in taken] if k not in assigned else []
                    if k not in assigned and len(live) == 1:
                        assigned[k] = live[0]; taken.add(live[0]); changed = True
            taken = set(assigned.values())
            for k, rs in sorted(cands.items()):     # residual ambiguity: deterministic tie-break, case flagged for review
                live = [r for r in rs if r not in taken]
                if k not in assigned and live:
                    assigned[k] = live[0]; taken.add(live[0])
                    if len(live) > 1:
                        self.ambiguous.add(k[0])
            return assigned

        # ---- phase 1: accounts
        cands = {}
        for c in cases:
            cid = c["case_id"]; uid, rids, cfiles = info[cid]
            if any(prefix(r) == "account" for r in rids):
                continue
            want = STATUS_RESULT.get(c["reported_status"])
            acts = [a for a in self.dw if prefix(a["resource_id"]) == "account" and window(c, a, "account") and a["reported_result"] == want
                    and a["resource_id"] not in owned and not (self.rid_owners[a["resource_id"]] - {uid})]
            known = [x for rid in rids for x in self.dw if x["resource_id"] == rid and prefix(rid) != "account"]
            if known and config.USE_RUN_ALIGNMENT:      # one deletion run => sibling actions sit at the run's learned second-offsets from its account delete
                al = [a for a in acts if all(self._aligned(T(a["event_time"]), T(k["event_time"]), prefix(k["resource_id"]), k, learned) for k in known)]
                acts = al or acts
            rs = [a["resource_id"] for a in acts]
            co = [r for r in rs if self.files_of_rid[r] & cfiles]
            if rs:
                cands[(cid, "account")] = co or rs
        self.account_cands = dict(cands)
        for (cid, _), r in propagate(cands).items():
            self.extra[cid].add(r)
        # ---- phase 2: policy-action resources aligned to the case's account run
        if config.USE_RUN_ALIGNMENT:
            self._bootstrap_alignment([c for c in cases if c['case_id'] not in learn_exclude], info, owned, learned, window)
        cands = {}
        taken_all = {r for rs in self.extra.values() for r in rs}
        for c in cases:
            cid = c["case_id"]; uid, rids, cfiles = info[cid]
            acc = next((r for r in list(rids) + list(self.extra[cid]) if prefix(r) == "account" and r in self.acc_event), None)
            groups: dict[str, list] = {}
            for a in self.dw:
                rid = a["resource_id"]; p = prefix(rid)
                if p == "account" or rid in rids or rid in owned or rid in taken_all or (self.rid_owners[rid] - {uid}):
                    continue
                if not (self._is_policy(a) and window(c, a, p)):
                    continue
                if acc and config.USE_RUN_ALIGNMENT and not self._aligned(T(self.acc_event[acc]["event_time"]), T(a["event_time"]), p, a, learned):
                    continue
                groups.setdefault(p, []).append(rid)
            for p, rs in groups.items():
                co = [r for r in rs if self.files_of_rid[r] & cfiles]
                cands[(cid, p)] = co or rs
        for (cid, _), r in propagate(cands).items():
            self.extra[cid].add(r)

    def _bootstrap_alignment(self, cases, info, owned, learned, window) -> None:
        """Types never seen with an identity link (anonymised analytics) have no learned offsets yet: learn them from windows
        that contain exactly one candidate of that type (unambiguous), then use the result as the alignment filter."""
        need = {"analytics"}
        for p in need:
            if sum(learned.get((p, True), {}).values()) >= 8:
                continue
            for c in cases:
                cid = c["case_id"]; uid, rids, _ = info[cid]
                acc = next((r for r in list(rids) + list(self.extra[cid]) if prefix(r) == "account" and r in self.acc_event), None)
                if not acc:
                    continue
                cs = [a for a in self.dw if prefix(a["resource_id"]) == p and self._is_policy(a) and window(c, a, p)
                      and a["resource_id"] not in owned and not (self.rid_owners[a["resource_id"]] - {uid})]
                if len(cs) == 1:
                    d = int((T(cs[0]["event_time"]) - T(self.acc_event[acc]["event_time"])).total_seconds())
                    if 0 < d < 4 * 3600:
                        learned[(p, True)][d % 60] += 1
            hist = learned.get((p, True), {})        # bootstrap is noisy: keep only the dominant offsets
            if hist:
                top = max(hist.values())
                learned[(p, True)] = defaultdict(int, {k: v for k, v in hist.items() if v >= 0.5 * top})

    @staticmethod
    def _is_policy(a) -> bool:
        return a["details"].startswith("Policy action completed")

    def _learn_alignment(self, info, exclude=frozenset()) -> dict:
        """(prefix, template) -> {second-offset mod 60 -> count} from resources directly linked together with their account."""
        learned: dict = defaultdict(lambda: defaultdict(int))
        by_rid = defaultdict(list)
        for a in self.dw:
            by_rid[a["resource_id"]].append(a)
        for cid, (_, rids, _) in info.items():
            if cid in exclude:
                continue
            acc = next((r for r in rids if r in self.acc_event), None)
            if not acc:
                continue
            t0 = T(self.acc_event[acc]["event_time"])
            for r in rids:
                p = prefix(r)
                if p == "account":
                    continue
                for a in by_rid.get(r, []):
                    d = int((T(a["event_time"]) - t0).total_seconds())
                    if 0 < d < 4 * 3600:
                        learned[(p, self._is_policy(a))][d % 60] += 1
        return learned

    def _aligned(self, t0, t1, p, a, learned) -> bool:
        d = int((t1 - t0).total_seconds())
        if not 0 < d < 4 * 3600:
            return False
        seen = learned.get((p, self._is_policy(a)))
        if not seen:
            return True
        tot = sum(seen.values())
        return seen.get(d % 60, 0) >= max(2, 0.03 * tot)

    # ------------------------------------------------------------ state + plan
    def state_of(self, rid: str, audit: str):
        """Latest state of a resource at audit_at. Two-tier time model (config.STRICT_TIME): only files captured by audit_at may
        decide the state and be cited; a later-exported file is used (uncited=True) only if nothing citable exists."""
        os_ = [o for o in self.by_rid.get(rid, []) if o.t <= audit]    # record time decides state
        if not os_:
            return None
        discovered = max(os_, key=lambda o: (o.t, o.fcap))             # record *type* is static: any record stamped <= audit_at tells it
        uncited = False
        if config.STRICT_TIME:
            citable = [o for o in os_ if o.fcap <= audit]
            if citable:
                os_ = citable
            else:
                uncited = True
        os_.sort(key=lambda o: (o.t, o.fcap))
        last_t = os_[-1].t
        latest = [o for o in os_ if o.t == last_t]
        st = latest[-1].state
        for o in latest:                                  # replica drift: any copy still alive at that instant counts
            if o.state in ("PRESENT", "PII", "ACTIVE", "RESTORABLE"):
                st = o.state
        cit = [o for o in os_ if o.state == st and o.fcap <= audit] or [o for o in os_ if o.fcap <= audit]   # citation: captured by audit_at
        ev = max(cit, key=lambda o: (o.t, o.fcap)).fid if cit else None
        attrs: dict = {}
        for o in os_:
            if o.attrs.get("state_unverified"):
                continue                                   # a default guessed from the id family is not a fact about the record
            attrs.update(o.attrs)
        deciding = [o for o in os_ if o.fid == ev and o.state == st]
        unverified = bool(deciding) and all(o.attrs.get("state_unverified") for o in deciding)
        return State(st, ev, discovered.kind if config.STRICT_TIME else latest[-1].kind, latest[-1].sys, attrs, uncited, unverified)

    def coverage_file(self, sysid: str, audit: str):
        """Latest file captured by audit_at that snapshots this system; proves absence of records it does not list."""
        fs = {o.fid for o in self.obs if o.sys == sysid and o.fcap <= audit and o.fid in self.manifest and o.kind != "catalog"}
        return max(fs, key=lambda f: self.manifest[f]["captured_at"]) if fs else None

    def solve(self, case: dict) -> dict:
        audit = case["audit_at"]
        uid, rids, _ = self.info[case["case_id"]]
        linked = set(rids) | self.extra.get(case["case_id"], set())
        lineage = {}                                             # recreated downstream copies: rid -> Edge (propagation along activity edges)
        if self.edges:
            taken = {r for cid, (_, rs, _) in self.info.items() if cid != case["case_id"] for r in rs}
            taken |= {r for cid, rs in self.extra.items() if cid != case["case_id"] for r in rs}
            for ed in downstream(self.edges, linked, audit):
                if ed.dst not in taken and not (self.rid_owners.get(ed.dst, set()) - {uid}):
                    lineage[ed.dst] = ed
            linked |= set(lineage)
        res, rflags = {}, {}
        for rid in linked:
            s = self.state_of(rid, audit)
            rflags[rid] = []
            if s:
                st, ev, kind, sysid, attrs = s.state, s.evidence, s.kind, s.system, s.attrs
                if s.uncited: rflags[rid].append("uncited_state")
                if s.unverified: rflags[rid].append("state_unverified")
            elif rid in lineage:                         # no snapshot of the recreated copy: the repopulation activity is the proof
                ed = lineage[rid]; st, ev, kind, sysid, attrs = "PRESENT", ed.activity_id, "lineage", ed.target_system, {}
            else:
                st, ev, kind, sysid, attrs = "ABSENT", None, "", SYS_OF_PREFIX.get(prefix(rid), "unknown"), {}
            sysid = sysid or SYS_OF_PREFIX.get(prefix(rid), "unknown")
            if ev is None and st == "ABSENT":
                ev = "?cov"
            res[rid] = (sysid, st, ev, kind, attrs)
        evs = [v[2] for v in res.values() if v[2] in self.manifest]       # snapshot files only (activity ids carry no capture time)
        primary = max(evs, key=lambda f: self.manifest[f]["captured_at"]) if evs else None
        res = {r: (v[0], v[1], (primary or self.coverage_file(v[0], audit)) if v[2] == "?cov" else v[2], v[3], v[4]) for r, v in res.items()}
        findings, rem, ver, viol_any, decisions = [], [], [], False, {}
        for rid, (sysid, st, ev, kind, attrs) in res.items():
            d = self.policy.decide(rid, st, kind, attrs, audit, len(self.rid_owners.get(rid, ())))
            d.flags += rflags.get(rid, [])
            decisions[rid] = d
            if d.violation:
                viol_any = True
                findings.append((d.finding, sysid, rid, ev or primary)); rem.append((d.remediation, sysid, rid, ""))
            ver.append((d.verify, sysid, rid, ev or primary))
        status = "INCOMPLETE" if viol_any else "COMPLETE"
        rows = findings + rem + [(v, s, r, "") for v, s, r, _ in ver] if viol_any else ver
        rows.sort(key=lambda x: (PHASES.index(PHASE[x[0]]), OP_ORDER.index(x[0]), x[1], x[2]))
        steps = [{"step_no": i, "phase": PHASE[op], "system_id": s, "resource_id": r, "operation": op,
                  "state": OP_STATE[op], "evidence_id": e or ""} for i, (op, s, r, e) in enumerate(rows, 1)]
        reason = {r: ("identity" if r in rids else "lineage:" + lineage[r].activity_id if r in lineage else "workflow-run") for r in linked}
        return {"status": status, "steps": steps, "resources": res, "uid": uid, "decisions": decisions, "lineage": lineage, "reason": reason}
