from __future__ import annotations

import unittest

from orchestrator.models import StepSpec
try:
    from orchestrator.runner import _resolve_on_failure
except ModuleNotFoundError:  # pragma: no cover - optional in bare test env
    _resolve_on_failure = None  # type: ignore[assignment]


@unittest.skipIf(_resolve_on_failure is None, "runner dependencies are not installed")
class RunnerOnFailureTests(unittest.TestCase):
    def test_resolve_on_failure_ask_human(self) -> None:
        steps = [
            StepSpec(step_id="01_plan", agent="opencode", role="planner", prompt="plan"),
            StepSpec(step_id="02_impl", agent="codex", role="implementer", prompt="impl"),
        ]
        self.assertEqual(_resolve_on_failure("ask_human", steps, 0), "ask_human")

    def test_resolve_on_failure_goto(self) -> None:
        steps = [
            StepSpec(step_id="01_plan", agent="opencode", role="planner", prompt="plan"),
            StepSpec(step_id="02_impl", agent="codex", role="implementer", prompt="impl"),
        ]
        self.assertEqual(_resolve_on_failure("goto:02_impl", steps, 0), 1)


if __name__ == "__main__":
    unittest.main()
