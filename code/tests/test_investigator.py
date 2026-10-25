"""Investigator loop: scripted stub router, real engine. Checks tools, guardrails and advisory behaviour."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auditor.config import DATASET  # noqa: E402
from auditor.llm.investigator import Tools, investigate  # noqa: E402
from auditor.llm.router import Router  # noqa: E402
from auditor.pipeline import read_requests, run  # noqa: E402


class Script:
    available = True

    def __init__(self, msgs):
        self.msgs = list(msgs); self.seen = []

    def complete_json(self, task, system, user, **kw):
        self.seen.append(user)
        return (self.msgs.pop(0) if self.msgs else None), {}


class InvestigatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reqs = read_requests("deletion_requests.csv"); samples = read_requests("sample_deletion_requests.csv")
        _, cls.report, cls.eng, _ = run(reqs, reqs + samples, Router(enabled=False), DATASET, use_vision=False, log=lambda *a: None)
        cls.by_id = {c["case_id"]: c for c in reqs + samples}
        cls.cid = sorted(cls.eng.ambiguous)[0]
        cls.cands = cls.eng.account_cands[(cls.cid, "account")]
        cls.current = next(r for r in cls.eng.extra[cls.cid] if r.startswith("account"))

    def test_tool_loop_returns_valid_candidate(self):
        s = Script([{"tool": "list_candidates", "args": {}}, {"tool": "resource_timeline", "args": {"resource_id": self.cands[0]}},
                    {"final": {"choose": self.cands[-1], "reason": "closest to reported_at"}}])
        r = investigate(self.eng, self.by_id[self.cid], self.cands, s, self.current)
        self.assertEqual((r["choose"], r["turns"]), (self.cands[-1], 3))
        self.assertIn("TOOL list_candidates", s.seen[1])

    def test_bare_final_without_wrapper_is_accepted(self):
        s = Script([{"choose": self.cands[0], "reason": "x"}])
        self.assertEqual(investigate(self.eng, self.by_id[self.cid], self.cands, s, self.current)["choose"], self.cands[0])

    def test_transcript_is_seeded_with_engine_facts(self):
        s = Script([{"choose": None, "reason": "no support"}])
        investigate(self.eng, self.by_id[self.cid], self.cands, s, self.current)
        self.assertIn("TOOL list_candidates", s.seen[0]); self.assertIn("TOOL get_case_dossier", s.seen[0])

    def test_choice_outside_candidates_is_rejected(self):
        s = Script([{"final": {"choose": "account_99999999", "reason": "made up"}}])
        self.assertIsNone(investigate(self.eng, self.by_id[self.cid], self.cands, s, self.current))

    def test_turn_limit_and_unknown_tool(self):
        s = Script([{"tool": "rm_rf", "args": {}}] * 10)
        self.assertIsNone(investigate(self.eng, self.by_id[self.cid], self.cands, s, self.current, max_turns=3))
        self.assertIn("unknown tool", s.seen[1])

    def test_tools_are_read_only_views(self):
        t = Tools(self.eng, self.by_id[self.cid], self.cands)
        before = {k: set(v) for k, v in self.eng.extra.items()}
        t.call("list_candidates", {}); t.call("search_evidence", {"identifier": "nobody@example.com"}); t.call("policy_for", {"category": "ANALYTICS_PROFILE"})
        self.assertEqual(before, {k: set(v) for k, v in self.eng.extra.items()})
        self.assertEqual(t.call("policy_for", {"category": "ANALYTICS_PROFILE"})["action"], "ANONYMIZE")


if __name__ == "__main__":
    unittest.main()
