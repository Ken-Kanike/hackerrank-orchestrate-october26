"""Catalog corroboration (D2) and the validator's citation rules."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auditor.corroborate import corroborate  # noqa: E402
from auditor.evidence import Obs  # noqa: E402
from auditor.validate import validate_row  # noqa: E402


class Dir:
    owner = {"a@x.test": {"user_1"}, "user_1": {"user_1"}, "b@x.test": {"user_2"}, "user_2": {"user_2"}}


def cat(rid="marketing_1", keys=("a@x.test", "user_1")):
    return Obs("evidence_9", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "marketing_platform", rid, "PRESENT", "catalog", set(keys))


class Corroborate(unittest.TestCase):
    def test_matching_artifact_keeps_link_without_flag(self):
        keep, flags = corroborate([cat()], {"evidence_9": {"emails": ["A@x.test"], "users": []}}, Dir)
        self.assertEqual((len(keep), flags), (1, []))

    def test_other_known_user_drops_link(self):
        keep, flags = corroborate([cat()], {"evidence_9": {"emails": ["b@x.test"], "users": []}}, Dir)
        self.assertEqual(keep, []); self.assertEqual(flags[0]["flag"], "catalog_contradicted")

    def test_unknown_identity_keeps_link_but_flags(self):
        keep, flags = corroborate([cat()], {"evidence_9": {"emails": ["stranger@elsewhere.test"], "users": []}}, Dir)
        self.assertEqual(len(keep), 1); self.assertEqual(flags[0]["flag"], "catalog_unverified_identity")

    def test_unread_artifact_is_flagged_not_assumed(self):
        keep, flags = corroborate([cat()], None, Dir)
        self.assertEqual(len(keep), 1); self.assertEqual(flags[0]["flag"], "catalog_artifact_unread")


class ValidatorCitations(unittest.TestCase):
    man = {"evidence_1": {"captured_at": "2026-01-01T00:00:00Z"}}
    case = {"audit_at": "2026-02-01T00:00:00Z"}

    def row(self, op, state, ev, phase="VERIFICATION"):
        s = [{"step_no": 1, "phase": phase, "system_id": "account_service", "resource_id": "account_1", "operation": op, "state": state, "evidence_id": ev}]
        return {"case_id": "c", "deletion_status": "COMPLETE", "steps_json": json.dumps(s)}

    def test_activity_id_citation_accepted_until_audit(self):
        acts = {"activity_1": {"event_time": "2026-01-15T00:00:00Z"}, "activity_2": {"event_time": "2026-03-01T00:00:00Z"}}
        self.assertEqual(validate_row(self.row("VERIFY_RECORD_ABSENT", "ABSENT", "activity_1"), self.man, self.case, {}, acts), [])
        self.assertTrue(any("after audit_at" in e for e in validate_row(self.row("VERIFY_RECORD_ABSENT", "ABSENT", "activity_2"), self.man, self.case, {}, acts)))

    def test_cited_file_must_not_contradict_state(self):
        o = Obs("evidence_1", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "account_service", "account_1", "PRESENT")
        errs = validate_row(self.row("VERIFY_RECORD_ABSENT", "ABSENT", "evidence_1"), self.man, self.case, {("evidence_1", "account_1"): [o]})
        self.assertTrue(any("contradicts" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
