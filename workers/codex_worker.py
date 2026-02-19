from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from orchestrator.models import ErrorInfo, Metrics, StepResult
from orchestrator.subprocess_utils import run_command
from workers.base import BaseWorker, StepContext
from workers.registry import register_worker


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CodexWorker(BaseWorker):
    AGENT_NAME = "codex"

    async def run(self, ctx: StepContext) -> StepResult:
        ctx.step_dir.mkdir(parents=True, exist_ok=True)

        if not ctx.enable_real_cli:
            return await self.simulate(ctx)

        full_prompt = self.build_full_prompt(ctx)
        base_commit = self.capture_base_commit(ctx)

        cmd = ["codex", "exec", "--json", full_prompt]
        cmd = ctx.policy.wrap_command(cmd)

        started_at = utc_now_iso()
        result = await run_command(
            cmd,
            cwd=ctx.job.workdir,
            env={},
            env_allowlist=sorted(ctx.env_allowlist),
            clear_env=ctx.sandbox_clear_env,
            timeout_sec=ctx.step.timeout_sec,
            idle_timeout_sec=ctx.idle_watchdog_sec,
            log_file=None,
        )
        finished_at = utc_now_iso()

        report_md = (
            f"# Codex implementer\n\n"
            f"## Exit code\n\n`{result.exit_code}`\n\n"
            f"## Raw stdout\n\n```\n{result.stdout[:8000]}\n```\n\n"
            f"## Raw stderr\n\n```\n{result.stderr[:8000]}\n```\n"
        )
        patch_diff = self.capture_patch_diff(ctx, base_commit)
        logs_txt = (
            f"[{ctx.step.step_id}] codex run\n"
            f"exit_code={result.exit_code}\n"
            f"duration_ms={result.duration_ms}\n"
            f"killed_by_watchdog={result.killed_by_watchdog}\n"
        )

        self.write_artifacts(
            ctx,
            report_md=report_md,
            patch_diff=patch_diff,
            logs_txt=logs_txt,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
        )

        status = "success" if result.exit_code == 0 else "failed"
        error = None
        if status != "success":
            error = ErrorInfo(
                code="agent_exit_nonzero",
                message=f"codex exited with code {result.exit_code}",
                details={"exit_code": result.exit_code},
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
            summary=f"Codex exit_code={result.exit_code}",
            artifacts=self.artifact_paths(ctx),
            metrics=Metrics(duration_ms=result.duration_ms),
            error=error,
        )

    async def simulate(self, ctx: StepContext) -> StepResult:
        started_at = utc_now_iso()
        await asyncio.sleep(0.6)
        finished_at = utc_now_iso()
        full_prompt = self.build_full_prompt(ctx)

        report_md = (
            f"# Implementation output (simulated)\n\n"
            f"Agent: **Codex**\n\n"
            f"## Prompt length\n\n{len(full_prompt)}\n\n"
            f"## What was done\n\n"
            "- Added placeholder implementation\n"
            "- (Simulated) tests passed\n"
        )
        patch_diff = (
            "diff --git a/src/example.txt b/src/example.txt\n"
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            "--- /dev/null\n"
            "+++ b/src/example.txt\n"
            "@@ -0,0 +1,1 @@\n"
            "+hello from simulated codex worker\n"
        )
        logs_txt = (
            f"[{ctx.step.step_id}] simulated implementation\n"
            "pytest: passed (simulated)\n"
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
            summary="Simulated implementation created",
            artifacts=self.artifact_paths(ctx),
            metrics=Metrics(duration_ms=600),
            error=None,
        )


register_worker(CodexWorker())
