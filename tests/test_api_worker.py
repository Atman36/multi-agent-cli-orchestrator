from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from orchestrator.models import JobSpec, PolicySpec, StepSpec
from orchestrator.policy import ExecutionPolicy
from workers.api_worker import APIWorker
from workers.base import StepContext


def _policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        allowed_binaries={"git"},
        sandbox=False,
        sandbox_wrapper=None,
        sandbox_wrapper_args=[],
        network_policy="deny",
    )


class DummyAPIWorker(APIWorker):
    AGENT_NAME = "dummy_api"

    def __init__(self) -> None:
        self.last_prompt: str | None = None
        self.last_context: dict[str, Any] | None = None

    async def call_api(self, prompt: str, context: dict[str, Any]) -> str:
        self.last_prompt = prompt
        self.last_context = context
        return "ok"


class BrokenAPIWorker(APIWorker):
    AGENT_NAME = "broken_api"

    async def call_api(self, prompt: str, context: dict[str, Any]) -> str:
        raise RuntimeError("boom")


class APIWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_worker_runs_and_receives_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init"], cwd=repo, check=False, capture_output=True, text=True)

            step = StepSpec(step_id="step01", agent="dummy_api", role="implementer", prompt="implement this")
            job = JobSpec(
                job_id="job-test-api-0001",
                goal="test api worker",
                workdir=str(repo),
                steps=[step],
                policy=PolicySpec(),
                metadata={"ticket": "DEV-1"},
                context_window=[{"role": "user", "content": "previous message"}],
                context_strategy="sliding",
            )
            ctx = StepContext(
                job=job,
                step=step,
                job_dir=root / "artifacts" / job.job_id,
                step_dir=root / "artifacts" / job.job_id / "steps" / step.step_id,
                enable_real_cli=True,
                policy=_policy(),
                env_allowlist=set(),
                sensitive_env_vars=set(),
                sandbox_clear_env=False,
                max_input_artifacts_files=10,
                max_input_artifact_chars=12000,
                max_input_artifacts_chars=40000,
                context_window=list(job.context_window),
                context_strategy=job.context_strategy,
            )

            worker = DummyAPIWorker()
            result = await worker.run(ctx)

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(worker.last_prompt)
            self.assertIsNotNone(worker.last_context)
            self.assertEqual(worker.last_context["ticket"], "DEV-1")
            self.assertEqual((ctx.step_dir / "report.md").exists(), True)
            self.assertEqual((ctx.step_dir / "logs.txt").exists(), True)

    async def test_api_worker_handles_api_exception(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init"], cwd=repo, check=False, capture_output=True, text=True)

            step = StepSpec(step_id="step01", agent="broken_api", role="implementer", prompt="implement this")
            job = JobSpec(
                job_id="job-test-api-0002",
                goal="test api worker error",
                workdir=str(repo),
                steps=[step],
                policy=PolicySpec(),
            )
            ctx = StepContext(
                job=job,
                step=step,
                job_dir=root / "artifacts" / job.job_id,
                step_dir=root / "artifacts" / job.job_id / "steps" / step.step_id,
                enable_real_cli=True,
                policy=_policy(),
                env_allowlist=set(),
                sensitive_env_vars=set(),
                sandbox_clear_env=False,
                max_input_artifacts_files=10,
                max_input_artifact_chars=12000,
                max_input_artifacts_chars=40000,
            )

            result = await BrokenAPIWorker().run(ctx)
            self.assertEqual(result.status, "failed")
            self.assertIsNotNone(result.error)
            assert result.error is not None
            self.assertEqual(result.error.code, "api_error")


if __name__ == "__main__":
    unittest.main()
