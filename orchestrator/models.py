from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


AGENT = str
NETWORK_POLICY = Literal["deny", "allow"]
SECRETS_CHECK = Literal["passed", "failed"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobSource(BaseModel):
    type: Literal["webhook", "manual", "cron"] = "manual"
    meta: dict[str, Any] = Field(default_factory=dict)


ON_FAILURE = Literal["stop", "continue", "ask_human"]


class StepSpec(BaseModel):
    step_id: str = Field(..., description="Unique step id within job")
    agent: AGENT
    role: str = Field(..., description="Human-readable role (planner/implementer/reviewer/etc)")
    prompt: str = Field(..., description="Prompt for the agent")
    timeout_sec: int = Field(default=600, ge=1, le=3600)
    max_retries: int = Field(default=1, ge=0, le=10)
    retry_backoff_sec: int = Field(default=2, ge=0, le=60)
    input_artifacts: list[str] = Field(default_factory=list, description="Relative paths inside artifacts/<job_id>/")
    apply_patches_from: list[str] = Field(default_factory=list, description="Relative patch paths to apply before the step")
    allowed_tools: list[str] | None = Field(default=None, description="Tool allowlist override for compatible agents")
    on_failure: str = Field(
        default="stop",
        description=(
            "Failure strategy: 'stop' (default) halts pipeline, 'continue' proceeds to next step, "
            "'ask_human' pauses job and moves it to awaiting_approval, "
            "'goto:<step_id>' jumps to named step"
        ),
    )

    @field_validator("on_failure")
    @classmethod
    def _validate_on_failure(cls, value: str) -> str:
        if value in {"stop", "continue", "ask_human"}:
            return value
        if re.fullmatch(r"goto:[0-9A-Za-z][0-9A-Za-z_-]{0,63}", value):
            return value
        raise ValueError("on_failure must be one of: stop, continue, ask_human, goto:<step_id>")


class PolicySpec(BaseModel):
    sandbox: bool = True
    network: NETWORK_POLICY = "deny"
    allowed_binaries: list[str] = Field(default_factory=list, description="Allowlist of executable binaries")
    requires_approval: bool = False
    # Future: allowed_tools per agent, allowed_paths, max_cost_usd, etc.


class JobSpec(BaseModel):
    schema_version: str = Field(default="1.0")
    job_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=utc_now_iso)
    source: JobSource = Field(default_factory=JobSource)
    goal: str = Field(..., min_length=1, max_length=5000)

    project_id: str | None = Field(default=None, description="Allowed project alias (for webhook/scheduled jobs)")
    workdir: str = Field(default=".", description="Working directory for execution (repo/workspace)")
    steps: list[StepSpec]
    policy: PolicySpec = Field(default_factory=PolicySpec)

    callback_url: str | None = Field(
        default=None,
        description="URL to POST job result to upon completion (event-driven notification)",
    )
    context_window: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Conversation history shared across steps",
    )
    context_strategy: Literal["full", "summarize", "sliding"] = Field(
        default="sliding",
        description="How context_window is maintained between steps",
    )

    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactPaths(BaseModel):
    # All paths are relative to artifacts/<job_id>/
    report_md: str
    patch_diff: str
    logs_txt: str
    result_json: str


RESULT_STATUS = Literal["success", "failed", "retryable", "timeout", "cancelled", "needs_human", "running"]
CHANGE_STATUS = Literal["changed", "no_changes"]


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Metrics(BaseModel):
    duration_ms: int = 0
    cost_usd: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None


class StepResult(BaseModel):
    schema_version: str = "1.0"
    kind: Literal["step"] = "step"

    job_id: str
    step_id: str
    agent: AGENT
    role: str

    status: RESULT_STATUS
    attempts: int = 1

    started_at: str
    finished_at: str

    summary: str
    change_status: CHANGE_STATUS | None = None
    artifacts: ArtifactPaths
    secrets_check: SECRETS_CHECK | None = None
    metrics: Metrics = Field(default_factory=Metrics)
    error: Optional[ErrorInfo] = None


class JobResult(BaseModel):
    schema_version: str = "1.0"
    kind: Literal["job"] = "job"

    job_id: str
    status: RESULT_STATUS

    started_at: str
    finished_at: str

    summary: str
    artifacts: ArtifactPaths
    secrets_check: SECRETS_CHECK | None = None

    steps: list[StepResult] = Field(default_factory=list)
    error: Optional[ErrorInfo] = None


def default_pipeline(goal: str) -> list[StepSpec]:
    """Default 3-step pipeline using all 3 agents."""
    return [
        StepSpec(
            step_id="01_plan",
            agent="opencode",
            role="planner",
            prompt=f"Сформируй план реализации для задачи:\n{goal}",
            timeout_sec=120,
            max_retries=1,
        ),
        StepSpec(
            step_id="02_implement",
            agent="codex",
            role="implementer",
            prompt=f"Реализуй задачу и подготовь патч:\n{goal}",
            timeout_sec=300,
            max_retries=1,
            input_artifacts=["steps/01_plan/report.md"],
        ),
        StepSpec(
            step_id="03_review",
            agent="claude",
            role="reviewer",
            prompt=f"Проведи review изменений и рисков по задаче:\n{goal}",
            timeout_sec=180,
            max_retries=1,
            input_artifacts=["steps/01_plan/report.md", "steps/02_implement/report.md", "steps/02_implement/patch.diff"],
        ),
    ]
