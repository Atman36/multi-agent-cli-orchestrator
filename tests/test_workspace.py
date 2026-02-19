from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.workspace import WorkspaceManager, WorkspaceError


class WorkspaceManagerTests(unittest.TestCase):
    def test_prepare_workspace_without_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspaces"
            mgr = WorkspaceManager(root, {})
            layout = mgr.prepare_workspace(job_id="job12345678", source_hint=None)
            self.assertTrue(layout.workdir.exists())
            self.assertTrue(str(layout.workdir).startswith(str(root.resolve())))

    def test_prepare_workspace_copies_source_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspaces"
            src = Path(td) / "src"
            src.mkdir(parents=True, exist_ok=True)
            (src / "a.txt").write_text("hello", encoding="utf-8")

            mgr = WorkspaceManager(root, {"demo": src})
            source = mgr.resolve_project_alias("demo")
            layout = mgr.prepare_workspace(job_id="job12345679", source_hint=source)
            self.assertEqual((layout.workdir / "a.txt").read_text(encoding="utf-8"), "hello")

    def test_resolve_unknown_alias_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            mgr = WorkspaceManager(Path(td) / "workspaces", {})
            with self.assertRaises(WorkspaceError):
                mgr.resolve_project_alias("unknown")


if __name__ == "__main__":
    unittest.main()
