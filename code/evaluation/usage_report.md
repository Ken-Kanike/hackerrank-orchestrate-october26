# Token usage and cost report

Scope: **the final full-dataset run** that produced `output.csv` - run `20261025T070741Z` (hybrid mode, providers ['groq'], finished 2026-10-25T07:07:47Z,
518 cases, status {'INCOMPLETE': 356, 'COMPLETE': 152, 'NOT_APPLICABLE': 10}, validator flags 0). Source: the router ledger (`code/.cache/usage.jsonl`, filtered by `run_id`) and
`code/runs/20261025T070741Z/run_meta.json`. Development and test calls from earlier runs are excluded.

Two views, because responses are cached on disk by prompt hash (a re-run costs 0 fresh tokens):
* **Fresh** = tokens actually sent/received during this run.
* **Cache-attributed** = tokens the cached answers originally cost; this is what producing this output from scratch needs.

| Provider | Model | Fresh calls | Fresh input tok | Fresh output tok | Cache-attributed calls | Cache-attributed in/out tok | Est. cost USD (fresh) | Est. cost USD (if uncached) |
|---|---|---|---|---|---|---|---|---|
| groq | openai/gpt-oss-120b | 0 | 0 | 0 | 32 | 31514 / 13197 | free tier ($0 billed) | 0.0126 |
| groq | openai/gpt-oss-20b | 0 | 0 | 0 | 1 | 1524 / 682 | free tier ($0 billed) | 0.0000 |
| groq | qwen/qwen3.8-27b | 0 | 0 | 0 | 11 | 21681 / 1245 | free tier ($0 billed) | 0.0000 |
| **Total** | | **0** | **0** | **0** | **44** | **54719 / 15124** | | **0.0126** |

* Cases answered: 518. Fresh model calls this run: 0; cache hits: 44.
* Tokens needed to produce this output.csv from scratch (fresh + cache-attributed): 69843; average per request: 134.8.
* Fresh tokens spent in this run: 0; average per request: 0.0.
* Estimated cost from scratch: $0.0126 total, $0.000024 per request, at list prices from `auditor/llm/router.py` (`PRICES`).
  Groq is used on its free tier, so the billed amount is $0; models without an entry in `PRICES` are priced at 0 and listed as such, not guessed.
* Where the model is used: intent classification of the distinct request texts in batches of 25 (rules are the guardrail and can only be
  overridden in the narrow cases documented in `auditor/intent.py`), screenshot reading (cached by image hash), and the advisory investigator on ambiguous cases.
  Evidence reconstruction, identity resolution, linking, policy and plan compilation are deterministic code.
