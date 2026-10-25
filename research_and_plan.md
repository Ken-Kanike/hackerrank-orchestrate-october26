# Research & Plan — Ghost Data Still Exists (HackerRank Orchestrate Oct 2026)

> Context file for any agent/IDE continuing this work. Read this, then `AGENTS.md` (logging rules), then
> `code/README.md`/`STATUS` section at the bottom of this file. **Do not commit unless the user asks.**
> Never log or print API keys. Organizer-only data must never be used.

## 0. Hard rules (from AGENTS.md / user)
- Output: `output.csv` at repo root: `case_id,deletion_status,steps_json`, 518 rows sorted by `case_id`.
- Only `dataset/` participant files may drive predictions. No hardcoded labels / case IDs / case-family shortcuts.
- Append a turn entry to `log.txt` after every user turn (format in AGENTS.md §5.2, with `tool=` and `model=`).
- Deliverables in `code/`: runnable solution, `README.md`, `code/evaluation/evaluation_report.md`, `code/evaluation/usage_report.md` (written as Markdown, not csv/json).
- No secrets in repo. Keys come from env / uncommitted `.env`.

## 1. What the problem really is (verified by analysis)
- 508/518 eval requests are generic deletion templates in 6 languages (en, pt, es, fr, ko, ja). 10 are plainly non-deletion
  (phone update, export, login help, name fix, marketing-only, invoice copy, email change, "what data do you hold", …);
  each also has a `CLASSIFY_REQUEST … non-deletion` event in `system_activity.csv`. Non-deletion → `NOT_APPLICABLE`, `[]`.
- Identity: request email → exactly one user via current email or `user_audit_log.csv` history (chains exist, case-insensitive).
  `email_hash` = SHA-256(email) (verified 850/850). Old hashes in the audit log also link records.
- Evidence linking:
  - Logs: identity key on `*_started` line, resource/state on `*_completed` line, joined by `trace_id` (7 log dialects).
  - Snapshots/exports carry `customer_reference`, emails, hashes. Anonymized records carry nothing.
  - Screenshots/PDFs ↔ `LINK_RESOURCE_IDENTITY` catalog events in the activity log.
  - SQL snapshots: compare primary vs replica tables (replication drift: gone in primary, alive in replica = remaining record).
- Time rules: use only observations whose record time ≤ `audit_at`; cite only files whose `captured_at` ≤ `audit_at`.
  Traps: a bundle exported later contains older inner snapshots (stale state); logs exported later contain earlier lines needed for linking.
- Recreation paths: `SYNC_RECORD integration→search "Active connector repopulated…"`, `RESTORE_BACKUP`,
  `CHECK_DATA_FLOW … remains enabled`, `CHECK_RESTORE_ACCESS … can still be restored`.
