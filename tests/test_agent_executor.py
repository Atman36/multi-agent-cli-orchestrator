from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from orchestrator.models import JobSpec, PolicySpec, StepSpec
from orchestrator.policy import ExecutionPolicy
from workers.codex_worker import CodexWorker
from workers.base import StepContext


def _policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        allowed_binaries={"codex", "git"},
        sandbox=False,
        sandbox_wrapper=None,
        sandbox_wrapper_args=[],
        network_policy="deny",
    )


class AgentExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_git_workdir_returns_needs_human(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            step = StepSpec(step_id="step01", agent="codex", role="implementer", prompt="implement")
            job = JobSpec(
                job_id="job-test-ae-0001",
                goal="test",
                workdir=str(root),
                steps=[step],
                policy=PolicySpec(),
            )
            ctx = StepContext(
                job=job,
                step=step,
                job_dir=root / "job",
                step_dir=root / "job" / "steps" / step.step_id,
                enable_real_cli=True,
                policy=_policy(),
                env_allowlist=set(),
                sensitive_env_vars=set(),
                sandbox_clear_env=False,
                max_input_artifacts_files=10,
                max_input_artifact_chars=12000,
                max_input_artifacts_chars=40000,
                non_git_workdir_status="needs_human",
            )

            result = await CodexWorker().run(ctx)
            self.assertEqual(result.status, "needs_human")
            self.assertIsNotNone(result.error)
            assert result.error is not None
            self.assertEqual(result.error.code, "non_git_workdir")

    async def test_missing_patch_fails_before_cli_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init"], cwd=repo, check=False, capture_output=True, text=True)

            step = StepSpec(
                step_id="step01",
                agent="codex",
                role="implementer",
                prompt="implement",
                apply_patches_from=["steps/01_plan/patch.diff"],
            )
            job_dir = root / "job"
            job = JobSpec(
                job_id="job-test-ae-0002",
                goal="test",
                workdir=str(repo),
                steps=[step],
                policy=PolicySpec(),
            )
            ctx = StepContext(
                job=job,
                step=step,
                job_dir=job_dir,
                step_dir=job_dir / "steps" / step.step_id,
                enable_real_cli=True,
                policy=_policy(),
                env_allowlist=set(),
                sensitive_env_vars=set(),
                sandbox_clear_env=False,
                max_input_artifacts_files=10,
                max_input_artifact_chars=12000,
                max_input_artifacts_chars=40000,
            )

            result = await CodexWorker().run(ctx)
            self.assertEqual(result.status, "failed")
            self.assertIsNotNone(result.error)
            assert result.error is not None
            self.assertEqual(result.error.code, "missing_patch")


if __name__ == "__main__":
    unittest.main()
