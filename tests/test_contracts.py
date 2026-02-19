from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.models import ArtifactPaths, JobResult, JobSpec, PolicySpec, StepResult, StepSpec, utc_now_iso
from orchestrator.policy import ExecutionPolicy
from workers.base import BaseWorker, StepContext

try:
    from orchestrator.validator import validate_json
except ModuleNotFoundError:  # pragma: no cover - optional in bare test env
    validate_json = None  # type: ignore[assignment]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _job_schema() -> Path:
    return _repo_root() / "contracts" / "job.schema.json"


def _result_schema() -> Path:
    return _repo_root() / "contracts" / "result.schema.json"


def _test_policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        allowed_binaries={"echo"},
        sandbox=False,
        sandbox_wrapper=None,
        sandbox_wrapper_args=[],
        network_policy="deny",
    )


@unittest.skipIf(validate_json is None, "jsonschema is not installed")
class ContractTests(unittest.TestCase):
    def test_job_schema_validation_for_model_dump(self) -> None:
        step = StepSpec(step_id="step01", agent="opencode", role="planner", prompt="plan")
        job = JobSpec(
            job_id="job-test-0001",
            goal="validate job schema",
            workdir=".",
            steps=[step],
            policy=PolicySpec(requires_approval=True),
        )
        validate_json(job.model_dump(), _job_schema())

    def test_step_result_schema_and_fixed_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            job_dir = Path(td) / "job"
            step_dir = job_dir / "steps" / "step01"
            step_dir.mkdir(parents=True, exist_ok=True)

            step = StepSpec(step_id="step01", agent="codex", role="implementer", prompt="implement")
            job = JobSpec(
                job_id="job-test-0002",
                goal="validate step result schema",
                workdir=str(job_dir),
                steps=[step],
                policy=PolicySpec(),
            )
            ctx = StepContext(
                job=job,
                step=step,
                job_dir=job_dir,
                step_dir=step_dir,
                enable_real_cli=False,
                policy=_test_policy(),
                env_allowlist=set(),
                sensitive_env_vars=set(),
                sandbox_clear_env=False,
                max_input_artifacts_files=10,
                max_input_artifact_chars=12000,
                max_input_artifacts_chars=40000,
            )

            paths = BaseWorker().artifact_paths(ctx)
            self.assertEqual(paths.report_md, "steps/step01/report.md")
            self.assertEqual(paths.patch_diff, "steps/step01/patch.diff")
            self.assertEqual(paths.logs_txt, "steps/step01/logs.txt")
            self.assertEqual(paths.result_json, "steps/step01/result.json")

            now = utc_now_iso()
            step_result = StepResult(
                job_id=job.job_id,
                step_id=step.step_id,
                agent=step.agent,
                role=step.role,
                status="success",
                attempts=1,
                started_at=now,
                finished_at=now,
                summary="ok",
                artifacts=paths,
                secrets_check="passed",
            )
            validate_json(step_result.model_dump(), _result_schema())

    def test_job_result_schema_and_fixed_artifact_paths(self) -> None:
        now = utc_now_iso()
        step_artifacts = ArtifactPaths(
            report_md="steps/step01/report.md",
            patch_diff="steps/step01/patch.diff",
            logs_txt="steps/step01/logs.txt",
            result_json="steps/step01/result.json",
        )
        step_result = StepResult(
            job_id="job-test-0003",
            step_id="step01",
            agent="claude",
            role="reviewer",
            status="success",
            attempts=1,
            started_at=now,
            finished_at=now,
            summary="reviewed",
            artifacts=step_artifacts,
            secrets_check="passed",
        )

        job_artifacts = ArtifactPaths(
            report_md="report.md",
            patch_diff="patch.diff",
            logs_txt="logs.txt",
            result_json="result.json",
        )
        self.assertEqual(job_artifacts.report_md, "report.md")
        self.assertEqual(job_artifacts.patch_diff, "patch.diff")
        self.assertEqual(job_artifacts.logs_txt, "logs.txt")
        self.assertEqual(job_artifacts.result_json, "result.json")

        job_result = JobResult(
            job_id="job-test-0003",
            status="success",
            started_at=now,
            finished_at=now,
            summary="completed",
            artifacts=job_artifacts,
            secrets_check="passed",
            steps=[step_result],
        )
        validate_json(job_result.model_dump(), _result_schema())


if __name__ == "__main__":
    unittest.main()
