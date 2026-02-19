from __future__ import annotations

import asyncio
import logging
from typing import Any

from orchestrator.models import StepResult, ErrorInfo, Metrics
from workers.base import BaseWorker, StepContext

log = logging.getLogger("workers.api")

class APIWorker(BaseWorker):
    """Base for API-based LLM (Kimi, GPT-4, etc.) instead of CLI."""
    AGENT_NAME = "api_base"

    async def call_api(self, prompt: str, context: dict) -> str:
        """Override this to implement actual API call."""
        raise NotImplementedError

    async def run(self, ctx: StepContext) -> StepResult:
        # Default run: build prompt, call API, write artifacts
        started_at = utc_now_iso()
        
        full_prompt = self.build_full_prompt(ctx)
        
        try:
            # Simulate API call for now unless overridden
            response_text = await self.call_api(full_prompt, ctx.job.metadata)
            status = "success"
            error = None
        except Exception as e:
            response_text = ""
            status = "failed"
            error = ErrorInfo(code="api_error", message=str(e))
            log.exception("API call failed")

        finished_at = utc_now_iso()

        # Simple artifacts
        report_md = f"# API Response ({self.AGENT_NAME})\n\n{response_text}"
        logs_txt = f"[{ctx.step.step_id}] API call to {self.AGENT_NAME}\nstatus={status}"
        
        self.write_artifacts(
            ctx,
            report_md=report_md,
            patch_diff="",  # API workers might return patches differently
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
            summary=f"API call completed: {status}",
            artifacts=self.artifact_paths(ctx),
            metrics=Metrics(duration_ms=0), # TODO: track
            error=error,
        )

from datetime import datetime, timezone
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
