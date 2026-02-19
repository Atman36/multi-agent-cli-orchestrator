from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from orchestrator.models import Metrics, StepResult
from orchestrator.subprocess_utils import run_command
from workers.base import BaseWorker, StepContext
from workers.registry import register_worker


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class OpenCodeWorker(BaseWorker):
    AGENT_NAME = "opencode"

    async def run(self, ctx: StepContext) -> StepResult:
        ctx.step_dir.mkdir(parents=True, exist_ok=True)

        if not ctx.enable_real_cli:
            return await self.simulate(ctx)

        full_prompt = self.build_full_prompt(ctx)
        base_commit = self.capture_base_commit(ctx)

        cmd = ["opencode", "run", "--format", "json", full_prompt]
        cmd = ctx.policy.wrap_command(cmd)

        started_at = utc_now_iso()
        result = await run_command(
            cmd,
            cwd=ctx.job.workdir,
            env={},
            env_allowlist=sorted(ctx.env_allowlist),
            timeout_sec=ctx.step.timeout_sec,
            idle_timeout_sec=ctx.idle_watchdog_sec,
            log_file=None,
        )
        finished_at = utc_now_iso()

        report_md = (
            f"# OpenCode step {ctx.step.step_id}\n\n"
            f"## Exit code\n\n`{result.exit_code}`\n\n"
            f"## Raw stdout\n\n```\n{result.stdout[:8000]}\n```\n\n"
            f"## Raw stderr\n\n```\n{result.stderr[:8000]}\n```\n"
        )
        patch_diff = self.capture_patch_diff(ctx, base_commit)
        logs_txt = (
            f"[{ctx.step.step_id}] opencode run\n"
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
        return StepResult(
            job_id=ctx.job.job_id,
            step_id=ctx.step.step_id,
            agent=ctx.step.agent,
            role=ctx.step.role,
            status=status,
            attempts=1,
            started_at=started_at,
            finished_at=finished_at,
            summary=f"OpenCode exit_code={result.exit_code}",
            artifacts=self.artifact_paths(ctx),
            metrics=Metrics(duration_ms=result.duration_ms),
            error=None,
        )

    async def simulate(self, ctx: StepContext) -> StepResult:
        started_at = utc_now_iso()
        await asyncio.sleep(0.4)
        finished_at = utc_now_iso()
        full_prompt = self.build_full_prompt(ctx)

        report_md = (
            f"# Planner output (simulated)\n\n"
            f"Agent: **OpenCode**\n\n"
            f"## Goal\n\n{ctx.job.goal}\n\n"
            f"## Prompt length\n\n{len(full_prompt)}\n\n"
            f"## Plan\n\n"
            "1. Inspect repository/workdir\n"
            "2. Identify changes\n"
            "3. Implement patch\n"
            "4. Run tests\n"
        )
        patch_diff = ""
        logs_txt = f"[{ctx.step.step_id}] simulated planning\n"

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
            summary="Simulated plan created",
            artifacts=self.artifact_paths(ctx),
            metrics=Metrics(duration_ms=400),
            error=None,
        )


register_worker(OpenCodeWorker())
