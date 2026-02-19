from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RetentionStats:
    removed_artifacts: int = 0
    removed_workspaces: int = 0


def _is_within(base: Path, target: Path) -> bool:
    return target == base or base in target.parents


def active_job_ids(queue_root: Path) -> set[str]:
    out: set[str] = set()
    for state in ("pending", "running"):
        d = queue_root / state
        if not d.exists():
            continue
        for p in d.glob("*.json"):
            out.add(p.stem.split(".", 1)[0])
    return out


def _cleanup_root(root: Path, ttl_sec: int, protected_job_ids: set[str]) -> int:
    if ttl_sec <= 0 or not root.exists():
        return 0

    now = time.time()
    removed = 0
    root_resolved = root.resolve()
    for item in root.iterdir():
        if not item.exists() or not item.is_dir():
            continue
        if item.name in protected_job_ids:
            continue
        if item.is_symlink():
            continue
        resolved = item.resolve()
        if not _is_within(root_resolved, resolved):
            continue
        try:
            age_sec = now - item.stat().st_mtime
        except FileNotFoundError:
            continue
        if age_sec < ttl_sec:
            continue
        shutil.rmtree(item, ignore_errors=True)
        removed += 1
    return removed


def run_retention(
    *,
    queue_root: Path,
    artifacts_root: Path,
    workspaces_root: Path,
    artifacts_ttl_sec: int,
    workspaces_ttl_sec: int,
) -> RetentionStats:
    protected = active_job_ids(queue_root)
    removed_artifacts = _cleanup_root(artifacts_root, artifacts_ttl_sec, protected)
    removed_workspaces = _cleanup_root(workspaces_root, workspaces_ttl_sec, protected)
    return RetentionStats(
        removed_artifacts=removed_artifacts,
        removed_workspaces=removed_workspaces,
    )
