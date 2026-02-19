from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from orchestrator.config import Settings
from orchestrator.logging_utils import setup_logging
from orchestrator.models import JobSpec, JobSource, default_pipeline, StepSpec, PolicySpec
from fsqueue.file_queue import FileQueue


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
            workdir=str(job_obj.get("workdir") or "."),
            tags=list(job_obj.get("tags") or []),
            metadata=dict(job_obj.get("metadata") or {}),
        )

    q.enqueue(job.model_dump())
    print(job.job_id)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    settings = Settings.load()
    job_dir = settings.artifacts_root / args.job_id
    state = (job_dir / "state.json").read_text(encoding="utf-8") if (job_dir / "state.json").exists() else None
    result = (job_dir / "result.json").read_text(encoding="utf-8") if (job_dir / "result.json").exists() else None

    print(json.dumps({"job_id": args.job_id, "job_dir": str(job_dir), "state": state, "result": result}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    load_dotenv()
    settings = Settings.load()
    setup_logging(settings.log_level)

    parser = argparse.ArgumentParser(prog="orchestrator-cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_submit = sub.add_parser("submit", help="Submit a job JSON file to the file queue")
    p_submit.add_argument("path")
    p_submit.set_defaults(func=cmd_submit)

    p_status = sub.add_parser("status", help="Print job status/result from artifacts directory")
    p_status.add_argument("job_id")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
