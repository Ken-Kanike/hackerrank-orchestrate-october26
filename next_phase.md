> **Progress (2026-10-25, Claude Sonnet 5.5):** Phases 0, 1, 2, 3, 6.1, 6.2 (advisory), 6.3, 7, 8 done; Phase 4 done except 4.4 (strength ranking), 4.5 (per-row vision),
> 4.7 (PDF extraction) and 4.8 (measured: not needed, leak check added instead); Phase 5 done except 5.1 (learned windows) and 5.2 (Hungarian). See the status table at the top of
> `limitations.md` for the reason behind every skipped item. Gate: `python code/tools/gate.py`. Accepted output reference: `code/evaluation/accepted_output.csv`
> (differs from the hand-off baseline `baseline_output.csv` by exactly one case, case_34).

# next_phase.md — Step-by-step fix plan (for any agent/model continuing this work)

Read first, in this order: `AGENTS.md` (logging rules, mandatory), `research_and_plan.md` (dataset findings + design),
`limitations.md` (every problem with ID, evidence and fix), `code/README.md` (how to run). Item IDs below (A1, B2, …) refer to `limitations.md`.

## 0. Ground rules (do not break any of these)
1. **Never** use organizer-only files, golden answers, case-ID lists, or ID-pattern tricks (e.g. `user_04 → account_004`). Never hardcode text
   copied from `deletion_requests.csv` into rules. Never read `dataset/sample_output.csv` anywhere except `code/evaluation/`.
2. **Never print or log secrets.** Do not print `os.environ`, router state, request headers or `.env`. Keys only via env/.env.
3. **Do not commit.** The user commits manually.
4. **Append a `log.txt` entry after every user turn** exactly as in AGENTS.md §5.2. Get the timestamp with `date -u +%Y-%m-%dT%H:%M:%SZ`,
   quote the prompt verbatim, and set `tool=` (your harness) and `model=` (your exact model id). Never edit old entries.
5. **One change at a time, measured.** After every task run the regression gate (§1). Keep a change only if the gate passes and the
   task's own acceptance criteria pass. Otherwise revert it and record why in `code/evaluation/experiments.jsonl` (created in task 1.3).
6. Keep the deterministic path working with **no API keys** (`--mode offline`). The LLM is an add-on, never a single point of failure.
7. Don't chase the 32 samples to 100%: about 6 expected steps are unreachable from participant data (see `limitations.md` A8 / G1).

## 1. Regression gate (run after every task)
```bash
python code/evaluation/main.py --mode offline          # must stay: status 32/32, precision >= 0.98, recall >= 0.965
python code/evaluation/custom_cases/test_custom_cases.py   # all pass
python code/main.py --mode offline --out /tmp/out.csv  # 518 rows, 0 validation flags
python code/tools/diff_outputs.py output.csv /tmp/out.csv   # (task 1.4) review every changed case; explain each in experiments.jsonl
```
Baseline at hand-off: status 32/32, precision 1.000, recall 0.969, exact 27/32, 518 rows, 0 flags, 17 tie-broken cases.
Before starting, save the current output: `copy output.csv code/evaluation/baseline_output.csv`.

---

## Phase 0 — Safety (15 min)
- **0.1 (A4)** Tell the user to rotate the 5 Groq keys before sharing any trace. Add `code/tests/test_router_no_secrets.py`. It builds a `Router`,
  forces a fake 429 on a fake key, then asserts that `str(router.__dict__)` does not contain the key.
- **0.2 (A5)** From now on, log turns correctly (rule 4). Do not edit previous entries.

## Phase 1 — Measurement first (do this before any logic change)
- **1.1 (G2) Real field-level and sequence metrics** in `code/evaluation/main.py:score()`:
  - Align predicted and gold steps by key `(resource_id, phase)`. For aligned pairs, count equality of `system_id`, `operation`, `state` and
    `evidence_id` separately.
  - Position accuracy: the fraction of gold steps whose `step_no` equals the predicted `step_no` for the same aligned key.
  - Sequence: exact array equality (existing), plus normalised Kendall tau over aligned keys, plus LCS ratio.
  - Remove the unused counters (`f_sys`…`ev_ok`).
  - Acceptance: the output JSON contains `field_acc.{system_id,operation,state,evidence_id}`, `position_acc`, `kendall_tau`, `lcs_ratio`.
