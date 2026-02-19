from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from croniter import croniter
from dotenv import load_dotenv

from orchestrator.config import Settings
from orchestrator.logging_utils import setup_logging
from orchestrator.models import JobSpec, default_pipeline, JobSource, StepSpec, PolicySpec
from fsqueue.file_queue import DuplicateJobError, FileQueue

log = logging.getLogger("scheduler")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _schedules_dir() -> Path:
    # You can put schedules here (git-tracked) or mount in production
    return _repo_root() / "schedules"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime) -> str:
    return dt.isoformat()


class CronScheduler:
    def __init__(self, queue: FileQueue, schedules_dir: Path):
        self.queue = queue
        self.schedules_dir = schedules_dir
        self.next_runs: dict[str, datetime] = {}

    def _compute_next(self, expr: str, base: datetime) -> datetime:
        it = croniter(expr, base)
        return it.get_next(datetime)

    def tick(self) -> None:
        self.schedules_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(self.schedules_dir.glob("*.json"))

        now = _now()

        for f in files:
            try:
                sched = _load_json(f)
            except Exception as e:
                log.error("Failed to read schedule %s: %s", f, e)
                continue

            if not sched.get("enabled", True):
                continue

            sched_id = str(sched.get("id") or f.stem)
            expr = str(sched.get("schedule") or "").strip()
            payload = sched.get("payload") or {}

            if not expr:
                log.warning("Schedule %s has no cron expression", sched_id)
                continue

            if sched_id not in self.next_runs:
                self.next_runs[sched_id] = self._compute_next(expr, now)
                log.info("Schedule %s next run at %s", sched_id, _utc_iso(self.next_runs[sched_id]))

            if now >= self.next_runs[sched_id]:
                # Fire
                goal = str(payload.get("goal") or f"Scheduled job {sched_id}")
                steps_payload = payload.get("steps")

                if steps_payload:
                    steps = [StepSpec.model_validate(s) for s in steps_payload]
                else:
                    steps = default_pipeline(goal)

                job = JobSpec(
                    goal=goal,
                    source=JobSource(type="cron", meta={"schedule_id": sched_id, "file": str(f)}),
                    steps=steps,
                    policy=PolicySpec(**(payload.get("policy") or {})),
                    project_id=(str(payload.get("project_id")).strip() if payload.get("project_id") is not None else None),
                    workdir=str(payload.get("workdir") or "."),
                    tags=list(payload.get("tags") or []),
                    metadata=dict(payload.get("metadata") or {}),
                )
                try:
                    enqueue_state = "awaiting_approval" if job.policy.requires_approval else "pending"
                    self.queue.enqueue(job.model_dump(), state=enqueue_state)
                    log.info("Enqueued scheduled job %s (job_id=%s)", sched_id, job.job_id)
                except DuplicateJobError:
                    log.warning("Skipping duplicate scheduled job %s (job_id=%s)", sched_id, job.job_id)

                # Compute next run
                self.next_runs[sched_id] = self._compute_next(expr, now)
                log.info("Schedule %s next run at %s", sched_id, _utc_iso(self.next_runs[sched_id]))


def main() -> None:
    load_dotenv()
    settings = Settings.load()
    setup_logging(settings.log_level, json_output=settings.log_json)

    q = FileQueue(settings.queue_root)
    sdir = _schedules_dir()
    scheduler = CronScheduler(q, sdir)

    log.info("Scheduler started. Watching %s", sdir)

    while True:
        try:
            scheduler.tick()
        except Exception as e:
            log.exception("Scheduler tick error: %s", e)
        time.sleep(1)


if __name__ == "__main__":
    main()
