# Ghost Data Still Exists - deletion audit agent

Reads `dataset/` only, writes `output.csv` (repo root): `case_id,deletion_status,steps_json`, 518 rows.

## Setup and run
```bash
python -m venv .venv && .venv/Scripts/activate      # (Windows)  or: source .venv/bin/activate
pip install -r code/requirements.txt                # pypdf only; everything else is the standard library
cp .env.example .env                                # optional: LLM keys (Groq / Gemini / OpenAI / Anthropic). Works with none.

python code/main.py                                 # hybrid: uses any configured LLM, else falls back to the deterministic path
python code/main.py --mode offline                  # never calls an LLM; same output contract
python code/main.py --refresh-llm                   # ignore cached LLM answers
python code/main.py --data some_dir                 # run on another dataset directory with the same layout
```
Python 3.10+. Keys come from the environment or the uncommitted `.env`; nothing secret is stored in the repo, the router keeps only key fingerprints.
Each run writes `code/runs/<run_id>/` (gitignored): `trace.jsonl` (per case: resolved user, each resource with its link reason, deciding evidence,
policy rule, flags), `review.md` (cases and catalog links a human should look at) and `run_meta.json`.

## Test, evaluate, report
```bash
python code/tools/gate.py                            # regression gate: samples, unit tests, end-to-end custom datasets, 518-row run, diff vs accepted output
python -m unittest discover -s code/tests -t code    # unit tests (policy, intent probes, router, investigator, corroboration, validator)
python code/evaluation/main.py -v                    # 32 public samples: status, step P/R/F1, per-field, position, Kendall tau, LCS
python code/evaluation/main.py --folds 2 --repeats 5 # held-out estimate
python code/evaluation/main.py --record "what changed"   # append metrics to evaluation/experiments.jsonl
python code/evaluation/custom_cases/run_custom_cases.py  # 8 end-to-end custom datasets with hand-written expected outputs
python code/evaluation/ablation.py                   # one-flag-off ablations
python code/evaluation/link_recovery.py              # label-free test of the activity-based account linker
python code/evaluation/reports.py                    # regenerates evaluation_report.md and usage_report.md (several minutes)
python code/tools/diff_outputs.py A.csv B.csv        # per-case diff of two outputs
python code/package.py                               # builds code.zip (no dataset, caches, runs, .env)
```

## Architecture - deterministic core, LLM where text/pixels need reading, every decision traceable
```
deletion_requests.csv
 -> intent.py          rights lexicon (12 languages: erasure / access / portability / rectification / marketing / ...) + negation and scope limits,
                       instruction-like sentences stripped; LLM classifies distinct texts in batches; rules are the guardrail (offline = rules only)
 -> engine.Directory   current + historical emails / hashes / phones from user_identities + user_audit_log (case-insensitive, digits-only phones)
 -> evidence.py        every evidence file -> normalized observations (7 log dialects joined by trace_id, JSON bundles, SQLite snapshots incl. replicas,
                       handover txt, PDFs, screenshots via catalog events + vision, activity-stream state checks as weak observations)
 -> corroborate.py     a catalog link is checked against the identifiers read from its artifact: contradicted -> dropped, unknown -> kept and flagged
 -> engine.link_all    identity links (cut-off for earlier requests only for users with several requests), then deletion-worker activity links:
                       time window + result matches claimed status + elimination + workflow-run reconstruction (see "Honest notes") + one-resource-one-case
 -> lineage.py         resources recreated by connector sync / backup restore at or before audit_at join the case (cited by activity_id)
 -> engine.state_of    two-tier time model: type discovery from any record stamped <= audit_at; state and citation only from files captured <= audit_at
 -> policy.py          deletion_rules.csv is DATA: category (taxonomy.py) -> rule -> condition predicates (retention dates, sharing) -> action -> operations
 -> validate.py        schema, order, citation (<= audit_at, not contradicting the step), activity_id citations; failures are reported, never silent
 -> ghost.py           defence in depth: grep all evidence for the subject's identifiers; unexplained resources and un-redacted CLEAN records become flags
 -> llm/investigator.py advisory tool-calling loop on ambiguous links (read-only tools, evidence-backed choices only; never changes output unless enabled)
 -> pipeline.py        orchestration, trace + review report
```
Configuration flags (`auditor/config.py`, overridable by env var) exist for every heuristic so ablations are one switch away:
`AUDIT_STRICT_TIME`, `AUDIT_LINEAGE`, `AUDIT_ACTIVITY_CHECKS`, `AUDIT_RUN_ALIGNMENT`, `AUDIT_GHOST_SWEEP`, `AUDIT_PARTITION_MULTI_ONLY`,
`AUDIT_INVESTIGATOR` / `AUDIT_INVESTIGATOR_APPLY`.

