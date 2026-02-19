from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class QueueEmpty(Exception):
    pass


@dataclass
class ClaimedJob:
    job_id: str
    path: Path  # path in running/


class FileQueue:
    """Very small filesystem-backed queue.

    Directories (under QUEUE_ROOT):
      pending/  - new jobs
      running/  - claimed by a runner (atomic rename)
      done/     - completed successfully
      failed/   - failed (final)

    File format: one job per JSON file. Filename starts with <job_id>.
    """

    def __init__(self, root: Path):
        self.root = root
        self.pending = root / "pending"
        self.running = root / "running"
        self.done = root / "done"
        self.failed = root / "failed"
        for p in [self.pending, self.running, self.done, self.failed]:
            p.mkdir(parents=True, exist_ok=True)

    def enqueue(self, job_obj: dict[str, Any]) -> str:
        job_id = str(job_obj.get("job_id") or job_obj.get("id") or "")
        if not job_id:
            raise ValueError("Job object missing job_id")

        tmp = self.pending / f".{job_id}.{int(time.time()*1000)}.tmp"
        final = self.pending / f"{job_id}.json"
        tmp.write_text(json.dumps(job_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, final)
        return job_id

    def claim(self) -> ClaimedJob:
        files = sorted(self.pending.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for f in files:
            job_id = f.stem
            target = self.running / f.name
            try:
                os.replace(f, target)  # atomic on same filesystem
                return ClaimedJob(job_id=job_id, path=target)
            except FileNotFoundError:
                continue
            except PermissionError:
                continue
        raise QueueEmpty()

    def read_claimed(self, claimed: ClaimedJob) -> dict[str, Any]:
        return json.loads(claimed.path.read_text(encoding="utf-8"))

    def ack(self, claimed: ClaimedJob) -> None:
        target = self.done / claimed.path.name
        os.replace(claimed.path, target)

    def fail(self, claimed: ClaimedJob) -> None:
        target = self.failed / claimed.path.name
        os.replace(claimed.path, target)

    def requeue(self, claimed: ClaimedJob) -> None:
        target = self.pending / claimed.path.name
        os.replace(claimed.path, target)
