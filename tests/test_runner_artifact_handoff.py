from __future__ import annotations

import unittest

from orchestrator.models import ArtifactPaths, StepResult, StepSpec, utc_now_iso

try:
    from orchestrator.runner import _latest_successful_step_id, _resolve_effective_step
except ModuleNotFoundError:  # pragma: no cover - optional in bare test env
    _latest_successful_step_id = None  # type: ignore[assignment]
    _resolve_effective_step = None  # type: ignore[assignment]


@unittest.skipIf(_latest_successful_step_id is None or _resolve_effective_step is None, "runner dependencies are not installed")
class RunnerArtifactHandoffTests(unittest.TestCase):
    @staticmethod
    def _step_result(step_id: str, status: str) -> StepResult:
        now = utc_now_iso()
        return StepResult(
            job_id="job-test-handoff-01",
            step_id=step_id,
            agent="codex",
            role="implementer",
            status=status,
            attempts=1,
            started_at=now,
            finished_at=now,
            summary=status,
            artifacts=ArtifactPaths(
                report_md=f"steps/{step_id}/report.md",
                patch_diff=f"steps/{step_id}/patch.diff",
                logs_txt=f"steps/{step_id}/logs.txt",
                result_json=f"steps/{step_id}/result.json",
            ),
        )

    def test_latest_successful_step_id(self) -> None:
        step_results = [
            self._step_result("01_plan", "failed"),
            self._step_result("02_impl", "success"),
            self._step_result("03_review", "failed"),
        ]
        self.assertEqual(_latest_successful_step_id(step_results), "02_impl")

    def test_patch_first_sets_previous_patch_only(self) -> None:
        step = StepSpec(
            step_id="04_fix",
            agent="codex",
            role="implementer",
            prompt="fix",
            input_artifacts=["steps/old/report.md"],
            apply_patches_from=["steps/old/patch.diff"],
        )
        effective = _resolve_effective_step(
            step,
            artifact_handoff="patch_first",
            previous_success_step_id="02_impl",
        )
        self.assertEqual(effective.input_artifacts, ["steps/02_impl/patch.diff"])
        self.assertEqual(effective.apply_patches_from, [])

    def test_workspace_first_drops_manual_artifacts(self) -> None:
        step = StepSpec(
            step_id="05_review",
            agent="claude",
            role="reviewer",
            prompt="review",
            input_artifacts=["steps/02_impl/report.md", "steps/02_impl/patch.diff"],
            apply_patches_from=["steps/01_plan/patch.diff"],
        )
        effective = _resolve_effective_step(
            step,
            artifact_handoff="workspace_first",
            previous_success_step_id="02_impl",
        )
        self.assertEqual(effective.input_artifacts, [])
        self.assertEqual(effective.apply_patches_from, [])

    def test_manual_keeps_input_artifacts(self) -> None:
        step = StepSpec(
            step_id="06_review",
            agent="claude",
            role="reviewer",
            prompt="review",
            input_artifacts=["steps/02_impl/report.md"],
            apply_patches_from=["steps/02_impl/patch.diff"],
        )
        effective = _resolve_effective_step(
            step,
            artifact_handoff="manual",
            previous_success_step_id="02_impl",
        )
        self.assertEqual(effective.input_artifacts, ["steps/02_impl/report.md"])
        self.assertEqual(effective.apply_patches_from, ["steps/02_impl/patch.diff"])


if __name__ == "__main__":
    unittest.main()
