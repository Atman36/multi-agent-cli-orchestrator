from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - optional in bare test env
    TestClient = None  # type: ignore[assignment]

try:
    from gateway import webhook_server
except ModuleNotFoundError:  # pragma: no cover - optional in bare test env
    webhook_server = None  # type: ignore[assignment]


@unittest.skipIf(TestClient is None or webhook_server is None, "web dependencies are not installed")
class WebhookServerTests(unittest.TestCase):
    def test_webhook_rejects_large_payload(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_root = Path(td) / "queue"
            artifacts_root = Path(td) / "artifacts"
            workspaces_root = Path(td) / "workspaces"
            env = {
                "WEBHOOK_TOKEN": "test-token",
                "QUEUE_ROOT": str(queue_root),
                "ARTIFACTS_ROOT": str(artifacts_root),
                "WORKSPACES_ROOT": str(workspaces_root),
                "MAX_WEBHOOK_BODY_BYTES": "64",
            }
            with patch.dict(os.environ, env, clear=False):
                webhook_server.settings = None
                webhook_server.queue = None
                with TestClient(webhook_server.app) as client:
                    payload = {"goal": "x" * 300}
                    resp = client.post(
                        "/webhook",
                        headers={"Authorization": "Bearer test-token"},
                        json=payload,
                    )
                    self.assertEqual(resp.status_code, 413)

    def test_jobs_endpoint_returns_structured_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_root = Path(td) / "queue"
            artifacts_root = Path(td) / "artifacts"
            workspaces_root = Path(td) / "workspaces"
            env = {
                "WEBHOOK_TOKEN": "test-token",
                "QUEUE_ROOT": str(queue_root),
                "ARTIFACTS_ROOT": str(artifacts_root),
                "WORKSPACES_ROOT": str(workspaces_root),
                "MAX_WEBHOOK_BODY_BYTES": "262144",
            }
            with patch.dict(os.environ, env, clear=False):
                webhook_server.settings = None
                webhook_server.queue = None
                with TestClient(webhook_server.app) as client:
                    create = client.post(
                        "/webhook",
                        headers={"Authorization": "Bearer test-token"},
                        json={"goal": "run tests"},
                    )
                    self.assertEqual(create.status_code, 200)
                    job_id = create.json()["job_id"]

                    job_dir = artifacts_root / job_id
                    job_dir.mkdir(parents=True, exist_ok=True)
                    (job_dir / "state.json").write_text(
                        json.dumps({"job_id": job_id, "status": "running"}),
                        encoding="utf-8",
                    )
                    (job_dir / "result.json").write_text(
                        json.dumps({"job_id": job_id, "status": "success"}),
                        encoding="utf-8",
                    )

                    status = client.get(f"/jobs/{job_id}")
                    self.assertEqual(status.status_code, 200)
                    payload = status.json()
                    self.assertEqual(payload["status"], "running")
                    self.assertIsInstance(payload["state"], dict)
                    self.assertIsInstance(payload["result"], dict)


if __name__ == "__main__":
    unittest.main()
