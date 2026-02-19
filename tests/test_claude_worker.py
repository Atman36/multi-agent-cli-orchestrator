from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.models import JobSpec, PolicySpec, StepSpec
from orchestrator.policy import ExecutionPolicy
from workers.base import StepContext
from workers.claude_worker import ClaudeWorker, _claude_allowed_tools


def _policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        allowed_binaries={"claude", "git"},
        sandbox=False,
        sandbox_wrapper=None,
        sandbox_wrapper_args=[],
        network_policy="deny",
    )


def _ctx(step: StepSpec, root: Path) -> StepContext:
    job = JobSpec(
        job_id="job-test-claude-0001",
        goal="test claude tools",
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


class ClaudeWorkerTests(unittest.TestCase):
    def test_allowed_tools_respects_explicit_step_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            step = StepSpec(
                step_id="step01",
                agent="claude",
                role="implementer",
                prompt="implement",
                allowed_tools=["Read", "Edit", "Write", "Bash"],
            )
            ctx = _ctx(step, Path(td))
            self.assertEqual(_claude_allowed_tools(ctx), ["Read", "Edit", "Write", "Bash"])

    def test_allowed_tools_defaults_to_read_only_for_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            step = StepSpec(step_id="step02", agent="claude", role="reviewer", prompt="review")
            ctx = _ctx(step, Path(td))
            self.assertEqual(_claude_allowed_tools(ctx), ["Read", "Grep", "Glob"])

    def test_build_cmd_uses_step_allowed_tools(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            step = StepSpec(
                step_id="step03",
                agent="claude",
                role="implementer",
                prompt="implement",
                allowed_tools=["Read", "Edit"],
            )
            ctx = _ctx(step, Path(td))
            cmd = ClaudeWorker().build_cmd(ctx, "test prompt")
            self.assertIn("--allowedTools", cmd)
            self.assertIn("Read,Edit", cmd)

    def test_reviewer_forces_read_only_even_with_mutating_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            step = StepSpec(
                step_id="step04",
                agent="claude",
                role="reviewer",
                prompt="review",
                allowed_tools=["Read", "Edit", "Write", "Bash", "Grep"],
            )
            ctx = _ctx(step, Path(td))
            self.assertEqual(_claude_allowed_tools(ctx), ["Read", "Grep"])

    def test_unknown_tools_are_filtered_out(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            step = StepSpec(
                step_id="step05",
                agent="claude",
                role="implementer",
                prompt="implement",
                allowed_tools=["Read", "UnknownTool"],
            )
            ctx = _ctx(step, Path(td))
            self.assertEqual(_claude_allowed_tools(ctx), ["Read"])


if __name__ == "__main__":
    unittest.main()
