# Example trace - case_34

Produced by `python code/main.py`; one line of `code/runs/<run_id>/trace.jsonl`. This case is the one the ghost sweep found:
the user has a single request, so pre-request evidence (a log from 2026-09-15, request on 2026-09-24) still belongs to it.

```json
{
 "case_id": "case_34",
 "user_id": "user_11",
 "status": "INCOMPLETE",
 "intent": {
  "rule": "DELETE",
  "strength": "strong",
  "llm": null,
  "final": "DELETE"
 },
 "resources": [
  {
   "resource_id": "account_5762",
   "system_id": "account_service",
   "state": "PRESENT",
   "evidence_id": "evidence_04",
   "link": "identity",
   "category": "USER_PROFILE",
   "rule_id": "rule_01",
   "action": "DELETE",
   "violation": true,
   "flags": [
    "category_inferred",
    "state_unverified"
   ]
  },
  {
   "resource_id": "audit_record_3753",
   "system_id": "security_service",
   "state": "RETAINED",
   "evidence_id": "evidence_01",
   "link": "identity",
   "category": "SECURITY_AUDIT_LOG",
   "rule_id": "rule_12",
   "action": "RETAIN",
   "violation": false,
   "flags": [
    "retention_unknown"
   ]
  },
  {
   "resource_id": "support_9538",
   "system_id": "support_platform",
   "state": "PRESENT",
   "evidence_id": "evidence_01",
   "link": "identity",
   "category": "SUPPORT_ATTACHMENT",
   "rule_id": "rule_06",
   "action": "DELETE",
   "violation": true,
   "flags": []
  }
 ],
 "flags": [
  "category_inferred",
  "retention_unknown",
  "state_unverified"
 ]
}
```

How to read it: `link` says why the resource belongs to the case (`identity` = an identifier on the record matches the subject, `workflow-run` = reconstructed from the
deletion-worker activity stream, `lineage:<activity_id>` = recreated by a connector/restore job at or before audit_at); `rule_id`/`category`/`action` come from
`deletion_rules.csv`; `evidence_id` is the file (or activity) that proves the deciding state; `flags` are things a reviewer may want to look at.
