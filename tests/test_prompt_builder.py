from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.models import JobSpec, PolicySpec, StepSpec
from orchestrator.policy import ExecutionPolicy
from workers.base import BaseWorker, StepContext


def _test_policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        allowed_binaries={"echo"},
        sandbox=False,
        sandbox_wrapper=None,
        sandbox_wrapper_args=[],
        network_policy="deny",
    )


def _make_ctx(
    *,
    job_dir: Path,
    step: StepSpec,
    max_files: int = 10,
    max_file_chars: int = 12000,
    max_total_chars: int = 40000,
) -> StepContext:
    job = JobSpec(
        job_id="job-test-0100",
        goal="prompt-builder test",
        workdir=str(job_dir),
        steps=[step],
        policy=PolicySpec(),
    )
    step_dir = job_dir / "steps" / step.step_id
    return StepContext(
        job=job,
        step=step,
        job_dir=job_dir,
        step_dir=step_dir,
        enable_real_cli=False,
        policy=_test_policy(),
        env_allowlist=set(),
        sensitive_env_vars=set(),
        sandbox_clear_env=False,
        max_input_artifacts_files=max_files,
        max_input_artifact_chars=max_file_chars,
        max_input_artifacts_chars=max_total_chars,
    )


class PromptBuilderTests(unittest.TestCase):
    def test_prompt_builder_uses_standard_markers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            job_dir = Path(td)
            (job_dir / "steps" / "01_plan").mkdir(parents=True, exist_ok=True)
            (job_dir / "steps" / "01_plan" / "report.md").write_text("plan ok", encoding="utf-8")

            step = StepSpec(
                step_id="02_impl",
                agent="codex",
                role="implementer",
                prompt="implement",
                input_artifacts=["steps/01_plan/report.md"],
            )
            ctx = _make_ctx(job_dir=job_dir, step=step)

            built = BaseWorker().build_full_prompt(ctx)
            self.assertIn("## Input artifacts", built)
            self.assertIn("=== BEGIN ARTIFACT: steps/01_plan/report.md ===", built)
            self.assertIn("plan ok", built)
            self.assertIn("=== END ARTIFACT ===", built)

    def test_prompt_builder_enforces_limits_and_path_safety(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            job_dir = Path(td)
            (job_dir / "a.txt").write_text("abcdefghij", encoding="utf-8")
            (job_dir / "b.txt").write_text("1234567890", encoding="utf-8")

            step = StepSpec(
                step_id="03_review",
                agent="claude",
                role="reviewer",
                prompt="review",
                input_artifacts=["a.txt", "b.txt", "../escape.txt", "missing.txt"],
            )
            ctx = _make_ctx(
                job_dir=job_dir,
                step=step,
                max_files=2,
                max_file_chars=8,
                max_total_chars=12,
            )

            built = BaseWorker().build_full_prompt(ctx)
            self.assertIn("=== BEGIN ARTIFACT: a.txt ===", built)
            self.assertIn("=== BEGIN ARTIFACT: b.txt ===", built)
            self.assertIn("[truncated:file_limit]", built)
            self.assertIn("[truncated:total_limit]", built)
            self.assertIn("[artifacts_truncated_or_limited]", built)
            self.assertNotIn("escape.txt", built)
            self.assertNotIn("missing.txt", built)

    def test_prompt_builder_marks_invalid_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            job_dir = Path(td)
            step = StepSpec(
                step_id="04_review",
                agent="claude",
                role="reviewer",
                prompt="review",
                input_artifacts=["../outside.txt"],
            )
            ctx = _make_ctx(job_dir=job_dir, step=step)
            built = BaseWorker().build_full_prompt(ctx)
            self.assertIn("[invalid_path]", built)


if __name__ == "__main__":
    unittest.main()
