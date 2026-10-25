"""Router behaviour without any network: error classes, validation retry, cache semantics, budgets, usage accounting."""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auditor.llm import router as R  # noqa: E402


def make_router(**env):
    tmp = Path(tempfile.mkdtemp())
    R.CACHE_DIR = tmp
    for k in ("GROQ_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        os.environ.pop(k, None)
    os.environ["GROQ_API_KEY"] = "gsk_FAKE_for_tests_only"
    os.environ["LLM_PROVIDER_ORDER"] = "groq"
    for k, v in env.items():
        os.environ[k] = v
    rt = R.Router(enabled=True)
    rt.available_models["groq"] = set()           # skip /models discovery (no network)
    return rt, tmp


def http_error(code, body):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body.encode()))


class RouterTests(unittest.TestCase):
    def tearDown(self):
        for k in ("LLM_MAX_CALLS", "LLM_REFRESH", "LLM_PROVIDER_ORDER", "GROQ_API_KEY"):
            os.environ.pop(k, None)

    def test_validator_reasks_once_and_bad_answers_are_not_cached(self):
        rt, _ = make_router()
        answers = iter(['{"a": 1}', '{"items": []}'])
        rt._call = lambda *a, **k: (next(answers), 10, 5)
        out, meta = rt.complete_json("t", "sys", "u", validator=lambda d: "items" in d)
        self.assertEqual(out, {"items": []})
        again, meta2 = rt.complete_json("t", "sys", "u", validator=lambda d: "items" in d)
        self.assertTrue(meta2["cached"])

    def test_request_specific_400_does_not_kill_the_model(self):
        rt, _ = make_router()
        def boom(*a, **k):
            raise http_error(400, '{"error":"image too large"}')
        rt._call = boom
        self.assertIsNone(rt.complete_json("t", "s", "u")[0])
        self.assertFalse(rt.dead)

    def test_model_error_marks_model_dead(self):
        rt, _ = make_router()
        def boom(*a, **k):
            raise http_error(400, '{"error":"The model `x` does not exist"}')
        rt._call = boom
        rt.complete_json("t", "s", "u")
        self.assertTrue(rt.dead)

    def test_cache_key_ignores_provider_and_refresh_bypasses_cache(self):
        rt, _ = make_router()
        calls = []
        rt._call = lambda *a, **k: (calls.append(1) or '{"v": 1}', 3, 2)
        rt.complete_json("t", "s", "u"); rt.complete_json("t", "s", "u")
        self.assertEqual(len(calls), 1)
        rt.refresh = True
        rt.complete_json("t", "s", "u")
        self.assertEqual(len(calls), 2)

    def test_call_budget_stops_the_run(self):
        rt, _ = make_router(LLM_MAX_CALLS="1")
        rt._call = lambda *a, **k: ('{"v": 1}', 1, 1)
        rt.complete_json("t", "s", "u1")
        out, meta = rt.complete_json("t", "s", "u2")
        self.assertIsNone(out); self.assertTrue(meta.get("budget_exhausted"))

    def test_usage_summary_separates_fresh_and_cached_per_run(self):
        rt, tmp = make_router()
        rt._call = lambda *a, **k: ('{"v": 1}', 100, 20)
        rt.complete_json("t", "s", "u"); rt.complete_json("t", "s", "u")          # one fresh, one cache hit
        agg = R.usage_summary(tmp / "usage.jsonl", rt.run_id)
        row = next(iter(agg.values()))
        self.assertEqual((row["calls"], row["in"], row["cached_calls"], row["cached_in"]), (1, 100, 1, 100))
        self.assertEqual(R.usage_summary(tmp / "usage.jsonl", "other-run"), {})

    def test_anthropic_request_asks_for_low_effort(self):
        rt, _ = make_router()
        sent = {}
        rt._post = lambda url, body, headers: (sent.update(body) or {"content": [{"text": "{}"}], "usage": {}, "stop_reason": "end_turn"})
        rt._call("anthropic", "claude-opus-5-5", "k", "s", "u", [], 120)
        self.assertEqual(sent["output_config"], {"effort": "low"}); self.assertGreaterEqual(sent["max_tokens"], 2000)
        self.assertNotIn("temperature", sent)

    def test_refusal_returns_empty_text(self):
        rt, _ = make_router()
        rt._post = lambda url, body, headers: {"content": [{"text": "partial"}], "usage": {"input_tokens": 4, "output_tokens": 1}, "stop_reason": "refusal"}
        self.assertEqual(rt._call("anthropic", "claude-opus-5-5", "k", "s", "u", [], 120)[0], "")


if __name__ == "__main__":
    unittest.main()
