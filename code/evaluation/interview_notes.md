# Interview notes

## 60-second pitch
The deletion workflow's own status is a claim. This system rebuilds the state of every record at `audit_at` from evidence, applies `deletion_rules.csv` as data, and writes
the plan. The core is deterministic and traceable; an LLM reads text (intent) and pixels (screenshots), and a bounded tool-calling investigator explains the few ambiguous links.
Every decision can be explained from `code/runs/<run_id>/trace.jsonl`.

## Walk one case (case_34, `code/evaluation/example_trace.md`)
1. Intent: erasure cue, no negation -> DELETE (rules are the guardrail; the LLM may only confirm a weak "not deletion" or rescue a cue-less paraphrase at >= 0.85 confidence).
2. Identity: request email -> user_11 via current + historical emails, hashes, phones.
3. Evidence -> observations (logs, JSON, SQL replicas, PDFs, screenshots via catalog events). Links: identity first; the activity stream (time window + result matches the
   claimed status + elimination + workflow-run reconstruction) only for accounts no identifier reaches.
4. State at audit_at: type discovery may use any record stamped <= audit_at; state and citation only from files captured <= audit_at (a later export can't change the answer).
5. Policy: kind -> data category -> rule -> condition (retention date vs audit_at, sharing) -> finding / remediation / verification operations.
6. Validator, then ghost sweep: grep all evidence for the subject's identifiers. It found the one real miss in the data (this case, pre-request evidence discarded by a cut-off meant for users with an earlier request).

## Why deterministic at the core
Auditable and reproducible; the contract (ordering, citation rules) is exact; LLMs are slow, rate-limited and can be injected through request text or screenshots. The LLM is therefore
an add-on with guardrails, and the whole pipeline works with no keys (`--mode offline`, identical output here).

## Where the LLM decides, and its guardrails
* Intent: batched (25 texts/call), schema-validated, one re-ask. Never overrides a strong rule verdict; disagreements are flagged.
* Screenshots: read by hash-cached vision; used only to set a state and to corroborate/contradict a catalog link; ids are validated against known families.
* Investigator: tools are read-only views; `choose` must be an engine candidate; advisory by default. Measured: it agrees with the engine on every case, so it explains rather than decides (say this openly).

## Measured claims to quote (all in `evaluation_report.md`)
* Samples: status 32/32, step precision 1.000, recall 0.969, field accuracy 100% on aligned steps, position 96.8%, exact sequence 27/32; 3 gold steps are unreachable by construction.
* Ablations: alignment off -> recall .943 and 154 outputs change; strict time / lineage / activity checks change 0 outputs here (guards for variants, each proven by an end-to-end case).
* Label-free linker test: hide a proven account, re-derive it from activity alone -> ~99% recovery.
* 8 hand-derived end-to-end datasets pass and each fails when its feature is switched off.

## Known limits (say them before they are found)
* Workflow-run alignment exploits a timing regularity of this dataset; real systems would carry run ids. It runs after evidence-based signals and is ablated.
* 17 account links have several equally plausible candidates and no sibling evidence; deterministic but a guess, flagged.
* 12 catalog-only cases rely on a per-family default state unless a vision key reads the screenshot; flagged `state_unverified`. Case_63's screenshot shows an unknown identity (`catalog_unverified_identity`).
* Time windows were set from the samples; the intent lexicon was written while seeing the evaluation texts (independent probes exist).
* Sample ceiling: ids like `account_004` appear nowhere; id-pattern inference is forbidden.

## With more time
Learned windows from evidence-confirmed pairs, per-row vision extraction with an OCR fallback, evidence-strength ranking, staleness guard, run ids on every event (the real fix for linking),
human-review queue for the flagged cases, policy versioning at `audit_at`.
