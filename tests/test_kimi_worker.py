from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.models import JobSpec, PolicySpec, StepSpec
from orchestrator.policy import ExecutionPolicy
from workers import ensure_workers_registered, list_workers
from workers.base import StepContext
from workers.kimi_worker import KimiWorker


def _policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        allowed_binaries={"kimi", "git"},
        sandbox=False,
        sandbox_wrapper=None,
        sandbox_wrapper_args=[],
        network_policy="deny",
    )


def _ctx(step: StepSpec, root: Path) -> StepContext:
    job = JobSpec(
        job_id="job-test-kimi-0001",
        goal="test kimi command",
        workdir=str(root),
        steps=[step],
        policy=PolicySpec(),
    )
    return StepContext(
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
    )


class KimiWorkerTests(unittest.TestCase):
    def test_call_api_simulated_response(self) -> None:
        import asyncio
        async def run_test() -> None:
            worker = KimiWorker()
            result = await worker.call_api("test prompt", {})
            self.assertIn("Kimi (Simulated)", result)
            
        asyncio.run(run_test())

    def test_worker_is_registered(self) -> None:
        ensure_workers_registered()
        self.assertIn("kimi", list_workers())


if __name__ == "__main__":
    unittest.main()