## LLM layer (`auditor/llm/`)
`router.py`: provider priority + key rotation, per-error handling (a request-specific 400 no longer disables a model), run budget
(`LLM_MAX_SECONDS`, `LLM_MAX_CALLS`), thread-pool for batch tasks (`LLM_WORKERS`), `/models` discovery, disk cache keyed by (task, prompt, input),
schema-validated answers with one re-ask, ledger lines carrying `run_id`. Anthropic requests use `output_config.effort="low"` (Opus 5.5 cannot
disable thinking and defaults to medium) with room for thinking tokens and treat `stop_reason: refusal` as no answer.
Provider order: `LLM_PROVIDER_ORDER` (default anthropic, openai, gemini, groq); any subset of keys works; none = offline.

## Honest notes (read before the interview)
* **Workflow-run reconstruction.** The ~280 accounts whose identifiers never reach an account record are linked through the deletion-worker
  activity stream. The strongest signal there is a second-offset regularity between a run's account-delete and its sibling actions, *learned* from
  evidence-confirmed links. It is a property of this dataset, not of real systems (which would carry run ids). It runs after evidence-based signals,
  is behind `AUDIT_RUN_ALIGNMENT`, and `evaluation_report.md` shows the ablation and the label-free recovery test.
* **Sample-fitted constants.** Time windows (account -180/+15 min, policy action -60/0 min) and the 1-day slack were set from the samples; they are in
  `engine.py` with comments and not yet learned from data.
* **Intent lexicon.** It was developed while looking at the evaluation texts, so the evaluation NOT_APPLICABLE set is not an independent test; the
  48 probes in `code/tests/test_intent.py` are (written separately, 10 languages).
* **ID-pattern inference is forbidden** (e.g. `user_04 -> account_004`); a few sample steps are therefore unreachable.
* The solution never reads organizer-only files; `dataset/sample_output.csv` is read only by `code/evaluation/`.

## Files
| Path | Role |
|---|---|
| `main.py` | CLI entry point |
| `auditor/config.py` | paths, `.env` loader, tunables |
| `auditor/taxonomy.py`, `auditor/policy.py` | resource families, kind -> data category; declarative policy from `deletion_rules.csv` |
| `auditor/evidence.py`, `auditor/ghost.py`, `auditor/lineage.py`, `auditor/corroborate.py` | observations, grep sweep, recreation graph, catalog checks |
| `auditor/engine.py` | identity, linking, state, plan |
| `auditor/intent.py`, `auditor/vision.py` | LLM-assisted gates |
| `auditor/llm/router.py`, `auditor/llm/investigator.py` | provider router; advisory tool loop |
| `auditor/validate.py`, `auditor/pipeline.py` | contract checks, orchestration, trace |
| `tests/` | unit tests; `tools/` gate, output diff; `evaluation/` scorer, custom datasets, ablations, reports |

## Web UI and docs
See `webui/` (sources, `build.py`, Playwright tests) and `docs/` (generated `index.html` plus architecture, agents, accuracy, UI and policy documentation).
