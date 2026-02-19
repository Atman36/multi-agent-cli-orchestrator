from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(args: list[str], *, cwd: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def current_head_commit(cwd: str | Path) -> str | None:
    res = _run_git(["rev-parse", "HEAD"], cwd=cwd)
    if res.returncode != 0:
        return None
    commit = res.stdout.strip()
    return commit or None


def is_git_repo(cwd: str | Path) -> bool:
    res = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=cwd)
    if res.returncode != 0:
        return False
    return res.stdout.strip().lower() == "true"


def diff_since_commit(cwd: str | Path, base_commit: str | None) -> str:
    if base_commit:
        res = _run_git(["diff", base_commit], cwd=cwd)
    else:
        res = _run_git(["diff"], cwd=cwd)
    if res.returncode != 0:
        return ""
    return res.stdout