- **1.2 (G1) Held-out estimate:** add `--folds 2 --repeats 5` to `code/evaluation/main.py`. Split the 32 samples randomly with a fixed seed.
  Data-driven parameters (alignment model, learned windows) must be learned using only the training half's evidence links. All
  identity-linked evidence is fine to use (it is not gold). Report mean ± std on the test halves. Acceptance: the command prints a fold table.
- **1.3 (G3) Experiment log:** `code/evaluation/main.py --record "<short description>"` appends
  `{"ts","desc","git_diff_stat","metrics":{...}}` to `code/evaluation/experiments.jsonl`. `reports.py` renders the "failures and improvements"
  table from this file instead of the typed text. Remove the typed numbers from `TEMPLATE_EVAL`.
- **1.4 Output diff tool:** `code/tools/diff_outputs.py A.csv B.csv` prints, per changed case, added/removed steps and status changes.

## Phase 2 — Policy as data (B1, highest impact on code-review score)
- **2.1** Create `code/auditor/policy.py`:
  ```python
  @dataclass
  class Rule: rule_id: str; category: str; condition: str; action: str   # loaded from dataset/deletion_rules.csv

  CATEGORY_OF = {   # observation kind -> data category (single source of truth; move SYS/prefix maps here too)
    "customer_profiles": "USER_PROFILE", "USER_PROFILE": "USER_PROFILE", "profile_lookup_completed": "USER_PROFILE", "profile_lookups": "USER_PROFILE",
    "customer_search_documents": "SEARCH_INDEX_ENTRY", "search_documents_primary": "SEARCH_INDEX_ENTRY", "SEARCH_INDEX_ENTRY": "SEARCH_INDEX_ENTRY",
    "index_queries": "SEARCH_INDEX_ENTRY", "index_query_completed": "SEARCH_INDEX_ENTRY",
    "support_conversations": "SUPPORT_MESSAGE", "support_records": "SUPPORT_MESSAGE", "tickets": "SUPPORT_MESSAGE", "SUPPORT_MESSAGE": "SUPPORT_MESSAGE",
    "message_pii_scan": "SUPPORT_MESSAGE", "message_read": "SUPPORT_MESSAGE", "support_ticket_read_completed": "SUPPORT_MESSAGE",
    "ticket_attachments": "SUPPORT_ATTACHMENT", "SUPPORT_ATTACHMENT": "SUPPORT_ATTACHMENT", "attachment_pii_scan": "SUPPORT_ATTACHMENT",
    "customer_analytics_reports": "ANALYTICS_PROFILE", "customer_analytics_profiles": "ANALYTICS_PROFILE", "profiles": "ANALYTICS_PROFILE",
    "ANALYTICS_PROFILE": "ANALYTICS_PROFILE", "analytics_profile_read": "ANALYTICS_PROFILE", "analytics_profile_read_completed": "ANALYTICS_PROFILE",
    "analytics_identity_scan": "ANALYTICS_PROFILE", "contact_lookup_completed": "SECONDARY_IDENTIFIER",
    "customer_export_jobs": "USER_EXPORT", "customer_exports": "USER_EXPORT", "exports": "USER_EXPORT", "USER_EXPORT": "USER_EXPORT",
    "export_download_check_completed": "USER_EXPORT", "export_metadata_read_completed": "USER_EXPORT",
    "security_audit_events": "SECURITY_AUDIT_LOG", "security_audit_records": "SECURITY_AUDIT_LOG", "audit_records": "SECURITY_AUDIT_LOG",
    "SECURITY_AUDIT_LOG": "SECURITY_AUDIT_LOG", "audit_record_read_completed": "SECURITY_AUDIT_LOG",
    "retained_order_records": "LEGAL_HOLD_RECORD", "LEGAL_HOLD_RECORD": "LEGAL_HOLD_RECORD", "retained_order_loaded": "LEGAL_HOLD_RECORD",
    "backup_catalog": "BACKUP_ARCHIVE", "backup_restore_entries": "BACKUP_ARCHIVE", "restore_entries": "BACKUP_ARCHIVE", "BACKUP_ARCHIVE": "BACKUP_ARCHIVE",
    "deleted_customer_references": "ACCOUNT_TOMBSTONE",
    "connector_configurations": "DATA_FLOW", "connector_subscriptions": "DATA_FLOW", "connectors": "DATA_FLOW", "DATA_FLOW": "DATA_FLOW",
  }
  ```
  Keep the resource-prefix fallback (`account→USER_PROFILE`, `marketing→MARKETING_PROFILE`, `object→SUPPORT_ATTACHMENT`, `tombstone→ACCOUNT_TOMBSTONE`,
  `data_flow→DATA_FLOW`, `backup→BACKUP_ARCHIVE`, `cache→CACHE_ENTRY`, `email_delivery→EMAIL_DELIVERY_LOG`) **only** when the kind is unknown,
  and mark that case `category_inferred=True` in the trace.
  - `contact_query_completed` (support replica *contact* index) maps to `SECONDARY_IDENTIFIER`. Check sample case_10 still behaves the same
    (expected DELETE `support_002`).
