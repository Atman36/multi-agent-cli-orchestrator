from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from orchestrator.models import ErrorInfo, Metrics, StepResult
from orchestrator.subprocess_utils import CommandResult
from workers.agent_executor import AgentExecutor, ParsedOutput
from workers.base import StepContext
from workers.registry import register_worker

log = logging.getLogger("workers.claude")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


CLAUDE_SAFE_TOOLS = {
    "Read",
    "Grep",
    "Glob",
    "Edit",
    "Write",
    "Bash",
}
CLAUDE_REVIEWER_TOOLS = ["Read", "Grep", "Glob"]


def _default_allowed_tools(role: str) -> list[str]:
    normalized = role.lower()
    if "review" in normalized:
        return CLAUDE_REVIEWER_TOOLS
    # Claude stays review-first in this orchestrator.
    return CLAUDE_REVIEWER_TOOLS


def _claude_allowed_tools(ctx: StepContext) -> list[str]:
    requested = ctx.step.allowed_tools
    role_is_reviewer = "review" in ctx.step.role.lower()
    if requested is None:
        return _default_allowed_tools(ctx.step.role)

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_tool in requested:
        tool = str(raw_tool).strip()
        if not tool or tool in seen:
            continue
        normalized.append(tool)
        seen.add(tool)

    if not normalized:
        return _default_allowed_tools(ctx.step.role)

    unknown = sorted([tool for tool in normalized if tool not in CLAUDE_SAFE_TOOLS])
    if unknown:
        log.warning(
            "Step %s requested unknown Claude tools: %s",
            ctx.step.step_id,
            ",".join(unknown),
        )

    filtered = [tool for tool in normalized if tool in CLAUDE_SAFE_TOOLS]
    if not filtered:
        return _default_allowed_tools(ctx.step.role)

    if role_is_reviewer:
        reviewer_filtered = [tool for tool in filtered if tool in CLAUDE_REVIEWER_TOOLS]
        denied = [tool for tool in filtered if tool not in CLAUDE_REVIEWER_TOOLS]
        if denied:
            log.warning(
                "Step %s requested mutating Claude tools for reviewer role; forcing read-only: %s",
                ctx.step.step_id,
                ",".join(denied),
            )
        return reviewer_filtered or CLAUDE_REVIEWER_TOOLS

    return filtered


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


class ClaudeWorker(AgentExecutor):
    AGENT_NAME = "claude"

    def build_cmd(self, ctx: StepContext, full_prompt: str) -> list[str]:
        allowed_tools = _claude_allowed_tools(ctx)
        return [
            "claude",
            "-p",
            full_prompt,
            "--allowedTools",
            ",".join(allowed_tools),
            "--output-format",
            "json",
        ]

    def parse_output(self, ctx: StepContext, result: CommandResult) -> ParsedOutput:
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

        status: str | None = "success"
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

        return ParsedOutput(
            report_md=report_md,
            summary=summary,
            status=status,
            error=error,
        )

    def build_logs(self, ctx: StepContext, result: CommandResult, status: str) -> str:
        allowed_tools = _claude_allowed_tools(ctx)
        return (
            f"[{ctx.step.step_id}] claude run\n"
            f"exit_code={result.exit_code}\n"
            f"duration_ms={result.duration_ms}\n"
            f"killed_by_watchdog={result.killed_by_watchdog}\n"
            f"allowed_tools={','.join(allowed_tools)}\n"
            f"status={status}\n"
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
