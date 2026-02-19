from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from orchestrator.models import ErrorInfo, Metrics, StepResult
from orchestrator.subprocess_utils import run_command
from workers.base import BaseWorker, StepContext
from workers.registry import register_worker


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_allowed_tools(role: str) -> list[str]:
    normalized = role.lower()
    if "implement" in normalized:
        return ["Read", "Write", "Edit", "Bash(git *)"]
    if "review" in normalized:
        return ["Read", "Grep", "Glob"]
    return ["Read", "Grep", "Glob"]


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out_text = _content_text(item)
            if out_text:
                out.append(out_text)
        return "\n".join(out).strip()
    if isinstance(value, dict):
        if "text" in value and isinstance(value["text"], str):
            return value["text"]
        if "content" in value:
            return _content_text(value["content"])
    return ""


def _extract_claude_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        out: list[str] = []
        for item in payload:
            piece = _extract_claude_text(item)
            if piece:
                out.append(piece)
        return "\n".join(out).strip()
    if isinstance(payload, dict):
        for key in ("result", "output_text", "output", "text", "completion"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val
        if "content" in payload:
            text = _content_text(payload["content"])
            if text:
                return text
        if isinstance(payload.get("message"), dict):
            text = _content_text(payload["message"])
            if text:
                return text
        if isinstance(payload.get("messages"), list):
            text = _content_text(payload["messages"])
            if text:
                return text
    return ""


class ClaudeWorker(BaseWorker):
    AGENT_NAME = "claude"

    async def run(self, ctx: StepContext) -> StepResult:
        ctx.step_dir.mkdir(parents=True, exist_ok=True)

        if not ctx.enable_real_cli:
            return await self.simulate(ctx)

        full_prompt = self.build_full_prompt(ctx)
        base_commit = self.capture_base_commit(ctx)
        allowed_tools = ctx.step.allowed_tools or _default_allowed_tools(ctx.step.role)

        cmd = [
            "claude",
            "-p",
            full_prompt,
            "--allowedTools",
            ",".join(allowed_tools),
            "--output-format",
            "json",
        ]
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

        parse_error: str | None = None
        extracted_text = ""
        payload: Any = None

        try:
            payload = json.loads(result.stdout)
            extracted_text = _extract_claude_text(payload).strip()
            if not extracted_text and payload is not None:
                extracted_text = json.dumps(payload, ensure_ascii=False, indent=2)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)

        if result.exit_code != 0 and parse_error is None:
            parse_error = f"claude exited with code {result.exit_code}"

        status = "success"
        error: ErrorInfo | None = None
        if parse_error is not None:
            status = "failed"
            error = ErrorInfo(
                code="parse_error",
                message=parse_error,
                details={"exit_code": result.exit_code},
            )

        if status == "success":
            report_md = (
                "# Claude review\n\n"
                "## Parsed response\n\n"
                f"{extracted_text}\n"
            )
            summary = extracted_text.strip().splitlines()[0][:200] if extracted_text.strip() else "Claude response parsed"
        else:
            report_md = (
                "# Claude review [parse_error]\n\n"
                f"- exit_code: `{result.exit_code}`\n"
                f"- parse_error: `{parse_error}`\n\n"
                "## Raw stdout\n\n"
                f"```\n{result.stdout[:8000]}\n```\n\n"
                "## Raw stderr\n\n"
                f"```\n{result.stderr[:8000]}\n```\n"
            )
            summary = f"Claude parse_error (exit_code={result.exit_code})"

        patch_diff = self.capture_patch_diff(ctx, base_commit)
        logs_txt = (
            f"[{ctx.step.step_id}] claude run\n"
            f"exit_code={result.exit_code}\n"
            f"duration_ms={result.duration_ms}\n"
            f"killed_by_watchdog={result.killed_by_watchdog}\n"
            f"allowed_tools={','.join(allowed_tools)}\n"
            f"status={status}\n"
        )

        self.write_artifacts(
            ctx,
            report_md=report_md,
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
            summary=summary,
            artifacts=self.artifact_paths(ctx),
            metrics=Metrics(duration_ms=result.duration_ms),
            error=error,
        )

    async def simulate(self, ctx: StepContext) -> StepResult:
        started_at = utc_now_iso()
        await asyncio.sleep(0.3)
        finished_at = utc_now_iso()
        full_prompt = self.build_full_prompt(ctx)

        report_md = (
            f"# Review output (simulated)\n\n"
            f"Agent: **Claude**\n\n"
            f"## Prompt length\n\n{len(full_prompt)}\n\n"
            "## Review\n\n"
            "- ✅ Structure looks OK for MVP\n"
            "- ⚠️ Replace simulation with real CLI execution\n"
            "- ✅ Ensure allowlist and sandbox are enabled for untrusted code\n"
        )
        logs_txt = f"[{ctx.step.step_id}] simulated review\n"

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
            status="success",
            attempts=1,
            started_at=started_at,
            finished_at=finished_at,
            summary="Simulated review created",
            artifacts=self.artifact_paths(ctx),
            metrics=Metrics(duration_ms=300),
            error=None,
        )


register_worker(ClaudeWorker())
