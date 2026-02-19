from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from orchestrator.models import ErrorInfo, Metrics, StepResult, StepSpec
from orchestrator.subprocess_utils import CommandResult, run_command
from workers.base import BaseWorker, StepContext


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ParsedOutput:
    report_md: str
    summary: str
    status: str | None = None
    error: ErrorInfo | None = None


class AgentExecutor(BaseWorker):
    def required_binaries(self, step: StepSpec) -> set[str]:
        return {step.agent, "git"}

    def build_cmd(self, ctx: StepContext, full_prompt: str) -> list[str]:
        raise NotImplementedError

    def parse_output(self, ctx: StepContext, result: CommandResult) -> ParsedOutput:
        report_md = (
            f"# {ctx.step.agent} step {ctx.step.step_id}\n\n"
            f"## Exit code\n\n`{result.exit_code}`\n\n"
            f"## Raw stdout\n\n```\n{result.stdout[:8000]}\n```\n\n"
            f"## Raw stderr\n\n```\n{result.stderr[:8000]}\n```\n"
        )
        return ParsedOutput(
            report_md=report_md,
            summary=f"{ctx.step.agent} exit_code={result.exit_code}",
        )

    def postprocess_patch(self, ctx: StepContext, patch_diff: str) -> str:
        return patch_diff

    def build_logs(self, ctx: StepContext, result: CommandResult, status: str) -> str:
        return (
            f"[{ctx.step.step_id}] {ctx.step.agent} run\n"
            f"exit_code={result.exit_code}\n"
            f"duration_ms={result.duration_ms}\n"
            f"killed_by_watchdog={result.killed_by_watchdog}\n"
            f"status={status}\n"
        )

    async def run(self, ctx: StepContext) -> StepResult:
        ctx.step_dir.mkdir(parents=True, exist_ok=True)

        if not ctx.enable_real_cli:
            return await self.simulate(ctx)

        started_at = utc_now_iso()
        patch_apply_error = self.apply_requested_patches(ctx)
        if patch_apply_error is not None:
            return self._build_early_failure(ctx, started_at=started_at, error=patch_apply_error)

        git_error = self.ensure_git_repo(ctx)
        if git_error is not None:
            return self._build_early_failure(ctx, started_at=started_at, error=git_error)

        full_prompt = self.build_full_prompt(ctx)
        base_commit = self.capture_base_commit(ctx)

        cmd = self.build_cmd(ctx, full_prompt)
        cmd = ctx.policy.wrap_command(cmd)

        result = await run_command(
            cmd,
            cwd=ctx.job.workdir,
            env={},
            env_allowlist=sorted(ctx.env_allowlist),
            clear_env=ctx.sandbox_clear_env,
            timeout_sec=ctx.step.timeout_sec,
            idle_timeout_sec=ctx.idle_watchdog_sec,
            max_output_chars=ctx.max_subprocess_output_chars,
            log_file=None,
        )
        finished_at = utc_now_iso()

        parsed = self.parse_output(ctx, result)
        status = parsed.status or ("success" if result.exit_code == 0 else "failed")
        error = parsed.error
        if status != "success" and error is None:
            error = ErrorInfo(
                code="agent_exit_nonzero",
                message=f"{ctx.step.agent} exited with code {result.exit_code}",
                details={"exit_code": result.exit_code},
            )

        patch_diff = self.postprocess_patch(ctx, self.capture_patch_diff(ctx, base_commit))
        patch_has_changes = bool(patch_diff.strip())
        change_status = "changed" if status == "success" and patch_has_changes else "no_changes" if status == "success" else None
        logs_txt = self.build_logs(ctx, result, status)
        if change_status is not None:
            logs_txt += f"change_status={change_status}\n"

        self.write_artifacts(
            ctx,
            report_md=parsed.report_md,
            patch_diff=patch_diff,
            logs_txt=logs_txt,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
        )

        return StepResult(
            job_id=ctx.job.job_id,
            step_id=ctx.step.step_id,
            agent=ctx.step.agent,
            role=ctx.step.role,
            status=status,
            attempts=1,
            started_at=started_at,
            finished_at=finished_at,
            summary=(
                f"{parsed.summary} ({change_status})"
                if change_status is not None
                else parsed.summary
            ),
            change_status=change_status,
            artifacts=self.artifact_paths(ctx),
            metrics=Metrics(duration_ms=result.duration_ms),
            error=error,
        )

    def _build_early_failure(self, ctx: StepContext, *, started_at: str, error: ErrorInfo) -> StepResult:
        finished_at = utc_now_iso()
        status = ctx.non_git_workdir_status if error.code == "non_git_workdir" else "failed"
        report_md = (
            f"# {ctx.step.agent} step {ctx.step.step_id} [{status}]\n\n"
            f"- error: `{error.code}`\n"
            f"- message: `{error.message}`\n\n"
            "## Details\n\n"
            f"```\n{error.details}\n```\n"
        )
        logs_txt = (
            f"[{ctx.step.step_id}] {ctx.step.agent} run skipped\n"
            f"status={status}\n"
            f"error={error.code}\n"
        )

        self.write_artifacts(
            ctx,
            report_md=report_md,
            patch_diff="",
            logs_txt=logs_txt,
        )

        return StepResult(
            job_id=ctx.job.job_id,
            step_id=ctx.step.step_id,
            agent=ctx.step.agent,
            role=ctx.step.role,
            status=status,
            attempts=1,
            started_at=started_at,
            finished_at=finished_at,
            summary=error.message[:200],
            artifacts=self.artifact_paths(ctx),
            metrics=Metrics(duration_ms=0),
            error=error,
        )
