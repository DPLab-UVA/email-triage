import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BROWSER = ROOT / "browser"
sys.path.insert(0, str(BROWSER))

from outlook_draft_helper import parse_reading_pane  # noqa: E402


class ParseReadingPaneTests(unittest.TestCase):
    def test_ignores_open_compose_and_later_ui_noise(self) -> None:
        message = {
            "subject": "Intake meeting for Research posting",
            "from": "Haverstrom, Richard Kenneth (rkh6j)",
        }
        pane_text = "\n".join(
            [
                "Intake meeting for Research posting",
                "Summarize",
                "HK",
                "Haverstrom, Richard Kenneth (rkh6j)",
                "Tue 3/3/2026 3:56 PM",
                "Initial email body",
                "WT",
                "You",
                "Tue 3/24/2026 3:29 PM",
                "We interviewed the candidates and want to extend an offer.",
                "HK",
                "Haverstrom, Richard Kenneth (rkh6j)",
                "Tue 3/24/2026 3:37 PM",
                "Please send me the names of all the people you interviewed.",
                "Please collect the required documents first.",
                "From: tianhao@virginia.edu",
                "WT",
                "To:",
                "Haverstrom, Richard Kenneth (rkh6j)",
                "Send",
                "Discard",
                "Draft saved at 3:38 PM",
                "WT",
                "Wang, Tianhao (nkp2mr)",
                "To:",
                "Li, Jingjing (jl9rf)",
                "Tue 3/24/2026 3:46 PM",
                "This is unrelated compose text and should be ignored.",
            ]
        )

        parsed = parse_reading_pane(message, pane_text)

        self.assertEqual(parsed.get("latest_incoming_sender"), "Haverstrom, Richard Kenneth (rkh6j)")
        self.assertEqual(parsed.get("latest_incoming_timestamp"), "Tue 3/24/2026 3:37 PM")
        self.assertIn("Please send me the names", parsed.get("latest_incoming_body", ""))
        self.assertEqual(parsed.get("latest_self_timestamp"), "Tue 3/24/2026 3:29 PM")
        self.assertNotIn("Li, Jingjing", parsed.get("latest_incoming_body", ""))
        self.assertNotIn("Send", parsed.get("pane_lines", []))


if __name__ == "__main__":
    unittest.main()
