from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class ArtifactStore:
    """Filesystem-backed artifact store with fixed paths.

    Layout:
      artifacts/<job_id>/
        job.json
        state.json
        result.json
        report.md
        patch.diff
        logs.txt
        orchestrator.log
        steps/<step_id>/
          result.json
          report.md
          patch.diff
          logs.txt
          raw_stdout.txt
          raw_stderr.txt
    """

    def __init__(self, artifacts_root: Path):
        self.artifacts_root = artifacts_root

    def job_dir(self, job_id: str) -> Path:
        p = (self.artifacts_root / job_id).resolve()
        # Safety: ensure job dir is within artifacts root
        if self.artifacts_root not in p.parents and p != self.artifacts_root:
            raise ValueError("Invalid job_id caused path traversal")
        return p

    def step_dir(self, job_id: str, step_id: str) -> Path:
        p = (self.job_dir(job_id) / "steps" / step_id).resolve()
        if self.job_dir(job_id) not in p.parents:
            raise ValueError("Invalid step_id caused path traversal")
        return p

    def ensure_job_layout(self, job_id: str) -> None:
        jd = self.job_dir(job_id)
        (jd / "steps").mkdir(parents=True, exist_ok=True)

    def ensure_step_layout(self, job_id: str, step_id: str) -> None:
        sd = self.step_dir(job_id, step_id)
        sd.mkdir(parents=True, exist_ok=True)

    def _atomic_write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as tf:
            tf.write(text)
            tmp = tf.name
        os.replace(tmp, path)

    def _atomic_write_json(self, path: Path, obj: Any) -> None:
        self._atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")

    def write_job_spec(self, job_id: str, job_obj: dict[str, Any]) -> None:
        self._atomic_write_json(self.job_dir(job_id) / "job.json", job_obj)

    def write_state(self, job_id: str, state_obj: dict[str, Any]) -> None:
        self._atomic_write_json(self.job_dir(job_id) / "state.json", state_obj)

    def write_context(self, job_id: str, context_obj: dict[str, Any]) -> None:
        self._atomic_write_json(self.job_dir(job_id) / "context.json", context_obj)

    def write_job_artifacts(self, job_id: str, *, report_md: str, patch_diff: str, logs_txt: str, result_obj: dict[str, Any]) -> None:
        jd = self.job_dir(job_id)
        self._atomic_write_text(jd / "report.md", report_md)
        self._atomic_write_text(jd / "patch.diff", patch_diff)
        self._atomic_write_text(jd / "logs.txt", logs_txt)
        self._atomic_write_json(jd / "result.json", result_obj)

    def write_step_artifacts(
        self,
        job_id: str,
        step_id: str,
        *,
        report_md: str,
        patch_diff: str,
        logs_txt: str,
        result_obj: dict[str, Any],
        raw_stdout: str = "",
        raw_stderr: str = "",
    ) -> None:
        sd = self.step_dir(job_id, step_id)
        self._atomic_write_text(sd / "report.md", report_md)
        self._atomic_write_text(sd / "patch.diff", patch_diff)
        self._atomic_write_text(sd / "logs.txt", logs_txt)
        self._atomic_write_json(sd / "result.json", result_obj)
        if raw_stdout:
            self._atomic_write_text(sd / "raw_stdout.txt", raw_stdout)
        if raw_stderr:
            self._atomic_write_text(sd / "raw_stderr.txt", raw_stderr)

    def relpath(self, path: Path, job_id: str) -> str:
        """Return path relative to artifacts/<job_id>/"""
        jd = self.job_dir(job_id)
        return str(path.resolve().relative_to(jd))
