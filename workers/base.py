from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from orchestrator.git_utils import current_head_commit, diff_since_commit, is_git_repo
from orchestrator.log_sanitizer import redact
from orchestrator.models import ArtifactPaths, ErrorInfo, JobSpec, Metrics, StepResult, StepSpec
from orchestrator.policy import ExecutionPolicy


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_within(base: Path, target: Path) -> bool:
    return target == base or base in target.parents


@dataclass(frozen=True)
class StepContext:
    job: JobSpec
    step: StepSpec

    job_dir: Path
    step_dir: Path

    enable_real_cli: bool
    policy: ExecutionPolicy
    env_allowlist: set[str]
    sensitive_env_vars: set[str]
    sandbox_clear_env: bool
    max_input_artifacts_files: int
    max_input_artifact_chars: int
    max_input_artifacts_chars: int
    idle_watchdog_sec: int | None = None
    non_git_workdir_status: str = "needs_human"


class WorkerError(RuntimeError):
    pass


class BaseWorker:
    AGENT_NAME: str = "base"

    async def run(self, ctx: StepContext) -> StepResult:
        """Execute a step and return a StepResult.

        Workers MUST write fixed artifacts into ctx.step_dir:
          - report.md
          - patch.diff
          - logs.txt
        Runner will persist result.json after it gets StepResult back.
        """
        return await self.simulate(ctx)

    @staticmethod
    @lru_cache(maxsize=16)
    def load_prompt(worker_name: str) -> str:
        repo_root = Path(__file__).resolve().parents[1]
        prompt_path = repo_root / "prompts" / f"{worker_name}.md"
        if not prompt_path.exists():
            return ""
        return prompt_path.read_text(encoding="utf-8").strip()

    def build_full_prompt(self, ctx: StepContext) -> str:
        prompt = ctx.step.prompt
        system_prompt = self.load_prompt(ctx.step.agent)
        if system_prompt:
            prompt = f"{system_prompt}\n\n## Task\n{prompt}"

        if not ctx.step.input_artifacts:
            return prompt

        parts = [prompt.rstrip(), "", "## Input artifacts"]
        remaining_total = max(0, ctx.max_input_artifacts_chars)
        per_file_limit = max(0, ctx.max_input_artifact_chars)
        max_files = max(0, ctx.max_input_artifacts_files)
        used_files = 0
        truncated = False

        for rel_path in ctx.step.input_artifacts:
            if used_files >= max_files:
                truncated = True
                break

            abs_path = (ctx.job_dir / rel_path).resolve()
            header = f"=== BEGIN ARTIFACT: {rel_path} ==="
            footer = "=== END ARTIFACT ==="

            if not _is_within(ctx.job_dir.resolve(), abs_path):
                parts.extend([header, "[invalid_path]", footer])
                used_files += 1
                continue
            if not abs_path.exists():
                parts.extend([header, "[missing]", footer])
                used_files += 1
                continue

            text = abs_path.read_text(encoding="utf-8", errors="replace")
            truncation_notes: list[str] = []

            if per_file_limit == 0:
                text = ""
                truncation_notes.append("[truncated:file_limit]")
            elif len(text) > per_file_limit:
                text = text[:per_file_limit]
                truncation_notes.append("[truncated:file_limit]")

            if remaining_total <= 0:
                parts.extend([header, "[truncated:total_limit]", footer])
                truncated = True
                used_files += 1
                continue

            if len(text) > remaining_total:
                text = text[:remaining_total]
                truncation_notes.append("[truncated:total_limit]")
                remaining_total = 0
                truncated = True
            else:
                remaining_total -= len(text)

            if truncation_notes:
                text = f"{text}\n" + "\n".join(truncation_notes)
                truncated = True

            parts.extend([header, text, footer])
            used_files += 1

        if truncated:
            parts.append("[artifacts_truncated_or_limited]")

        return "\n".join(parts).rstrip() + "\n"

    def artifact_paths(self, ctx: StepContext) -> ArtifactPaths:
        return ArtifactPaths(
            report_md=str(Path("steps") / ctx.step.step_id / "report.md"),
            patch_diff=str(Path("steps") / ctx.step.step_id / "patch.diff"),
            logs_txt=str(Path("steps") / ctx.step.step_id / "logs.txt"),
            result_json=str(Path("steps") / ctx.step.step_id / "result.json"),
        )

    def redact_text(self, text: str, ctx: StepContext) -> str:
        return redact(text, sensitive_env_vars=ctx.sensitive_env_vars)

    def write_artifacts(
        self,
        ctx: StepContext,
        *,
        report_md: str,
        patch_diff: str,
        logs_txt: str,
        raw_stdout: str | None = None,
        raw_stderr: str | None = None,
    ) -> None:
        ctx.step_dir.mkdir(parents=True, exist_ok=True)
        (ctx.step_dir / "report.md").write_text(self.redact_text(report_md, ctx), encoding="utf-8")
        (ctx.step_dir / "patch.diff").write_text(self.redact_text(patch_diff, ctx), encoding="utf-8")
        (ctx.step_dir / "logs.txt").write_text(self.redact_text(logs_txt, ctx), encoding="utf-8")

        if raw_stdout is not None:
            (ctx.step_dir / "raw_stdout.txt").write_text(self.redact_text(raw_stdout, ctx), encoding="utf-8")
        if raw_stderr is not None:
            (ctx.step_dir / "raw_stderr.txt").write_text(self.redact_text(raw_stderr, ctx), encoding="utf-8")

    def capture_base_commit(self, ctx: StepContext) -> str | None:
        return current_head_commit(ctx.job.workdir)

    def capture_patch_diff(self, ctx: StepContext, base_commit: str | None) -> str:
        return diff_since_commit(ctx.job.workdir, base_commit)

    def ensure_git_repo(self, ctx: StepContext) -> ErrorInfo | None:
        if is_git_repo(ctx.job.workdir):
            return None
        return ErrorInfo(
            code="non_git_workdir",
            message=f"Workdir is not a git repository: {ctx.job.workdir}",
            details={"workdir": ctx.job.workdir, "status": ctx.non_git_workdir_status},
        )

    def apply_requested_patches(self, ctx: StepContext) -> ErrorInfo | None:
        if not ctx.step.apply_patches_from:
            return None

        git_error = self.ensure_git_repo(ctx)
        if git_error is not None:
            return git_error

        job_root = ctx.job_dir.resolve()
        for rel_patch in ctx.step.apply_patches_from:
            patch_path = (ctx.job_dir / rel_patch).resolve()
            if not _is_within(job_root, patch_path):
                return ErrorInfo(
                    code="invalid_patch_path",
                    message=f"Patch path escapes job dir: {rel_patch}",
                    details={"patch": rel_patch},
                )
            if not patch_path.exists():
                return ErrorInfo(
                    code="missing_patch",
                    message=f"Patch file does not exist: {rel_patch}",
                    details={"patch": rel_patch},
                )
            if patch_path.is_dir():
                return ErrorInfo(
                    code="invalid_patch_path",
                    message=f"Patch path is a directory: {rel_patch}",
                    details={"patch": rel_patch},
                )

            proc = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", str(patch_path)],
                cwd=ctx.job.workdir,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                return ErrorInfo(
                    code="patch_apply_failed",
                    message=f"Failed to apply patch: {rel_patch}",
                    details={
                        "patch": rel_patch,
                        "exit_code": proc.returncode,
                        "stderr": proc.stderr.strip(),
                    },
                )
        return None

    async def simulate(self, ctx: StepContext) -> StepResult:
        """Default simulation: create deterministic artifacts."""
        ctx.step_dir.mkdir(parents=True, exist_ok=True)

        started_at = utc_now_iso()
        await asyncio.sleep(0.5)
        finished_at = utc_now_iso()
        full_prompt = self.build_full_prompt(ctx)

        report_md = (
            f"# Step {ctx.step.step_id}\n\n"
            f"- agent: **{ctx.step.agent}**\n"
            f"- role: **{ctx.step.role}**\n\n"
            f"## Prompt\n\n{full_prompt}\n\n"
            f"## Output (simulated)\n\n"
            f"This is a simulated worker run. Replace simulation with real CLI execution.\n"
        )

        patch_diff = (
            "diff --git a/README.md b/README.md\n"
            "index 0000000..1111111 100644\n"
            "--- a/README.md\n"
            "+++ b/README.md\n"
            "@@ -0,0 +1,2 @@\n"
            f"+Simulated change from {ctx.step.agent}:{ctx.step.role}\n"
            "+TODO: replace with real patch\n"
        )

        logs_txt = (
            f"[{ctx.step.step_id}] Simulated logs\n"
            f"prompt_length={len(full_prompt)}\n"
            "tests: (skipped)\n"
        )

        self.write_artifacts(
            ctx,
            report_md=report_md,
            patch_diff=patch_diff,
            logs_txt=logs_txt,
        )

        return StepResult(
            job_id=ctx.job.job_id,
            step_id=ctx.step.step_id,
            agent=ctx.step.agent,
            role=ctx.step.role,
            status="success",
            attempts=1,
            started_at=started_at,
            finished_at=finished_at,
            summary="Simulated success",
            artifacts=self.artifact_paths(ctx),
            metrics=Metrics(duration_ms=500),
            error=None,
        )
