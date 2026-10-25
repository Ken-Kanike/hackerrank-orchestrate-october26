# Inputs, outputs and policy

**Inputs** (`dataset/`): requests, identities, identifier-change audit log, global activity stream (claims, with decoys), `deletion_rules.csv`, evidence manifest and files (logs, JSON, SQL snapshots, PDFs, screenshots).

**Output** `output.csv`: `case_id,deletion_status,steps_json`. Statuses COMPLETE / INCOMPLETE / NOT_APPLICABLE (`[]`). Steps carry `step_no, phase, system_id, resource_id, operation, state, evidence_id`; phases FINDING, REMEDIATION, VERIFICATION; remediation and verification use an empty evidence id.

| Action | Finding | Remediation | Verification |
|---|---|---|---|
| DELETE | REPORT_REMAINING_RECORD | DELETE_RECORD | VERIFY_RECORD_ABSENT |
| REDACT | REPORT_EXPOSED_PII | REDACT_RECORD | VERIFY_RECORD_REDACTED |
| ANONYMIZE | REPORT_EXPOSED_PII | ANONYMIZE_RECORD | VERIFY_RECORD_ANONYMIZED |
| RETAIN | none | none | VERIFY_RECORD_PRESENT |
| RETAIN with restorable backup | REPORT_RESTORE_RISK | BLOCK_RESTORE | VERIFY_RESTORE_BLOCKED |
| active connector | REPORT_ACTIVE_DATA_FLOW | DISABLE_DATA_FLOW | VERIFY_DATA_FLOW_DISABLED |

Conditions are evaluated from evidence at `audit_at`: an expired `retention_until` / `retained_until` turns RETAIN into DELETE; a shared attachment becomes REDACT; unknown categories are flagged, never silently defaulted. Editing `deletion_rules.csv` changes the output (unit-tested). Remediation order: disable flows and block restores first, downstream copies before sources.
