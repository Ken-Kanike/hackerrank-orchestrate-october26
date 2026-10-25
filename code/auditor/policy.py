"""Declarative deletion policy: dataset/deletion_rules.csv -> per-record decision.

A record is classified into a data category (taxonomy.CATEGORY_OF; resource-id family only as a flagged fallback), the category's
rule supplies the required action, and a condition predicate evaluated from the record's own evidence (retention dates against
audit_at, sharing, attributability) decides whether the rule applies as written. Changing deletion_rules.csv changes the output.

Unknown category or unevaluable condition never passes silently: the Decision carries flags that end up in the review report.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .taxonomy import CATEGORY_OF, CATEGORY_OF_PREFIX, prefix

# action -> (finding op, remediation op, verification op). A violation exists when the record is in a "bad" state for the action.
ACTION_OPS = {
    "DELETE": ("REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT"),
    "REDACT": ("REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED"),
    "ANONYMIZE": ("REPORT_EXPOSED_PII", "ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED"),
    "RETAIN": (None, None, "VERIFY_RECORD_PRESENT"),
    "RETAIN_BLOCK_RESTORE": ("REPORT_RESTORE_RISK", "BLOCK_RESTORE", "VERIFY_RESTORE_BLOCKED"),
    "DISABLE": ("REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED"),
}
BAD_STATES = {"DELETE": {"PRESENT", "PII", "RETAINED"}, "REDACT": {"PII"}, "ANONYMIZE": {"PII"}, "RETAIN": set(),
              "RETAIN_BLOCK_RESTORE": {"RESTORABLE"}, "DISABLE": {"ACTIVE"}}
# Not in deletion_rules.csv: the challenge contract (problem statement 6.4) requires active connectors to be disabled.
BUILTIN = {"DATA_FLOW": ("builtin_data_flow", "Connector is enabled", "DISABLE")}
RETENTION_ATTR = {"SECURITY_AUDIT_LOG": "retention_until", "LEGAL_HOLD_RECORD": "retained_until"}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    category: str
    condition: str
    action: str


@dataclass
class Decision:
    violation: bool
    finding: str | None
    remediation: str | None
    verify: str
    rule_id: str
    category: str
    action: str
    flags: list = field(default_factory=list)


class Policy:
    def __init__(self, rules: list[Rule]):
        self.rules = rules
        self.by_cat = {r.category: r for r in rules}

    @classmethod
    def load(cls, data: Path) -> "Policy":
        with open(Path(data) / "deletion_rules.csv", encoding="utf-8") as f:
            return cls([Rule(r["rule_id"], r["data_category"], r["condition"], r["required_action"].strip().upper())
                        for r in csv.DictReader(f)])

    def category(self, rid: str, kind: str) -> tuple[str, bool]:
        """(category, inferred_from_prefix)."""
        if kind in CATEGORY_OF:
            return CATEGORY_OF[kind], False
        return CATEGORY_OF_PREFIX.get(prefix(rid), "UNKNOWN"), True

    def decide(self, rid: str, state: str, kind: str, attrs: dict | None, audit_at: str, owners: int = 1) -> Decision:
        attrs = attrs or {}
        cat, inferred = self.category(rid, kind)
        flags = ["category_inferred"] if inferred and cat != "UNKNOWN" else []
        if cat in BUILTIN:
            rule_id, _, action = BUILTIN[cat]
        elif cat in self.by_cat:
            rule = self.by_cat[cat]; rule_id, action = rule.rule_id, rule.action
        else:
            flags.append("category_unmapped")                       # no rule: be conservative (delete) but surface it
            rule_id, action = "none", "DELETE"
        if action == "RETAIN":
            until = attrs.get(RETENTION_ATTR.get(cat, ""))
            if cat == "BACKUP_ARCHIVE":
                action = "RETAIN_BLOCK_RESTORE"                     # rule: "Restore access can be blocked" -> block the path, keep the record
            elif cat in RETENTION_ATTR:
                if until and until < audit_at:                      # condition fails: retention/hold lapsed before audit_at
                    action = "DELETE"; flags.append("retention_expired")
                elif not until:
                    flags.append("retention_unknown")
        elif cat == "SUPPORT_ATTACHMENT" and action == "DELETE" and owners > 1:
            action = "REDACT"; flags.append("shared_attachment")    # condition "belongs only to the subject" fails
        f, r, v = ACTION_OPS[action]
        return Decision(state in BAD_STATES[action], f, r, v, rule_id, cat, action, flags)
