from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from orchestrator.models import Metrics, StepResult
from orchestrator.subprocess_utils import CommandResult
from workers.agent_executor import AgentExecutor, ParsedOutput
from workers.base import StepContext
from workers.registry import register_worker


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class OpenCodeWorker(AgentExecutor):
    AGENT_NAME = "opencode"

    def build_cmd(self, ctx: StepContext, full_prompt: str) -> list[str]:
        return ["opencode", "run", "--format", "json", full_prompt]

    def parse_output(self, ctx: StepContext, result: CommandResult) -> ParsedOutput:
        return ParsedOutput(
            report_md=(
                f"# OpenCode step {ctx.step.step_id}\n\n"
                f"## Exit code\n\n`{result.exit_code}`\n\n"
                f"## Raw stdout\n\n```\n{result.stdout[:8000]}\n```\n\n"
                f"## Raw stderr\n\n```\n{result.stderr[:8000]}\n```\n"
            ),
            summary=f"OpenCode exit_code={result.exit_code}",
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
