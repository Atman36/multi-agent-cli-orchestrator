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
      awaiting_approval/ - gated jobs that need manual approval
      running/  - claimed by a runner (atomic rename)
      done/     - completed successfully
      failed/   - failed (final)

    File format: one job per JSON file. Filename is <job_id>.json
    (or <job_id>.<suffix>.json in no-overwrite move collisions).
    """

    def __init__(self, root: Path):
        self.root = root
        self.pending = root / "pending"
        self.running = root / "running"
        self.done = root / "done"
        self.failed = root / "failed"
        self.awaiting_approval = root / "awaiting_approval"
        for p in [self.pending, self.running, self.done, self.failed, self.awaiting_approval]:
            p.mkdir(parents=True, exist_ok=True)

    def _find_job_files(self, folder: Path, job_id: str) -> list[Path]:
        files: list[Path] = []
        exact = folder / f"{job_id}.json"
        if exact.exists():
            files.append(exact)
        files.extend(folder.glob(f"{job_id}.*.json"))
        return sorted(files, key=lambda p: p.stat().st_mtime)

    def _job_exists_anywhere(self, job_id: str) -> bool:
        for folder in [self.pending, self.running, self.done, self.failed, self.awaiting_approval]:
            if self._find_job_files(folder, job_id):
                return True
        return False

    def _resolve_enqueue_dir(self, state: str) -> Path:
        if state == "pending":
            return self.pending
        if state == "awaiting_approval":
            return self.awaiting_approval
        raise ValueError(f"Unsupported queue state for enqueue: {state}")

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

    def enqueue(self, job_obj: dict[str, Any], *, state: str = "pending") -> str:
        job_id = str(job_obj.get("job_id") or job_obj.get("id") or "")
        if not job_id:
            raise ValueError("Job object missing job_id")
        if self._job_exists_anywhere(job_id):
            raise DuplicateJobError(f"Job with job_id='{job_id}' already exists")

        target_dir = self._resolve_enqueue_dir(state)
        tmp = target_dir / f".{job_id}.{int(time.time()*1000)}.tmp"
        final = target_dir / f"{job_id}.json"
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

    def await_approval(self, claimed: ClaimedJob) -> None:
        self._move_to_dir_no_overwrite(claimed.path, self.awaiting_approval)

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

    def _find_job_file(self, folder: Path, job_id: str) -> Path | None:
        files = self._find_job_files(folder, job_id)
        return files[0] if files else None

    def approve(self, job_id: str) -> bool:
        src = self._find_job_file(self.awaiting_approval, job_id)
        if src is None:
            return False
        self._move_to_dir_no_overwrite(src, self.pending)
        return True

    def unlock(self, job_id: str) -> bool:
        src = self._find_job_file(self.running, job_id)
        if src is None:
            return False
        self._move_to_dir_no_overwrite(src, self.failed)
        return True

    def queue_state(self, job_id: str) -> str | None:
        states = [
            ("pending", self.pending),
            ("running", self.running),
            ("done", self.done),
            ("failed", self.failed),
            ("awaiting_approval", self.awaiting_approval),
        ]
        for state, folder in states:
            if self._find_job_file(folder, job_id) is not None:
                return state
        return None
