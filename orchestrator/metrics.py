from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _queue_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for p in path.glob("*.json") if p.is_file())


def render_prometheus_metrics(*, queue_root: Path, artifacts_root: Path) -> str:
    queue_states = ("pending", "running", "done", "failed", "awaiting_approval")
    queue_counts = {state: _queue_size(queue_root / state) for state in queue_states}

    job_status_counts: dict[str, int] = {}
    step_status_counts: dict[str, int] = {}
    duration_sum_ms = 0.0
    duration_count = 0

    if artifacts_root.exists():
        for job_dir in artifacts_root.iterdir():
            if not job_dir.is_dir():
                continue
            result_path = job_dir / "result.json"
            if not result_path.exists():
                continue
            try:
                result_obj = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            status = str(result_obj.get("status") or "unknown")
            job_status_counts[status] = job_status_counts.get(status, 0) + 1

            started = _parse_iso(result_obj.get("started_at"))
            finished = _parse_iso(result_obj.get("finished_at"))
            if started and finished and finished >= started:
                duration_sum_ms += (finished - started).total_seconds() * 1000.0
                duration_count += 1

            for step in result_obj.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                step_status = str(step.get("status") or "unknown")
                step_status_counts[step_status] = step_status_counts.get(step_status, 0) + 1

    lines = [
        "# HELP orchestrator_queue_jobs Number of queue entries by state.",
        "# TYPE orchestrator_queue_jobs gauge",
    ]
    for state in queue_states:
        lines.append(f'orchestrator_queue_jobs{{state="{state}"}} {queue_counts[state]}')

    lines.extend(
        [
            "# HELP orchestrator_jobs_total Number of finished jobs by final status.",
            "# TYPE orchestrator_jobs_total gauge",
        ]
    )
    if job_status_counts:
        for status, count in sorted(job_status_counts.items()):
            lines.append(f'orchestrator_jobs_total{{status="{status}"}} {count}')
    else:
        lines.append('orchestrator_jobs_total{status="none"} 0')

    lines.extend(
        [
            "# HELP orchestrator_steps_total Number of step results by status.",
            "# TYPE orchestrator_steps_total gauge",
        ]
    )
    if step_status_counts:
        for status, count in sorted(step_status_counts.items()):
            lines.append(f'orchestrator_steps_total{{status="{status}"}} {count}')
    else:
        lines.append('orchestrator_steps_total{status="none"} 0')

    lines.extend(
        [
            "# HELP orchestrator_job_duration_ms_sum Sum of job duration in milliseconds.",
            "# TYPE orchestrator_job_duration_ms_sum gauge",
            f"orchestrator_job_duration_ms_sum {duration_sum_ms:.0f}",
            "# HELP orchestrator_job_duration_ms_count Number of jobs with measurable duration.",
            "# TYPE orchestrator_job_duration_ms_count gauge",
            f"orchestrator_job_duration_ms_count {duration_count}",
        ]
    )

    return "\n".join(lines) + "\n"