- Decoys: look-alike emails (`g.silva76.jr@`), look-alike names, 300-line unrelated log.
- **Hardest part:** ~54% of eval cases have no `account_*` resource linked by identity anywhere. It must be found from
  `deletion_worker` activity: time window `reported_at-3h .. +15m`, result matches claimed status
  (COMPLETE↔SUCCESS, PARTIALLY_COMPLETE↔PARTIAL, NOT_STARTED↔FAILED), exclude accounts tied to other users,
  prefer accounts co-occurring in the same evidence files as the user's other records, workflow-run timing alignment
  (activities of one run sit at consistent second-offsets from that run's account delete), then global propagation
  (one account → one case). Some golden resources are not discoverable from participant data (irreducible ceiling; measure & report it).
- Format facts confirmed on samples: step order = phase, then operation table order, then system_id, then resource_id.
  COMPLETE = verification steps only, each citing evidence. INCOMPLETE = findings (cite evidence) + remediation (empty evidence)
  + verification (empty evidence) covering every relevant resource incl. account (VERIFY_RECORD_ABSENT) and retained audit record
  (VERIFY_RECORD_PRESENT).

## 2. Policy (deletion_rules.csv) → treatment
| Category | Violation when… | Finding | Remediation | Verify |
|---|---|---|---|---|
| account/search/export/cache/marketing/attachment | record present | REPORT_REMAINING_RECORD | DELETE_RECORD | VERIFY_RECORD_ABSENT |
| analytics profile / telemetry | still has identifiers | REPORT_EXPOSED_PII | ANONYMIZE_RECORD | VERIFY_RECORD_ANONYMIZED |
| support message (shared context) | has identifiers | REPORT_EXPOSED_PII | REDACT_RECORD | VERIFY_RECORD_REDACTED |
| account tombstone | has name/email/phone/hash | REPORT_EXPOSED_PII | REDACT_RECORD | VERIFY_RECORD_REDACTED |
| data flow | enabled | REPORT_ACTIVE_DATA_FLOW | DISABLE_DATA_FLOW | VERIFY_DATA_FLOW_DISABLED |
| backup | restore allowed | REPORT_RESTORE_RISK | BLOCK_RESTORE | VERIFY_RESTORE_BLOCKED |
| security audit / legal hold | never a violation | — | — | VERIFY_RECORD_PRESENT |

## 3. Architecture
```
deletion_requests.csv
 → 1 Intent gate (rules + optional LLM cross-check) → NOT_APPLICABLE / continue
 → 2 Identity resolver
 → 3 Evidence store (all files → normalized observations)
 → 4 Resource linker (direct + activity + global propagation)
 → 5 State reconstructor (latest ≤ audit_at, replica drift, citation)
 → 6 Policy engine → 7 Plan compiler → 8 Validator/writer → output.csv
 LLM roles (minimal usage, cached, multi-provider fallback): intent cross-check on unusual texts,
 screenshot extraction (vision), investigator for ambiguous cases only.
```
Design principles: deterministic code decides states/policy; LLM only reads unstructured things or breaks ties among
evidence-backed candidates and can never override proven evidence. Judges (last edition: code 30% arch / prompt+tool craft /
robustness / rigor; interview 30%; output 30%; transcript 10%) penalise "hardcoded workflow with LLM calls" claims that the code
doesn't implement and reward measured trade-offs → ablations (offline vs hybrid), honest ceiling analysis, tool-calling loop on flagged cases.

## 4. LLM orchestration (user decision)
- Free Groq keys (5, rotated on 429/exhaustion) are the baseline. `.env` also supports Gemini, OpenAI(GPT), Claude keys.
- Any subset of providers/keys may be present. Router tries providers in configured priority order (best→lowest), rotating
  keys inside a provider, with per-key cooldown on rate limit, then falls through to next provider; if none work the
  pipeline degrades to fully deterministic ("offline") mode with identical output contract.
- Usage kept minimal: disk cache keyed by (task, prompt hash) — repeated runs cost 0 tokens; LLM only on flagged inputs;
  usage ledger records every call → `code/evaluation/usage_report.md`.
- Groq models (docs, 2026-10): production `openai/gpt-oss-120b` (best text), `openai/gpt-oss-20b`, `llama-3.3-70b-versatile`,
  `llama-3.1-8b-instant`; vision availability must be probed at runtime (`GROQ_VISION_MODEL`, default
  `meta-llama/llama-4-scout-17b-16e-instruct`). If no vision provider works, screenshots fall back to the paired
  `LINK_RESOURCE_IDENTITY` catalog events (deterministic).

## 5. Evaluation plan
Scorer vs `dataset/sample_output.csv`: status accuracy, step P/R/F1, per-field accuracy, exact sequence. ≥3 (target 6) custom
cases written inside the report. Ceiling analysis. Ablations. Failure log with before/after. Usage report from the real ledger.

## 6. Prototype result (analysis scripts, not in repo)
31/32 status, step precision 0.957 / recall 0.933 / full-field recall 0.834 on the 32 samples, before PDF/image layer & refinements.

## 7. Risks
Overfitting 32 samples (rules must be evidence-semantics based); timing-signature linking is a tie-breaker only and ablated;
row sort order assumed numeric by case number (`case_33…case_550`) — verify vs sample_output order; resource-id sort inside a step group assumed lexicographic.

---
## STATUS (update this as work proceeds)
Last updated 2026-10-25. Nothing committed (user commits manually).
- [x] Research + plan saved (this file)
- [x] Evidence parsers (logs x7 dialects, JSON, SQL replicas, handover txt, PDFs, catalog events for screenshots)
- [x] Identity directory, linker (direct + activity + learned run alignment + global propagation), state, policy, plan, validator
- [x] Multi-provider LLM router (anthropic > openai > gemini > groq, key rotation, cache, ledger); intent cross-check; vision cross-check
- [x] `output.csv` generated: 518 rows (offline and Groq-hybrid outputs are byte-identical), 0 validator flags
- [x] Sample score: status 32/32, step precision 1.00, recall 0.969, exact sequence 27/32 (rest unreachable from participant data)
- [x] evaluation_report.md / usage_report.md generated by `code/evaluation/reports.py`; 7 custom cases in `code/evaluation/custom_cases/`
- [ ] Possible next steps: LLM adjudication for the ~17 tie-break links (only if it beats the deterministic tie-break on samples),
      analyse eval-set cases with no audit step (92), packaging `code.zip`, README root pointer, final interview prep notes.
- Free Groq models (2026-10-25 key listing): openai/gpt-oss-120b, openai/gpt-oss-20b, qwen/qwen3.8-27b (vision works), allam-2-7b. llama-3.x gone.
- Security note: never print router state; an earlier debug print exposed Groq keys in a session transcript -> rotate them before sharing traces.

### STATUS addendum - second pass (2026-10-25, Claude Sonnet 5.5)
Followed `next_phase.md`; full resolution table in `limitations.md`. Net effect on the answer: **one** case changed (case_34, found by the ghost sweep);
every other change is structure, guards, measurement and honesty about limits. Added: declarative policy (`policy.py`, `taxonomy.py`), generic multilingual
intent with batched LLM classification, two-tier time model, lineage, activity checks, catalog corroboration, ghost sweep + redaction leak check, trace/review
report, advisory investigator, hardened router, 8 end-to-end custom datasets, ablation + label-free linker recovery + held-out folds, experiments log, packaging.
- [x] `python code/tools/gate.py` passes (samples 32/32, precision 1.000, recall 0.969, exact 27/32; 518 rows, 0 flags; 17 tie-broken links, all flagged)
- [ ] Rotate the Groq keys printed in an earlier session before sharing any trace.
- [ ] Not built (see limitations.md): evidence-strength ranking, per-row vision, learned windows, Hungarian assignment, PDF reference extraction, staleness guard.
