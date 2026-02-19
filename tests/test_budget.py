from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.budget import BudgetLimitExceeded, BudgetTracker


class BudgetTrackerTests(unittest.TestCase):
    def test_budget_tracker_blocks_when_call_limit_reached(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tracker = BudgetTracker(
                db_path=Path(td) / "state.db",
                max_daily_api_calls=2,
                max_daily_cost_usd=0,
            )

            tracker.check_budget()
            tracker.log_budget("codex", api_calls=1, cost_usd=0.0)
            tracker.check_budget()
            tracker.log_budget("codex", api_calls=1, cost_usd=0.0)

            with self.assertRaises(BudgetLimitExceeded):
                tracker.check_budget()

    def test_budget_tracker_accumulates_cost(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tracker = BudgetTracker(
                db_path=Path(td) / "state.db",
                max_daily_api_calls=0,
                max_daily_cost_usd=0.5,
            )

            tracker.log_budget("opencode", api_calls=1, cost_usd=0.2)
            tracker.check_budget()
            tracker.log_budget("claude", api_calls=1, cost_usd=0.3)

            with self.assertRaises(BudgetLimitExceeded):
                tracker.check_budget()


if __name__ == "__main__":
    unittest.main()