- **2.2 Conditions as predicates over the case's evidence**, evaluated at `audit_at`:
  - `SECURITY_AUDIT_LOG`: retain if `retention_until` (parse it in evidence.py into `Obs.attrs`) is ≥ `audit_at` or unknown. Otherwise the action
    becomes DELETE and must be flagged.
  - `LEGAL_HOLD_RECORD`: retain if `retained_until` is ≥ `audit_at`.
  - `SUPPORT_ATTACHMENT`: DELETE if the attachment's owner set contains only the subject (an object-storage catalog line "belongs only to … no other
    subject" or a single `uploaded_by`). If shared, REDACT and flag.
  - `SUPPORT_MESSAGE`: REDACT (the rule's condition is the normal case). If the message has no shared context and only the subject, still REDACT and flag.
  - `ANALYTICS_PROFILE` / `PRODUCT_TELEMETRY`: ANONYMIZE if attributable (any subject key in the record). Otherwise compliant.
  - `EMAIL_DELIVERY_LOG`: REDACT if it contains any subject email.
  - `ACCOUNT_TOMBSTONE`: REDACT if any of name/email/phone/email_hash is present.
  - `BACKUP_ARCHIVE`: RETAIN, with BLOCK_RESTORE if restore is allowed.
  - `DATA_FLOW`: disable if enabled.
  - DELETE categories: delete if present.
- **2.3** Action → operations table (finding / remediation / verification) in `policy.py`. **Replace** `engine.treatment()` with
  `policy.decide(obs_category, state, attrs, audit_at) -> Decision(violation, finding_op, remediation_op, verify_op, rule_id, flags)`.
- **2.4** Unit tests in `code/tests/test_policy.py`, one per rule, including expired retention → DELETE and a shared attachment → REDACT+flag.
- **2.5 Edit-the-CSV test:** copy `deletion_rules.csv` to a temp directory, change `ANALYTICS_PROFILE` to `DELETE`, run the pipeline against that
  directory, and assert that the analytics steps change to `REPORT_REMAINING_RECORD`/`DELETE_RECORD`. This proves the policy is data-driven.
- Acceptance: the regression gate passes, the output diff is empty (or every change is explained), and the 2.5 test passes.

## Phase 3 — Intent gate rewrite (A1, F4)
- **3.1** Delete the dataset-copied phrases from `intent.py` (`NA_TOPICS` and the copied `NEGATIONS`). Build `RIGHTS_LEXICON` from **generic**
  vocabulary for 10 languages (en, es, pt, fr, de, it, ko, ja, zh, ar) with these keys:
  - `erasure`: delete, erase, remove my account/data, close account, forget me, wipe; borrar/eliminar; excluir/apagar; supprimer/effacer;
    löschen; cancellare; 삭제; 削除; 删除; حذف.
  - `access`: copy of my data, what data you hold.
  - `portability`: download/export my data.
  - `rectification`: correct/update/change name/email/phone/address.
  - `objection_marketing`: unsubscribe, marketing, promotional, newsletter, stop emails.
  - `restriction`, `account_support` (password/login), `billing` (invoice/refund/charge).
  - Negation and scope limiters: "not … delete", "don't delete/close", "keep my account", "only <X>", "without deleting".
- **3.2 LLM as the primary classifier for every distinct text**, batched: 25 texts per call, ids are row indexes, and the request text is
  wrapped as data. JSON schema:
  `{"items":[{"id":int,"rights":["erasure"|"access"|...],"authorizes_deletion":bool,"negated":bool,"confidence":0..1}]}`.
  Use the cached router task `intent_v2`. Validate the schema; re-ask once on failure.
- **3.3 Decision rule (guardrail):**
  - DELETE when `erasure` is present and not negated or scope-limited, by rules OR by the LLM with confidence ≥ 0.7, *and* the other side does not report an explicit negation.
  - When only one side says erasure and the other says not, flag the case and use the rule result.
  - Log disagreements to the review report (F4).
  - Offline: rules only.
- **3.4** `code/tests/test_intent.py`: ≥40 probes written independently, never copied from `deletion_requests.csv`. Include multilingual
  deletion, every non-deletion right, negation, scope limiting, injection attempts and follow-up phrasing ("my account page is gone but …").
  Rules must reach ≥90% on the probes offline.
- Acceptance: the gate passes, NOT_APPLICABLE remains exactly case_533–542 in the eval output (if not, inspect each change manually), and the probe tests pass.

## Phase 4 — Evidence model upgrades
- **4.1 (A3) Two-tier time model** in `engine.state_of()`:
  - (a) Choose state from observations with `fcap <= audit_at` and `t <= audit_at` (citable).
  - (b) Only if there are none, use observations with `t <= audit_at` from later files, and mark `uncited=True`.
  - (c) The citation must be an observation whose state equals the chosen state. If none exists, for COMPLETE cases cite the best scope-complete
    snapshot (4.4) and set flag `weak_citation`.
  - Measure on the samples. Keep whichever variant scores higher on the held-out folds, and write the reasoning in experiments.jsonl.
  - Add the validator rule "cited evidence must not contradict the step state".
- **4.2 (C2) Activity state checks as weak observations:** in `evidence.py` add `activity_obs(acts)`:
  - `CHECK_DATA_FLOW` "remains enabled" → ACTIVE.
  - `CHECK_RESTORE_ACCESS` "can still be restored" → RESTORABLE.
  - `RESTORE_BACKUP` → RESTORABLE (plus the edge in 4.3).
  - `fid = activity_id`, `fcap = event_time`, `kind = "activity_check"`, `strength = 1`.
  - Operation claims (DELETE/REDACT/ANONYMIZE/DISABLE/BLOCK results) are **not** observations.
- **4.3 (C1) Lineage graph and recreation:** `code/auditor/lineage.py` builds edges
  `(src_rid → dst_rid, time, activity_id, kind)` from:
  - SYNC_RECORD "Active connector repopulated downstream resource X" (src = data_flow);
  - RESTORE_BACKUP "Restore job repopulated downstream resource X" (src = backup);
  - SYNC_RECORD account_service→account_replication_cluster / failover (src = dst = same rid, replica copy).

  In `link_all`, for every resource linked to a case, add downstream resources whose edge time ≤ `audit_at`. Record the link reason
  "lineage:<activity_id>". The downstream state comes from evidence; if there is none, it is recreated → PRESENT, citing the activity_id.
  Measure: sample scores must not drop. List every eval case whose output changes and justify each one.
- **4.4 (C3, C4) Evidence strength and absence proofs:**
  - Strength ranks: SQL table snapshot or readback export = 4, record-lookup listing (handover / diagnostic / manifest) = 3,
    log readback = 2, screenshot/PDF = 2, activity check = 1.
  - `state_of` resolves by (record time, strength).
  - An absence proof is a file with `snapshot_scope` or a full table, or a readback list covering that system, captured ≤ `audit_at`.
  - Store `strength` on `Obs`.
- **4.5 (B2, D3, F3) Per-row artifact reading:**
  - New vision schema `{"rows":[{"resource_id","subject_ref","emails","phones","names","status":{"enabled","restore_allowed","shows_identifiers","availability"}}]}`.
  - Validate `resource_id` against `RID_RE`; on failure re-ask once with the hint "copy ids exactly".
  - Build observations per row. A row links to the subject if its identifiers match the subject's keys, or if a catalog event names that row.
  - Offline fallback: if `pytesseract` and the tesseract binary are available, OCR the image and run the same regex extractors. Otherwise use
    `PREFIX_STATE` only as `state_unverified=True` and add a review flag.
- **4.6 (D2) Identity corroboration for catalog links:**
  - For every `LINK_RESOURCE_IDENTITY`, compare the artifact's identifiers (vision rows / OCR / PDF text) with the subject's keys.
  - If they match the subject → link, strength as normal.
  - If they resolve to a **different known user** in `user_identities`/`user_audit_log` → drop the link and flag `catalog_contradicted`.
  - If they are unknown identifiers (e.g. case_63 shows "sj.park@naver.com", not a known user) → keep the link and flag
    `catalog_unverified_identity` in the review report. Do not silently change the status.
  - Document the rule in README.
- **4.7 (B5) PDF extraction:**
  - Extract all ID families with regex (resource IDs, `CS-\d+`, `ORD-\d+`, `NST-\d{4}-\d{4}-\d+`, `FIN-\d+`), dates
    ("retain until DD Mon YYYY"), emails, phones and user refs.
  - Map business references to resources using bundle fields (`ticket_id` ↔ `support_*`, `order_reference` ↔ `legal_hold_*`, catalog
    `(NST-…)` ↔ `export_*`).
  - Do not invent resource IDs from reference numbers.
- **4.8 (C5) Subject-aware PII recognizer:** `code/auditor/pii.py`.
  - `SubjectRecognizer(keys)` scans any string for: exact subject emails (case-insensitive), the subject's phones in any formatting (digits
    match), the subject's name tokens (only together with another signal), sha256 hashes of subject emails, and generic email/phone patterns.
  - Use it in `store_obs`/`_log_state` for free-text fields (`message_text`, `message_excerpt`, PDF text, OCR text) to decide PII vs CLEAN, and
    to verify REDACTED/ANONYMIZED claims.
