from __future__ import annotations

import unittest

from orchestrator.models import JobSpec, PolicySpec, StepSpec
from orchestrator.step_requirements import required_binaries_for_job
from workers import ensure_workers_registered


class RunnerDynamicPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        ensure_workers_registered()

    def test_collects_only_required_cli_binaries_for_job(self) -> None:
        steps = [
            StepSpec(step_id="01_plan", agent="opencode", role="planner", prompt="plan"),
            StepSpec(step_id="02_impl", agent="codex", role="implementer", prompt="impl"),
        ]
        job = JobSpec(
            job_id="job-test-dynamic-preflight-1",
            goal="test",
            steps=steps,
            policy=PolicySpec(),
        )
        required = required_binaries_for_job(job)
        self.assertEqual(required, {"opencode", "codex", "git"})

    def test_api_only_job_requires_no_cli_binary(self) -> None:
        steps = [
            StepSpec(step_id="01_kimi", agent="kimi", role="analyst", prompt="analyze"),
        ]
        job = JobSpec(
            job_id="job-test-dynamic-preflight-2",
            goal="test",
            steps=steps,
            policy=PolicySpec(),
        )
        required = required_binaries_for_job(job)
        self.assertEqual(required, set())


if __name__ == "__main__":
    unittest.main()
