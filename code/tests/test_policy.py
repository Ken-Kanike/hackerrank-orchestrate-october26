"""Policy-as-data tests: one per rule family, plus the proof that editing deletion_rules.csv changes the output."""
import csv
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auditor.config import DATASET  # noqa: E402
from auditor.llm.router import Router  # noqa: E402
from auditor.pipeline import read_requests, run  # noqa: E402
from auditor.policy import Policy  # noqa: E402

AUDIT = "2026-09-01T00:00:00Z"


class PolicyRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pol = Policy.load(DATASET)

    def d(self, rid, state, kind, attrs=None, owners=1):
        return self.pol.decide(rid, state, kind, attrs, AUDIT, owners)

    def test_delete_categories(self):
        for rid, kind in (("account_1", "customer_profiles"), ("search_1", "customer_search_documents"), ("export_1", "customer_exports"),
                          ("marketing_1", "catalog"), ("support_1", "contact_query_completed"), ("support_2", "ticket_attachments")):
            x = self.d(rid, "PRESENT", kind)
            self.assertTrue(x.violation, rid); self.assertEqual((x.finding, x.remediation, x.verify),
                                                              ("REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT"))
            self.assertFalse(self.d(rid, "ABSENT", kind).violation)

    def test_redact_and_anonymize(self):
        x = self.d("support_1", "PII", "support_records")
        self.assertEqual((x.violation, x.remediation, x.verify), (True, "REDACT_RECORD", "VERIFY_RECORD_REDACTED"))
        self.assertFalse(self.d("support_1", "CLEAN", "support_records").violation)
        y = self.d("analytics_1", "PII", "customer_analytics_reports")
        self.assertEqual((y.violation, y.remediation, y.verify), (True, "ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED"))
        z = self.d("tombstone_1", "PII", "deleted_customer_references")
        self.assertEqual((z.violation, z.remediation), (True, "REDACT_RECORD"))
        self.assertFalse(self.d("tombstone_1", "CLEAN", "deleted_customer_references").violation)

    def test_retention_conditions(self):
        ok = self.d("audit_record_1", "RETAINED", "security_audit_events", {"retention_until": "2033-12-31T23:59:59Z"})
        self.assertEqual((ok.violation, ok.verify, ok.flags), (False, "VERIFY_RECORD_PRESENT", []))
        exp = self.d("audit_record_1", "RETAINED", "security_audit_events", {"retention_until": "2026-01-01T00:00:00Z"})
        self.assertEqual((exp.violation, exp.remediation), (True, "DELETE_RECORD")); self.assertIn("retention_expired", exp.flags)
        hold = self.d("legal_hold_1", "RETAINED", "retained_order_records", {"retained_until": "2026-02-01T00:00:00Z"})
        self.assertTrue(hold.violation)
        unk = self.d("legal_hold_1", "RETAINED", "retained_order_records")
        self.assertFalse(unk.violation); self.assertIn("retention_unknown", unk.flags)

    def test_shared_attachment_is_redacted_not_deleted(self):
        x = self.d("support_9", "PRESENT", "ticket_attachments", owners=2)
        self.assertEqual((x.action, x.remediation), ("REDACT", "REDACT_RECORD")); self.assertIn("shared_attachment", x.flags)

    def test_backup_and_flow(self):
        self.assertTrue(self.d("backup_1", "RESTORABLE", "backup_catalog").violation)
        self.assertEqual(self.d("backup_1", "RESTORABLE", "backup_catalog").remediation, "BLOCK_RESTORE")
        self.assertFalse(self.d("backup_1", "BLOCKED", "backup_catalog").violation)
        self.assertEqual(self.d("data_flow_1", "ACTIVE", "connectors").remediation, "DISABLE_DATA_FLOW")

    def test_unknown_kind_is_flagged_not_silent(self):
        x = self.d("support_1", "PII", "never_seen_kind")
        self.assertIn("category_inferred", x.flags)
        y = self.d("weird_1", "PRESENT", "never_seen_kind")
        self.assertIn("category_unmapped", y.flags)


class PolicyIsData(unittest.TestCase):
    def test_editing_rules_csv_changes_output(self):
        """ANALYTICS_PROFILE ANONYMIZE -> DELETE must turn analytics steps into REPORT_REMAINING_RECORD / DELETE_RECORD."""
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(DATASET, tmp / "ds")
            p = tmp / "ds" / "deletion_rules.csv"
            rows = list(csv.DictReader(open(p, encoding="utf-8")))
            for r in rows:
                if r["data_category"] == "ANALYTICS_PROFILE":
                    r["required_action"] = "DELETE"
            with open(p, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
            samples = read_requests("sample_deletion_requests.csv", tmp / "ds")
            out, _, _, _ = run(samples, samples, Router(enabled=False), tmp / "ds", use_vision=False, log=lambda *a: None)
            ops = {s["operation"] for r in out for s in json.loads(r["steps_json"]) if s["resource_id"].startswith("analytics_")}
            self.assertIn("DELETE_RECORD", ops); self.assertNotIn("ANONYMIZE_RECORD", ops)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