- **4.9 Ghost sweep (L1):**
  - After linking, for each deletion case, scan the raw text of every evidence file (cache the file text once) for every subject identifier.
  - Consider only lines or records whose timestamp is ≤ `audit_at`. A hit whose resource_id (same line or record) is not linked becomes a
    `ghost_hit` review flag with file and line.
  - Report the count. Promote hits to links only when the line has a resource_id and a timestamp ≤ `audit_at`, and only if that improves the
    held-out folds.

## Phase 5 — Linking robustness
- **5.1 (B3)** Learn the windows from evidence-confirmed pairs (case with identity-linked account + its DELETE activity):
  - account-delete offset vs `reported_at`: use the [p1, p99] range, widened by 10%;
  - policy-action offset vs `reported_at`: same.
  - Move every remaining constant into `code/auditor/config.py` with a comment saying where it came from.
- **5.2 (D1) Global scored assignment** replacing `propagate()`. Build a cost matrix (case-slot × candidate) from:
  - −log-likelihood of the time offset under the learned distribution;
  - −2 when the candidate co-occurs in the case's evidence files;
  - −3 when the alignment test passes (only if alignment is enabled);
  - +∞ when the status/result do not match.

  Solve with a Hungarian algorithm (stdlib implementation in `code/auditor/assign.py`, ~60 lines, plus a unit test on a 3×3 example).
  Ambiguity = the gap between the best and second-best total < threshold → flag the case.
