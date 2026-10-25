"""The router must never keep a raw API key in its state (only fingerprints)."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auditor.llm import router as R  # noqa: E402


class RouterSecrets(unittest.TestCase):
    def test_no_raw_key_in_state_after_429(self):
        fake = "gsk_FAKE_TEST_KEY_do_not_use_123456"
        old = os.environ.get("GROQ_API_KEY")
        os.environ["GROQ_API_KEY"] = fake
        try:
            rt = R.Router(enabled=True)
            rt.cache_path = rt.cache_dir / "test_cache_unused.json"
            key = rt._next_key("groq")
            self.assertEqual(key, fake)
            rt.cooldown[R._fp(key)] = 9e9                      # what a 429 does
            self.assertNotIn(fake, str(rt.__dict__))
            self.assertNotIn(fake, repr(rt.cooldown))
        finally:
            if old is None:
                os.environ.pop("GROQ_API_KEY", None)
            else:
                os.environ["GROQ_API_KEY"] = old


if __name__ == "__main__":
    unittest.main()
