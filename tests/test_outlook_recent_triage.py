import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BROWSER = ROOT / "browser"
sys.path.insert(0, str(BROWSER))

from outlook_recent_triage import merge_visible_batch  # noqa: E402


def row(key: str, subject: str) -> dict:
    return {"cursor_key": key, "subject": subject}


class MergeVisibleBatchTests(unittest.TestCase):
    def test_leading_stop_keys_do_not_hide_new_rows(self) -> None:
        collected: list[dict] = []
        seen: set[str] = set()
        batch = [
            row("old-1", "Pinned old 1"),
            row("old-2", "Pinned old 2"),
            row("new-1", "Fresh mail"),
            row("new-2", "Another fresh mail"),
        ]

        stop_hit, limit_hit = merge_visible_batch(
            collected,
            seen,
            batch,
            limit=10,
            stop_keys={"old-1", "old-2"},
        )

        self.assertFalse(stop_hit)
        self.assertFalse(limit_hit)
        self.assertEqual([entry["cursor_key"] for entry in collected], ["new-1", "new-2"])

    def test_stop_key_after_new_rows_halts_scan(self) -> None:
        collected: list[dict] = []
        seen: set[str] = set()
        batch = [
            row("old-1", "Pinned old 1"),
            row("new-1", "Fresh mail"),
            row("new-2", "Another fresh mail"),
            row("old-2", "Older already-seen row"),
            row("new-3", "Should not be reached"),
        ]

        stop_hit, limit_hit = merge_visible_batch(
            collected,
            seen,
            batch,
            limit=10,
            stop_keys={"old-1", "old-2"},
        )

        self.assertTrue(stop_hit)
        self.assertFalse(limit_hit)
        self.assertEqual([entry["cursor_key"] for entry in collected], ["new-1", "new-2"])


if __name__ == "__main__":
    unittest.main()
