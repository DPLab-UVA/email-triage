import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
sys.path.insert(0, str(SHARED))

import triage_engine  # noqa: E402


class TriageEngineFallbackTests(unittest.TestCase):
    def test_llm_exception_falls_back_without_draft(self) -> None:
        rules = {"priority_threshold": 4}
        examples: list[dict] = []
        message = {
            "from": "Mike Example <mike@example.edu>",
            "subject": "Can we meet on Friday about the prototype?",
            "body": "Can you meet Friday to discuss next steps for the infrastructure work?",
        }

        with patch.object(triage_engine, "llm_judge_message", side_effect=RuntimeError("llm timeout")):
            result = triage_engine.triage_message(message, rules, examples)

        self.assertEqual(result.get("decision_source"), "llm-fallback")
        self.assertEqual(result.get("draft_reply"), "")
        self.assertTrue(result.get("needs_manual_review"))
        self.assertIn("llm fallback: llm timeout", result.get("reasons", []))


if __name__ == "__main__":
    unittest.main()