- **5.3 (A2)** Add `config.USE_RUN_ALIGNMENT` (default True), and report the ablation (on/off) in `evaluation_report.md` via experiments.jsonl.
  Rename it in code and docs to "workflow-run reconstruction" and describe it honestly.
- **5.4 (D4)** Apply the requested_at partition only for users with more than one case. Measure.
- **5.5 (D5)** Hash raw and lowercased emails; normalise phones to digits; names only as a corroborating signal.

## Phase 6 — LLM layer that matters (F1, F2)
- **6.1 Router fixes** (`router.py`):
  - Cache key = `(task, prompt_version, inputs)`; store provider/model in meta; add a `--refresh-llm` CLI flag.
  - On 400: mark the model dead only when the error body mentions the model or "not found"/"does not exist"; otherwise fail just that request.
  - Add a run budget (`LLM_MAX_SECONDS`, default 600) and `LLM_MAX_CALLS`.
  - Add a `concurrent.futures.ThreadPoolExecutor` with per-provider concurrency (Groq 2) for batch tasks.
  - Model discovery: on first use per provider, GET `/models` (OpenAI/Groq: `/v1/models`; Gemini: `v1beta/models`; Anthropic: `/v1/models`)
    and pick the first configured model that exists, otherwise the first preferred family match. Cache the list for the run.
  - Anthropic: send `"output_config": {"effort": "low"}` and `max_tokens >= 2000`; check `stop_reason` (`refusal` → treat as failure);
    no `temperature`.
  - Validate JSON against the per-task schema and re-ask once with the validation error appended.
  - Ledger fields: `run_id`, `task`, `ok`, `cached`, tokens (A7).
