from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from orchestrator.config import Settings
from orchestrator.health import run_doctor_checks
from orchestrator.logging_utils import setup_logging
from orchestrator.models import JobSpec, JobSource, default_pipeline, StepSpec, PolicySpec
from orchestrator.runner import reclaim_stale_running_jobs
from fsqueue.file_queue import DuplicateJobError, FileQueue


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_obj_or_none(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def cmd_submit(args: argparse.Namespace) -> int:
    settings = Settings.load()
    q = FileQueue(settings.queue_root)

    path = Path(args.path)
    job_obj = _read_json(path)

    # Accept either a full JobSpec or a minimal payload {goal:..., ...}
    if "schema_version" in job_obj and "steps" in job_obj and "job_id" in job_obj:
        job = JobSpec.model_validate(job_obj)
    else:
        goal = str(job_obj.get("goal") or "").strip()
        if not goal:
            print("ERROR: job file must have 'goal' or be a full JobSpec", file=sys.stderr)
            return 2

        steps_payload = job_obj.get("steps")
        if steps_payload:
            steps = [StepSpec.model_validate(s) for s in steps_payload]
        else:
            steps = default_pipeline(goal)

        job = JobSpec(
            goal=goal,
            source=JobSource(type="manual", meta={"file": str(path)}),
            steps=steps,
            policy=PolicySpec(**(job_obj.get("policy") or {})),
            project_id=(str(job_obj.get("project_id")).strip() if job_obj.get("project_id") is not None else None),
            workdir=str(job_obj.get("workdir") or "."),
            tags=list(job_obj.get("tags") or []),
            metadata=dict(job_obj.get("metadata") or {}),
        )

    try:
        queue_state = "awaiting_approval" if job.policy.requires_approval else "pending"
        q.enqueue(job.model_dump(), state=queue_state)
    except DuplicateJobError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(job.job_id)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    settings = Settings.load()
    q = FileQueue(settings.queue_root)
    job_dir = settings.artifacts_root / args.job_id
    state = (job_dir / "state.json").read_text(encoding="utf-8") if (job_dir / "state.json").exists() else None
    result = (job_dir / "result.json").read_text(encoding="utf-8") if (job_dir / "result.json").exists() else None
    queue_state = q.queue_state(args.job_id)
    state_obj = _json_obj_or_none(state)
    status = (state_obj or {}).get("status") or queue_state or "unknown"

    print(
        json.dumps(
            {
                "job_id": args.job_id,
                "job_dir": str(job_dir),
                "status": status,
                "queue_state": queue_state,
                "state": state,
                "result": result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    settings = Settings.load()
    checks = run_doctor_checks(settings)
    has_fail = False
    for check in checks:
        if check.status == "FAIL":
            has_fail = True
        print(f"[{check.status}] {check.title}: {check.detail}")
    return 1 if has_fail else 0


def cmd_recover(args: argparse.Namespace) -> int:
    settings = Settings.load()
    q = FileQueue(settings.queue_root)
    stale_after_sec = int(args.stale_after_sec or settings.runner_reclaim_after_sec)
    reclaimed = reclaim_stale_running_jobs(q, stale_after_sec)
    print(json.dumps({"reclaimed": reclaimed, "stale_after_sec": stale_after_sec}, ensure_ascii=False))
    return 0


def cmd_unlock(args: argparse.Namespace) -> int:
    settings = Settings.load()
    q = FileQueue(settings.queue_root)
    unlocked = q.unlock(args.job_id)
    if not unlocked:
        print(f"ERROR: running job not found: {args.job_id}", file=sys.stderr)
        return 2
    print(json.dumps({"job_id": args.job_id, "status": "failed"}, ensure_ascii=False))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    settings = Settings.load()
    q = FileQueue(settings.queue_root)
    approved = q.approve(args.job_id)
    if not approved:
        print(f"ERROR: awaiting_approval job not found: {args.job_id}", file=sys.stderr)
        return 2
    print(json.dumps({"job_id": args.job_id, "status": "pending"}, ensure_ascii=False))
    return 0


def main() -> int:
    load_dotenv()
    settings = Settings.load()
    setup_logging(settings.log_level, json_output=settings.log_json)

    parser = argparse.ArgumentParser(prog="orchestrator-cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_submit = sub.add_parser("submit", help="Submit a job JSON file to the file queue")
    p_submit.add_argument("path")
    p_submit.set_defaults(func=cmd_submit)

    p_status = sub.add_parser("status", help="Print job status/result from artifacts directory")
    p_status.add_argument("job_id")
    p_status.set_defaults(func=cmd_status)

    p_doctor = sub.add_parser("doctor", help="Check local environment and runtime prerequisites")
    p_doctor.set_defaults(func=cmd_doctor)

    p_recover = sub.add_parser("recover", help="Move stale running jobs back to pending")
    p_recover.add_argument("--stale-after-sec", type=int, default=None)
    p_recover.set_defaults(func=cmd_recover)

    p_unlock = sub.add_parser("unlock", help="Force-move one running job to failed")
    p_unlock.add_argument("--job", dest="job_id", required=True)
    p_unlock.set_defaults(func=cmd_unlock)

    p_approve = sub.add_parser("approve", help="Move one awaiting_approval job to pending")
    p_approve.add_argument("--job", dest="job_id", required=True)
    p_approve.set_defaults(func=cmd_approve)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
