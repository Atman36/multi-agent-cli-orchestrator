from __future__ import annotations

import hmac
import logging
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

from orchestrator.config import Settings
from orchestrator.logging_utils import setup_logging
from orchestrator.models import JobSpec, JobSource, default_pipeline, StepSpec, PolicySpec
from fsqueue.file_queue import FileQueue

log = logging.getLogger("webhook")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


app = FastAPI(title="Multi-Agent CLI Orchestrator", version="0.1.0")

settings: Settings | None = None
queue: FileQueue | None = None


@app.on_event("startup")
def _startup() -> None:
    global settings, queue
    load_dotenv()
    settings = Settings.load()
    setup_logging(settings.log_level)
    queue = FileQueue(settings.queue_root)
    log.info("Webhook server started")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.post("/webhook")
async def webhook(request: Request, authorization: Optional[str] = Header(default=None)) -> JSONResponse:
    assert settings is not None
    assert queue is not None

    # Auth: Authorization: Bearer <token>
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer <token>")

    token = authorization.split(" ", 1)[1].strip()
    if not constant_time_equal(token, settings.webhook_token):
        raise HTTPException(status_code=403, detail="Invalid token")

    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    goal = str(payload.get("goal") or "").strip()
    if not goal:
        raise HTTPException(status_code=400, detail="Missing 'goal'")

    workdir = str(payload.get("workdir") or ".")
    steps_payload = payload.get("steps")
    policy_payload = payload.get("policy") or {}
    tags = list(payload.get("tags") or [])
    metadata = dict(payload.get("metadata") or {})

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

    job = JobSpec(
        goal=goal,
        source=JobSource(type="webhook", meta={"remote": request.client.host if request.client else None}),
        steps=steps,
        policy=policy,
        workdir=workdir,
        tags=tags,
        metadata=metadata,
    )

    job_id = queue.enqueue(job.model_dump())
    return JSONResponse(
        {
            "status": "queued",
            "job_id": job_id,
            "artifacts_dir": str((settings.artifacts_root / job_id)),
            "status_url": f"/jobs/{job_id}",
        }
    )


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    assert settings is not None
    job_dir = settings.artifacts_root / job_id
    state_path = job_dir / "state.json"
    result_path = job_dir / "result.json"

    state = None
    result = None

    if state_path.exists():
        state = state_path.read_text(encoding="utf-8")
    if result_path.exists():
        result = result_path.read_text(encoding="utf-8")

    return {
        "job_id": job_id,
        "state_json": state,
        "result_json": result,
        "job_dir": str(job_dir.resolve()),
    }


def main() -> None:
    # NOTE: host/port intentionally fixed for MVP
    uvicorn.run("gateway.webhook_server:app", host="127.0.0.1", port=8080, reload=False)


if __name__ == "__main__":
    main()
