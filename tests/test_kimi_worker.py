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
    def test_build_cmd_uses_non_interactive_prompt_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            step = StepSpec(step_id="step01", agent="kimi", role="assistant", prompt="implement")
            ctx = _ctx(step, Path(td))
            cmd = KimiWorker().build_cmd(ctx, "test prompt")

            self.assertEqual(cmd[0], "kimi")
            self.assertIn("--print", cmd)
            self.assertIn("--output-format", cmd)
            self.assertIn("--final-message-only", cmd)
            self.assertIn("--prompt", cmd)
            self.assertNotIn("run", cmd)

    def test_worker_is_registered(self) -> None:
        ensure_workers_registered()
        self.assertIn("kimi", list_workers())


if __name__ == "__main__":
    unittest.main()
