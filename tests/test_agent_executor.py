from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.models import JobSpec, PolicySpec, StepSpec
from orchestrator.policy import ExecutionPolicy
from orchestrator.subprocess_utils import CommandResult
from workers.codex_worker import CodexWorker
from workers.agent_executor import AgentExecutor
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
    @staticmethod
    def _init_git_repo_with_commit(repo: Path) -> None:
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=repo, check=False, capture_output=True, text=True)
        (repo / "tracked.txt").write_text("before\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test User",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-m",
                "init",
            ],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )

    @staticmethod
    def _dummy_ctx(*, root: Path, repo: Path) -> StepContext:
        step = StepSpec(step_id="step01", agent="dummy", role="implementer", prompt="implement")
        job = JobSpec(
            job_id="job-test-ae-0003",
            goal="test",
            workdir=str(repo),
            steps=[step],
            policy=PolicySpec(),
        )
        return StepContext(
            job=job,
            step=step,
            job_dir=root / "job",
            step_dir=root / "job" / "steps" / step.step_id,
            enable_real_cli=True,
            policy=ExecutionPolicy(
                allowed_binaries={"dummy", "git"},
                sandbox=False,
                sandbox_wrapper=None,
                sandbox_wrapper_args=[],
                network_policy="deny",
            ),
            env_allowlist=set(),
            sensitive_env_vars=set(),
            sandbox_clear_env=False,
            max_input_artifacts_files=10,
            max_input_artifact_chars=12000,
            max_input_artifacts_chars=40000,
        )

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

    async def test_real_cli_marks_change_status_as_changed(self) -> None:
        class DummyWorker(AgentExecutor):
            AGENT_NAME = "dummy"

            def build_cmd(self, ctx: StepContext, full_prompt: str) -> list[str]:
                return ["dummy", "run", full_prompt]

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            self._init_git_repo_with_commit(repo)
            ctx = self._dummy_ctx(root=root, repo=repo)

            async def _fake_run_command(*args, **kwargs) -> CommandResult:
                (repo / "tracked.txt").write_text("after\n", encoding="utf-8")
                return CommandResult(exit_code=0, stdout="ok", stderr="", duration_ms=10)

            with patch("workers.agent_executor.run_command", new=_fake_run_command):
                result = await DummyWorker().run(ctx)

            self.assertEqual(result.status, "success")
            self.assertEqual(result.change_status, "changed")
            self.assertIn("(changed)", result.summary)

    async def test_real_cli_marks_change_status_as_no_changes(self) -> None:
        class DummyWorker(AgentExecutor):
            AGENT_NAME = "dummy"

            def build_cmd(self, ctx: StepContext, full_prompt: str) -> list[str]:
                return ["dummy", "run", full_prompt]

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            self._init_git_repo_with_commit(repo)
            ctx = self._dummy_ctx(root=root, repo=repo)

            async def _fake_run_command(*args, **kwargs) -> CommandResult:
                return CommandResult(exit_code=0, stdout="ok", stderr="", duration_ms=10)

            with patch("workers.agent_executor.run_command", new=_fake_run_command):
                result = await DummyWorker().run(ctx)

            self.assertEqual(result.status, "success")
            self.assertEqual(result.change_status, "no_changes")
            self.assertIn("(no_changes)", result.summary)


if __name__ == "__main__":
    unittest.main()
