from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from orchestrator.models import ErrorInfo, Metrics, StepResult
from workers.base import BaseWorker, StepContext


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class APIResponse:
    report_md: str
    summary: str
    status: str | None = None
    error: ErrorInfo | None = None
    raw_response: str | None = None
    metrics: Metrics | None = None


class APIWorker(BaseWorker):
    """Base worker for direct LLM API integrations (OpenAI/Anthropic/etc.)."""

    AGENT_NAME = "api_base"

    async def call_api(self, prompt: str, context: dict[str, Any]) -> str | APIResponse:
        raise NotImplementedError

    def normalize_api_response(self, response: str | APIResponse) -> APIResponse:
        if isinstance(response, APIResponse):
            return response
        text = str(response).strip()
        report_md = (
            "# API response\n\n"
            f"{text or '[empty]'}\n"
        )
        summary = text.splitlines()[0][:200] if text else "API call completed"
        return APIResponse(
            report_md=report_md,
            summary=summary,
            status="success",
            raw_response=text,
        )

    def build_logs(self, ctx: StepContext, *, status: str, duration_ms: int) -> str:
        return (
            f"[{ctx.step.step_id}] {ctx.step.agent} api run\n"
            f"status={status}\n"
            f"duration_ms={duration_ms}\n"
        )

    async def run(self, ctx: StepContext) -> StepResult:
        ctx.step_dir.mkdir(parents=True, exist_ok=True)

        if not ctx.enable_real_cli:
            return await self.simulate(ctx)

        started_at = utc_now_iso()
        started_perf = time.perf_counter()

        patch_apply_error = self.apply_requested_patches(ctx)
        if patch_apply_error is not None:
            return self._build_early_failure(ctx, started_at=started_at, error=patch_apply_error)

        git_error = self.ensure_git_repo(ctx)
        if git_error is not None:
            return self._build_early_failure(ctx, started_at=started_at, error=git_error)

        full_prompt = self.build_full_prompt(ctx)
        base_commit = self.capture_base_commit(ctx)
        api_context = {
            "job_id": ctx.job.job_id,
            "step_id": ctx.step.step_id,
            "agent": ctx.step.agent,
            "role": ctx.step.role,
            "job_metadata": dict(ctx.job.metadata),
            "context_window": list(ctx.context_window),
            "context_strategy": ctx.context_strategy,
        }

        try:
            response_obj = self.normalize_api_response(await self.call_api(full_prompt, api_context))
        except Exception as e:
            response_obj = APIResponse(
                report_md=(
                    f"# API call failed\n\n"
                    f"- error: `{e}`\n"
                ),
                summary="API call failed",
                status="failed",
                error=ErrorInfo(code="api_call_failed", message=str(e)),
                raw_response=str(e),
            )

        finished_at = utc_now_iso()
        duration_ms = max(0, int((time.perf_counter() - started_perf) * 1000))
        status = response_obj.status or ("success" if response_obj.error is None else "failed")
        error = response_obj.error
        if status != "success" and error is None:
            error = ErrorInfo(code="api_failed", message="API worker returned non-success status")

        patch_diff = self.capture_patch_diff(ctx, base_commit)
        logs_txt = self.build_logs(ctx, status=status, duration_ms=duration_ms)
        raw_stderr = error.message if error is not None else None

        self.write_artifacts(
            ctx,
            report_md=response_obj.report_md,
            patch_diff=patch_diff,
            logs_txt=logs_txt,
            raw_stdout=response_obj.raw_response,
            raw_stderr=raw_stderr,
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
            summary=response_obj.summary,
            artifacts=self.artifact_paths(ctx),
            metrics=response_obj.metrics or Metrics(duration_ms=duration_ms),
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
            f"[{ctx.step.step_id}] {ctx.step.agent} api run skipped\n"
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