- **6.2 Investigator agent** `code/auditor/llm/investigator.py`. Runs only on flagged cases (ambiguous assignment, `catalog_contradicted`,
  `catalog_unverified_identity`, `ghost_hit`, `uncited`, intent disagreement).
  - OpenAI-compatible tool calling (works on Groq `openai/gpt-oss-120b`, OpenAI and Anthropic via its own format) with a manual loop, max 6 turns.
  - Tools (pure-python functions over the Engine): `get_case_dossier(case_id)`, `search_evidence(identifier)`, `resource_timeline(resource_id)`,
    `list_candidates(case_id, slot)`, `policy_for(category)`.
  - Output schema: `{"decisions":[{"slot":"account|analytics|...","choose":"<candidate id or null>","reason":"..."}],"flags":[...]}`.
  - Guardrails: `choose` must be one of the engine's candidates; the agent cannot change evidence-proven states or policy; an invalid output means the deterministic choice stands.
  - Measure on the samples (offline vs hybrid). Keep it enabled only if it does not reduce held-out metrics. If it is neutral, keep it enabled
    for flagged cases with the reason recorded (good for the interview), but the deterministic choice wins ties.
- **6.3 Usage report (A7):** `reports.py` reads only the ledger lines of the final run_id. Report "fresh calls/tokens this run" and "attributed
  tokens (cache hits counted with their original usage)". Mark free-tier cost as $0 and other prices as "list price, verified on <date>" or "unknown".

## Phase 7 — Evaluation assets
- **7.1 (G4) End-to-end custom cases:** add 6 folders under `code/evaluation/custom_cases/` (see limitations G4). Each folder contains
  `deletion_requests.csv`, `user_identities.csv`, `user_audit_log.csv`, `system_activity.csv`, `deletion_rules.csv`, `evidence_files.csv`,
  `evidence/...` and `expected_output.csv`.
  - `config.DATASET` must be overridable via the `--data DIR` CLI flag (add it to `main.py` and `evaluation/main.py`).
  - `python code/evaluation/main.py --data code/evaluation/custom_cases/<name> --gold expected_output.csv` must score each folder.
  - Describe every case (input, expected output, why) in `evaluation_report.md`, because judges ignore csv/json.
- **7.2 (G5) Trace and review report:** `code/runs/<run_id>/trace.jsonl` (per case: identity keys used, resources with link reason, observations
  used with fid/time/strength, policy rule_id, flags, confidence) and `code/runs/<run_id>/review.md` (flagged cases only).
  Add `code/runs/` to `.gitignore` except one example trace committed under `code/evaluation/example_trace.md`.
- **7.3** Regenerate the reports with `python code/evaluation/reports.py`. The report must include: sample metrics (offline/hybrid),
  held-out folds, field and sequence metrics, the ablation table (alignment, lineage, strict-time, investigator), custom cases, the experiment log
  table, the unreachable ceiling and honest limitations.

## Phase 8 — Docs, packaging, hand-in
- **8.1 (H1)** Root `README.md`: add an "Our solution" section at the top with the run commands and a pointer to `code/README.md`.
- **8.2 (H2)** `code/package.py` builds `code.zip` from `README.md` and `code/`. It excludes `.cache`, `runs`, `__pycache__`, `*.zip`, `.env`,
  `dataset`, then prints the archive listing and the total size.
- **8.3 (H3, H4, H5)** `code/tests/` per-format fixture tests; `python -m unittest discover code/tests`; `sys.stdout.reconfigure(encoding="utf-8")`
  in the entry points; pin `pypdf` in `code/requirements.txt`.
- **8.4** Update the STATUS section of `research_and_plan.md` and mark every fixed item in `limitations.md` with `**Status:** fixed in <task>`.
- **8.5 Final run:**
  - `python code/main.py` (hybrid with whatever keys exist).
  - Validator 0 flags; 518 rows; `python code/tools/diff_outputs.py code/evaluation/baseline_output.csv output.csv`, with every change reviewed.
  - `python code/evaluation/reports.py`.
  - `python code/package.py`.
- **8.6** Interview prep: `code/evaluation/interview_notes.md` covering the architecture walkthrough of one case trace, why the core is
  deterministic, where the LLM decides and its guardrails, the measured ablations, the known limits (unreachable ceiling, timing heuristic,
  catalog contradiction) and what you would do with more time.

## Suggested order if time is short
Phase 0 → 1.1/1.3/1.4 → 2 (policy) → 3 (intent) → 4.1 → 4.3 → 4.6 → 5.2 → 6.1 → 6.2 → 7.1/7.2 → 8. Phases 4.5, 4.8, 4.9, 5.1 and 5.4 come next.
Each item is independent enough to stop after any task with a working, validated `output.csv`.
