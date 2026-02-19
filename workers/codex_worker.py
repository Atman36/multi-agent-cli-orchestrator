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


class CodexWorker(AgentExecutor):
    AGENT_NAME = "codex"

    def build_cmd(self, ctx: StepContext, full_prompt: str) -> list[str]:
        return ["codex", "exec", "--json", full_prompt]

    def parse_output(self, ctx: StepContext, result: CommandResult) -> ParsedOutput:
        return ParsedOutput(
            report_md=(
                "# Codex implementer\n\n"
                f"## Exit code\n\n`{result.exit_code}`\n\n"
                f"## Raw stdout\n\n```\n{result.stdout[:8000]}\n```\n\n"
                f"## Raw stderr\n\n```\n{result.stderr[:8000]}\n```\n"
            ),
            summary=f"Codex exit_code={result.exit_code}",
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
