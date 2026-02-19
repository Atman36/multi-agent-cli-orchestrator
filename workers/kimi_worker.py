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


class KimiWorker(AgentExecutor):
    AGENT_NAME = "kimi"

    def build_cmd(self, ctx: StepContext, full_prompt: str) -> list[str]:
        return [
            "kimi",
            "--print",
            "--output-format",
            "text",
            "--final-message-only",
            "--prompt",
            full_prompt,
        ]

    def parse_output(self, ctx: StepContext, result: CommandResult) -> ParsedOutput:
        return ParsedOutput(
            report_md=(
                f"# Kimi step {ctx.step.step_id}\n\n"
                f"## Exit code\n\n`{result.exit_code}`\n\n"
                f"## Raw stdout\n\n```\n{result.stdout[:8000]}\n```\n\n"
                f"## Raw stderr\n\n```\n{result.stderr[:8000]}\n```\n"
            ),
            summary=f"Kimi exit_code={result.exit_code}",
        )

    async def simulate(self, ctx: StepContext) -> StepResult:
        started_at = utc_now_iso()
        await asyncio.sleep(0.5)
        finished_at = utc_now_iso()
        full_prompt = self.build_full_prompt(ctx)

        report_md = (
            f"# Kimi output (simulated)\n\n"
            f"Agent: **Kimi**\n\n"
            f"## Prompt length\n\n{len(full_prompt)}\n\n"
            f"## Response\n\n"
            "Simulated Kimi response. Replace with real CLI execution.\n"
        )
        patch_diff = (
            "diff --git a/example.txt b/example.txt\n"
            "index 0000000..1111111 100644\n"
            "--- a/example.txt\n"
            "+++ b/example.txt\n"
            "@@ -0,0 +1 @@\n"
            "+Simulated change from kimi worker\n"
        )
        logs_txt = (
            f"[{ctx.step.step_id}] simulated kimi run\n"
            f"prompt_length={len(full_prompt)}\n"
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
            summary="Simulated Kimi run",
            artifacts=self.artifact_paths(ctx),
            metrics=Metrics(duration_ms=500),
            error=None,
        )


register_worker(KimiWorker())
