from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hmac
import json
import logging
import math
from pathlib import Path
from threading import Lock
import time
from typing import Any, Callable, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
import uvicorn

from orchestrator.config import Settings
from orchestrator.logging_utils import setup_logging
from orchestrator.metrics import render_prometheus_metrics
from orchestrator.models import JobSpec, JobSource, default_pipeline, StepSpec, PolicySpec
from fsqueue.file_queue import DuplicateJobError, FileQueue

log = logging.getLogger("webhook")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_sec: int = 0


class InMemoryRateLimiter:
    def __init__(self, *, window_sec: int, max_requests: int, now_fn: Callable[[], float] | None = None):
        self.window_sec = max(1, int(window_sec))
        self.max_requests = max(1, int(max_requests))
        self._now_fn = now_fn or time.monotonic
        self._lock = Lock()
        self._buckets: dict[str, deque[float]] = {}

    def check(self, key: str) -> RateLimitDecision:
        now = self._now_fn()
        cutoff = now - self.window_sec
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                retry_after = max(1, int(math.ceil((bucket[0] + self.window_sec) - now)))
                return RateLimitDecision(allowed=False, retry_after_sec=retry_after)
            bucket.append(now)
            return RateLimitDecision(allowed=True, retry_after_sec=0)


def _extract_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        first_hop = forwarded_for.split(",", 1)[0].strip()
        if first_hop:
            return first_hop
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _resolve_token_scopes(token: str, cfg: Settings) -> set[str] | None:
    if cfg.webhook_tokens:
        for candidate_token, scopes in cfg.webhook_tokens.items():
            if constant_time_equal(token, candidate_token):
                return scopes
        return None
    if constant_time_equal(token, cfg.webhook_token):
        return {"*"}
    return None


app = FastAPI(title="Multi-Agent CLI Orchestrator", version="0.1.0")

settings: Settings | None = None
queue: FileQueue | None = None
rate_limiter: InMemoryRateLimiter | None = None


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


@app.on_event("startup")
def _startup() -> None:
    global settings, queue, rate_limiter
    load_dotenv()
    settings = Settings.load()
    setup_logging(settings.log_level, json_output=settings.log_json)
    queue = FileQueue(settings.queue_root)
    if settings.webhook_rate_limit_max_requests > 0:
        rate_limiter = InMemoryRateLimiter(
            window_sec=settings.webhook_rate_limit_window_sec,
            max_requests=settings.webhook_rate_limit_max_requests,
        )
    else:
        rate_limiter = None
    log.info("Webhook server started")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    assert settings is not None
    body = render_prometheus_metrics(queue_root=settings.queue_root, artifacts_root=settings.artifacts_root)
    return PlainTextResponse(content=body, media_type="text/plain; version=0.0.4")


@app.post("/webhook")
async def webhook(request: Request, authorization: Optional[str] = Header(default=None)) -> JSONResponse:
    assert settings is not None
    assert queue is not None

    # Auth: Authorization: Bearer <token>
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer <token>")

    token = authorization.split(" ", 1)[1].strip()
    token_scopes = _resolve_token_scopes(token, settings)
    if token_scopes is None:
        raise HTTPException(status_code=403, detail="Invalid token")
    if rate_limiter is not None:
        rate_limit_key = f"{token}:{_extract_client_ip(request)}"
        decision = rate_limiter.check(rate_limit_key)
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(decision.retry_after_sec)},
            )

    body = await request.body()
    if len(body) > settings.max_webhook_body_bytes:
        raise HTTPException(status_code=413, detail=f"Payload too large (>{settings.max_webhook_body_bytes} bytes)")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    goal = str(payload.get("goal") or "").strip()
    if not goal:
        raise HTTPException(status_code=400, detail="Missing 'goal'")

    requested_workdir = payload.get("workdir")
    project_id_raw = payload.get("project_id")
    project_id = str(project_id_raw).strip() if project_id_raw is not None else None
    if project_id == "":
        project_id = None
    if project_id is not None and project_id not in settings.project_aliases:
        raise HTTPException(status_code=400, detail=f"Unknown project_id '{project_id}'")
    if "*" not in token_scopes:
        if project_id is None:
            raise HTTPException(status_code=403, detail="Token requires explicit project_id")
        if project_id not in token_scopes:
            raise HTTPException(status_code=403, detail=f"Token is not allowed for project_id '{project_id}'")

    callback_url = payload.get("callback_url")
    if callback_url is not None:
        callback_url = str(callback_url).strip()
        if not callback_url:
            callback_url = None

    steps_payload = payload.get("steps")
    policy_payload = payload.get("policy") or {}
    tags = list(payload.get("tags") or [])
    metadata = dict(payload.get("metadata") or {})
    context_window = payload.get("context_window", [])
    context_strategy = payload.get("context_strategy", "sliding")
    if requested_workdir is not None:
        metadata["ignored_workdir"] = str(requested_workdir)

    if steps_payload:
        try:
            steps = [StepSpec.model_validate(s) for s in steps_payload]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid steps: {e}")
    else:
        steps = default_pipeline(goal)

    try:
        policy = PolicySpec(**policy_payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid policy: {e}")

    try:
        job = JobSpec(
            goal=goal,
            source=JobSource(type="webhook", meta={"remote": request.client.host if request.client else None}),
            steps=steps,
            policy=policy,
            project_id=project_id,
            callback_url=callback_url,
            workdir=".",
            context_window=context_window,
            context_strategy=context_strategy,
            artifact_handoff=str(payload.get("artifact_handoff") or settings.default_artifact_handoff),
            tags=tags,
            metadata=metadata,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid job: {e}")

    try:
        enqueue_state = "awaiting_approval" if job.policy.requires_approval else "pending"
        job_id = queue.enqueue(job.model_dump(), state=enqueue_state)
    except DuplicateJobError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return JSONResponse(
        {
            "status": "awaiting_approval" if job.policy.requires_approval else "queued",
            "job_id": job_id,
            "artifacts_dir": str((settings.artifacts_root / job_id)),
            "status_url": f"/jobs/{job_id}",
        }
    )


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    assert settings is not None
    assert queue is not None
    job_dir = settings.artifacts_root / job_id
    state_path = job_dir / "state.json"
    result_path = job_dir / "result.json"

    state = _read_json_if_exists(state_path)
    result = _read_json_if_exists(result_path)
    queue_state = queue.queue_state(job_id)

    return {
        "job_id": job_id,
        "status": (state or {}).get("status") or queue_state or "queued",
        "queue_state": queue_state,
        "state": state,
        "result": result,
    }


def main() -> None:
    # NOTE: host/port intentionally fixed for MVP
    uvicorn.run("gateway.webhook_server:app", host="127.0.0.1", port=8080, reload=False)


if __name__ == "__main__":
    main()
