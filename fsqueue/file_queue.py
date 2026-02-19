from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class QueueEmpty(Exception):
    pass


class DuplicateJobError(ValueError):
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

    def _job_exists_anywhere(self, job_id: str) -> bool:
        for folder in [self.pending, self.running, self.done, self.failed]:
            if any(folder.glob(f"{job_id}*.json")):
                return True
        return False

    def _job_id_from_path(self, path: Path) -> str:
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            value = str(obj.get("job_id") or obj.get("id") or "").strip()
            if value:
                return value
        except Exception:
            pass
        # Backward-compatible fallback for legacy filenames.
        return path.stem.split(".", 1)[0]

    def _move_to_dir_no_overwrite(self, src: Path, target_dir: Path) -> Path:
        base_name = src.name
        target = target_dir / base_name
        if not target.exists():
            os.replace(src, target)
            return target

        # Keep original content; only filename gains a suffix.
        while True:
            suffix = time.time_ns()
            alt = target_dir / f"{src.stem}.{suffix}.json"
            if not alt.exists():
                os.replace(src, alt)
                return alt

    def enqueue(self, job_obj: dict[str, Any]) -> str:
        job_id = str(job_obj.get("job_id") or job_obj.get("id") or "")
        if not job_id:
            raise ValueError("Job object missing job_id")
        if self._job_exists_anywhere(job_id):
            raise DuplicateJobError(f"Job with job_id='{job_id}' already exists")

        tmp = self.pending / f".{job_id}.{int(time.time()*1000)}.tmp"
        final = self.pending / f"{job_id}.json"
        tmp.write_text(json.dumps(job_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, final)
        return job_id

    def claim(self) -> ClaimedJob:
        files = sorted(self.pending.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for f in files:
            target = self.running / f.name
            try:
                os.replace(f, target)  # atomic on same filesystem
                return ClaimedJob(job_id=self._job_id_from_path(target), path=target)
            except FileNotFoundError:
                continue
            except PermissionError:
                continue
        raise QueueEmpty()

    def read_claimed(self, claimed: ClaimedJob) -> dict[str, Any]:
        return json.loads(claimed.path.read_text(encoding="utf-8"))

    def ack(self, claimed: ClaimedJob) -> None:
        self._move_to_dir_no_overwrite(claimed.path, self.done)

    def fail(self, claimed: ClaimedJob) -> None:
        self._move_to_dir_no_overwrite(claimed.path, self.failed)

    def requeue(self, claimed: ClaimedJob) -> None:
        self._move_to_dir_no_overwrite(claimed.path, self.pending)

    def reclaim_stale_running(self, stale_after_sec: int) -> int:
        now = time.time()
        reclaimed = 0
        files = sorted(self.running.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for f in files:
            try:
                age = now - f.stat().st_mtime
            except FileNotFoundError:
                continue
            if age < stale_after_sec:
                continue
            try:
                self._move_to_dir_no_overwrite(f, self.pending)
                reclaimed += 1
            except FileNotFoundError:
                continue
        return reclaimed
