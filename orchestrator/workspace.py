from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(RuntimeError):
    pass


def _is_within(base: Path, target: Path) -> bool:
    return target == base or base in target.parents


def _assert_no_symlink_components(base: Path, target: Path) -> None:
    base_resolved = base.resolve()
    candidate = target if target.is_absolute() else (base_resolved / target)
    try:
        relative = candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise WorkspaceError(f"Path escapes WORKSPACES_ROOT: {target}") from exc

    cursor = base_resolved
    for part in relative.parts:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise WorkspaceError(f"Refusing symlink path component: {cursor}")


def _mkdir_secure(path: Path, mode: int = 0o750) -> None:
    old_umask = os.umask(0o027)
    try:
        path.mkdir(parents=True, exist_ok=True, mode=mode)
    finally:
        os.umask(old_umask)
    path.chmod(mode)


def _check_no_symlink_escape(base: Path, target: Path) -> None:
    base_resolved = base.resolve()
    _assert_no_symlink_components(base_resolved, target)

    candidate = target
    if candidate.exists() and candidate.is_symlink():
        raise WorkspaceError(f"Refusing symlink path: {candidate}")
    parent = candidate.parent
    if parent.exists() and parent.is_symlink():
        raise WorkspaceError(f"Refusing symlink parent: {parent}")
    resolved_parent = parent.resolve()
    if not _is_within(base_resolved, resolved_parent):
        raise WorkspaceError(f"Path escapes WORKSPACES_ROOT: {candidate}")


def _is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


@dataclass(frozen=True)
class WorkspaceLayout:
    root: Path
    workdir: Path


class WorkspaceManager:
    def __init__(self, workspaces_root: Path, project_aliases: dict[str, Path]):
        self.workspaces_root = workspaces_root.resolve()
        self.project_aliases = dict(project_aliases)
        _mkdir_secure(self.workspaces_root)

    def resolve_project_alias(self, project_id: str) -> Path:
        if project_id not in self.project_aliases:
            raise WorkspaceError(f"Unknown project_id '{project_id}'")
        path = self.project_aliases[project_id].resolve()
        if not path.exists() or not path.is_dir():
            raise WorkspaceError(f"Configured project path does not exist: {path}")
        return path

    def prepare_workspace(self, *, job_id: str, source_hint: str | Path | None) -> WorkspaceLayout:
        if not job_id or ".." in job_id or "/" in job_id or "\\" in job_id:
            raise WorkspaceError("Invalid job_id for workspace path")

        root = (self.workspaces_root / job_id)
        workdir = root / "work"

        _check_no_symlink_escape(self.workspaces_root, root)
        _mkdir_secure(root)
        _check_no_symlink_escape(self.workspaces_root, workdir)

        if source_hint is None:
            _mkdir_secure(workdir)
        else:
            src = Path(source_hint).expanduser().resolve()
            if not src.exists() or not src.is_dir():
                raise WorkspaceError(f"Source workdir does not exist: {src}")
            if workdir.exists():
                if not workdir.is_dir() or any(workdir.iterdir()):
                    raise WorkspaceError(f"Workspace already exists and is not empty: {workdir}")
            else:
                self._copy_source(src, workdir)

        final_workdir = workdir.resolve()
        if not _is_within(self.workspaces_root, final_workdir):
            raise WorkspaceError(f"Workspace escaped root: {final_workdir}")

        return WorkspaceLayout(root=root.resolve(), workdir=final_workdir)

    def _copy_source(self, src: Path, workdir: Path) -> None:
        if _is_git_repo(src):
            proc = subprocess.run(
                ["git", "clone", "--local", "--quiet", str(src), str(workdir)],
                check=False,
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                return
            raise WorkspaceError(f"Failed to clone git source: {proc.stderr.strip() or proc.stdout.strip()}")

        for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
            base = Path(dirpath)
            for dirname in dirnames:
                candidate = base / dirname
                if candidate.is_symlink():
                    raise WorkspaceError(f"Refusing source with symlink entry: {candidate}")
            for filename in filenames:
                candidate = base / filename
                if candidate.is_symlink():
                    raise WorkspaceError(f"Refusing source with symlink entry: {candidate}")

        shutil.copytree(src, workdir, symlinks=False)
