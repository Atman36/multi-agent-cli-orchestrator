from __future__ import annotations

from orchestrator.models import JobSpec
from workers import get_worker


def required_binaries_for_job(job: JobSpec) -> set[str]:
    required: set[str] = set()
    for step in job.steps:
        worker = get_worker(step.agent)
        if not worker:
            continue
        required.update(worker.required_binaries(step))
    return required
