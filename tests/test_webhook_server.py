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
                "WEBHOOK_TOKENS": "",
                "QUEUE_ROOT": str(queue_root),
                "ARTIFACTS_ROOT": str(artifacts_root),
                "WORKSPACES_ROOT": str(workspaces_root),
                "MAX_WEBHOOK_BODY_BYTES": "64",
            }
            with patch.dict(os.environ, env, clear=False):
                webhook_server.settings = None
                webhook_server.queue = None
                webhook_server.rate_limiter = None
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
                "WEBHOOK_TOKENS": "",
                "QUEUE_ROOT": str(queue_root),
                "ARTIFACTS_ROOT": str(artifacts_root),
                "WORKSPACES_ROOT": str(workspaces_root),
                "MAX_WEBHOOK_BODY_BYTES": "262144",
            }
            with patch.dict(os.environ, env, clear=False):
                webhook_server.settings = None
                webhook_server.queue = None
                webhook_server.rate_limiter = None
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

    def test_webhook_ignores_payload_workdir_and_keeps_project_alias(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_root = Path(td) / "queue"
            artifacts_root = Path(td) / "artifacts"
            workspaces_root = Path(td) / "workspaces"
            repo_root = Path(td) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)

            env = {
                "WEBHOOK_TOKEN": "test-token",
                "WEBHOOK_TOKENS": "",
                "QUEUE_ROOT": str(queue_root),
                "ARTIFACTS_ROOT": str(artifacts_root),
                "WORKSPACES_ROOT": str(workspaces_root),
                "PROJECT_ALIASES": f"demo={repo_root}",
            }
            with patch.dict(os.environ, env, clear=False):
                webhook_server.settings = None
                webhook_server.queue = None
                webhook_server.rate_limiter = None
                with TestClient(webhook_server.app) as client:
                    resp = client.post(
                        "/webhook",
                        headers={"Authorization": "Bearer test-token"},
                        json={"goal": "run tests", "project_id": "demo", "workdir": "/etc"},
                    )
                    self.assertEqual(resp.status_code, 200)
                    pending_files = list((queue_root / "pending").glob("*.json"))
                    self.assertEqual(len(pending_files), 1)
                    obj = json.loads(pending_files[0].read_text(encoding="utf-8"))
                    self.assertEqual(obj["workdir"], ".")
                    self.assertEqual(obj["project_id"], "demo")
                    self.assertEqual(obj["metadata"]["ignored_workdir"], "/etc")

    def test_webhook_rejects_unknown_project_alias(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_root = Path(td) / "queue"
            artifacts_root = Path(td) / "artifacts"
            workspaces_root = Path(td) / "workspaces"
            env = {
                "WEBHOOK_TOKEN": "test-token",
                "WEBHOOK_TOKENS": "",
                "QUEUE_ROOT": str(queue_root),
                "ARTIFACTS_ROOT": str(artifacts_root),
                "WORKSPACES_ROOT": str(workspaces_root),
                "PROJECT_ALIASES": "",
            }
            with patch.dict(os.environ, env, clear=False):
                webhook_server.settings = None
                webhook_server.queue = None
                webhook_server.rate_limiter = None
                with TestClient(webhook_server.app) as client:
                    resp = client.post(
                        "/webhook",
                        headers={"Authorization": "Bearer test-token"},
                        json={"goal": "run tests", "project_id": "missing"},
                    )
                    self.assertEqual(resp.status_code, 400)

    def test_webhook_routes_requires_approval_to_awaiting_queue(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_root = Path(td) / "queue"
            artifacts_root = Path(td) / "artifacts"
            workspaces_root = Path(td) / "workspaces"
            env = {
                "WEBHOOK_TOKEN": "test-token",
                "WEBHOOK_TOKENS": "",
                "QUEUE_ROOT": str(queue_root),
                "ARTIFACTS_ROOT": str(artifacts_root),
                "WORKSPACES_ROOT": str(workspaces_root),
            }
            with patch.dict(os.environ, env, clear=False):
                webhook_server.settings = None
                webhook_server.queue = None
                webhook_server.rate_limiter = None
                with TestClient(webhook_server.app) as client:
                    resp = client.post(
                        "/webhook",
                        headers={"Authorization": "Bearer test-token"},
                        json={"goal": "run tests", "policy": {"requires_approval": True}},
                    )
                    self.assertEqual(resp.status_code, 200)
                    self.assertEqual(resp.json()["status"], "awaiting_approval")
                    awaiting = list((queue_root / "awaiting_approval").glob("*.json"))
                    pending = list((queue_root / "pending").glob("*.json"))
                    self.assertEqual(len(awaiting), 1)
                    self.assertEqual(len(pending), 0)

    def test_webhook_accepts_context_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_root = Path(td) / "queue"
            artifacts_root = Path(td) / "artifacts"
            workspaces_root = Path(td) / "workspaces"
            env = {
                "WEBHOOK_TOKEN": "test-token",
                "WEBHOOK_TOKENS": "",
                "QUEUE_ROOT": str(queue_root),
                "ARTIFACTS_ROOT": str(artifacts_root),
                "WORKSPACES_ROOT": str(workspaces_root),
            }
            with patch.dict(os.environ, env, clear=False):
                webhook_server.settings = None
                webhook_server.queue = None
                webhook_server.rate_limiter = None
                with TestClient(webhook_server.app) as client:
                    resp = client.post(
                        "/webhook",
                        headers={"Authorization": "Bearer test-token"},
                        json={
                            "goal": "run tests",
                            "context_strategy": "sliding",
                            "context_window": [{"role": "user", "content": "hello"}],
                        },
                    )
                    self.assertEqual(resp.status_code, 200)
                    pending = list((queue_root / "pending").glob("*.json"))
                    self.assertEqual(len(pending), 1)
                    obj = json.loads(pending[0].read_text(encoding="utf-8"))
                    self.assertEqual(obj["context_strategy"], "sliding")
                    self.assertEqual(obj["context_window"][0]["content"], "hello")

    def test_webhook_scoped_tokens_enforce_project_access(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_root = Path(td) / "queue"
            artifacts_root = Path(td) / "artifacts"
            workspaces_root = Path(td) / "workspaces"
            demo_repo = Path(td) / "demo"
            tools_repo = Path(td) / "tools"
            demo_repo.mkdir(parents=True, exist_ok=True)
            tools_repo.mkdir(parents=True, exist_ok=True)

            env = {
                "WEBHOOK_TOKENS": "token-demo=demo,token-all=*",
                "QUEUE_ROOT": str(queue_root),
                "ARTIFACTS_ROOT": str(artifacts_root),
                "WORKSPACES_ROOT": str(workspaces_root),
                "PROJECT_ALIASES": f"demo={demo_repo},tools={tools_repo}",
            }
            with patch.dict(os.environ, env, clear=False):
                webhook_server.settings = None
                webhook_server.queue = None
                webhook_server.rate_limiter = None
                with TestClient(webhook_server.app) as client:
                    ok = client.post(
                        "/webhook",
                        headers={"Authorization": "Bearer token-demo"},
                        json={"goal": "run tests", "project_id": "demo"},
                    )
                    self.assertEqual(ok.status_code, 200)

                    denied = client.post(
                        "/webhook",
                        headers={"Authorization": "Bearer token-demo"},
                        json={"goal": "run tests", "project_id": "tools"},
                    )
                    self.assertEqual(denied.status_code, 403)

                    missing_project = client.post(
                        "/webhook",
                        headers={"Authorization": "Bearer token-demo"},
                        json={"goal": "run tests"},
                    )
                    self.assertEqual(missing_project.status_code, 403)

                    wildcard = client.post(
                        "/webhook",
                        headers={"Authorization": "Bearer token-all"},
                        json={"goal": "run tests", "project_id": "tools"},
                    )
                    self.assertEqual(wildcard.status_code, 200)

    def test_webhook_rate_limit_returns_429(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_root = Path(td) / "queue"
            artifacts_root = Path(td) / "artifacts"
            workspaces_root = Path(td) / "workspaces"
            env = {
                "WEBHOOK_TOKEN": "test-token",
                "WEBHOOK_TOKENS": "",
                "QUEUE_ROOT": str(queue_root),
                "ARTIFACTS_ROOT": str(artifacts_root),
                "WORKSPACES_ROOT": str(workspaces_root),
                "WEBHOOK_RATE_LIMIT_WINDOW_SEC": "60",
                "WEBHOOK_RATE_LIMIT_MAX_REQUESTS": "1",
            }
            with patch.dict(os.environ, env, clear=False):
                webhook_server.settings = None
                webhook_server.queue = None
                webhook_server.rate_limiter = None
                with TestClient(webhook_server.app) as client:
                    first = client.post(
                        "/webhook",
                        headers={"Authorization": "Bearer test-token"},
                        json={"goal": "run tests"},
                    )
                    self.assertEqual(first.status_code, 200)

                    second = client.post(
                        "/webhook",
                        headers={"Authorization": "Bearer test-token"},
                        json={"goal": "run tests again"},
                    )
                    self.assertEqual(second.status_code, 429)
                    self.assertIn("Retry-After", second.headers)

    def test_webhook_uses_default_artifact_handoff_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_root = Path(td) / "queue"
            artifacts_root = Path(td) / "artifacts"
            workspaces_root = Path(td) / "workspaces"
            env = {
                "WEBHOOK_TOKEN": "test-token",
                "WEBHOOK_TOKENS": "",
                "QUEUE_ROOT": str(queue_root),
                "ARTIFACTS_ROOT": str(artifacts_root),
                "WORKSPACES_ROOT": str(workspaces_root),
                "DEFAULT_ARTIFACT_HANDOFF": "patch_first",
            }
            with patch.dict(os.environ, env, clear=False):
                webhook_server.settings = None
                webhook_server.queue = None
                webhook_server.rate_limiter = None
                with TestClient(webhook_server.app) as client:
                    resp = client.post(
                        "/webhook",
                        headers={"Authorization": "Bearer test-token"},
                        json={"goal": "run tests"},
                    )
                    self.assertEqual(resp.status_code, 200)
                    pending_files = list((queue_root / "pending").glob("*.json"))
                    self.assertEqual(len(pending_files), 1)
                    job_obj = json.loads(pending_files[0].read_text(encoding="utf-8"))
                    self.assertEqual(job_obj["artifact_handoff"], "patch_first")

    def test_webhook_payload_can_override_artifact_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_root = Path(td) / "queue"
            artifacts_root = Path(td) / "artifacts"
            workspaces_root = Path(td) / "workspaces"
            env = {
                "WEBHOOK_TOKEN": "test-token",
                "WEBHOOK_TOKENS": "",
                "QUEUE_ROOT": str(queue_root),
                "ARTIFACTS_ROOT": str(artifacts_root),
                "WORKSPACES_ROOT": str(workspaces_root),
                "DEFAULT_ARTIFACT_HANDOFF": "manual",
            }
            with patch.dict(os.environ, env, clear=False):
                webhook_server.settings = None
                webhook_server.queue = None
                webhook_server.rate_limiter = None
                with TestClient(webhook_server.app) as client:
                    resp = client.post(
                        "/webhook",
                        headers={"Authorization": "Bearer test-token"},
                        json={"goal": "run tests", "artifact_handoff": "workspace_first"},
                    )
                    self.assertEqual(resp.status_code, 200)
                    pending_files = list((queue_root / "pending").glob("*.json"))
                    self.assertEqual(len(pending_files), 1)
                    job_obj = json.loads(pending_files[0].read_text(encoding="utf-8"))
                    self.assertEqual(job_obj["artifact_handoff"], "workspace_first")

    def test_metrics_endpoint_returns_prometheus_text(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_root = Path(td) / "queue"
            artifacts_root = Path(td) / "artifacts"
            workspaces_root = Path(td) / "workspaces"
            env = {
                "WEBHOOK_TOKEN": "test-token",
                "WEBHOOK_TOKENS": "",
                "QUEUE_ROOT": str(queue_root),
                "ARTIFACTS_ROOT": str(artifacts_root),
                "WORKSPACES_ROOT": str(workspaces_root),
            }
            with patch.dict(os.environ, env, clear=False):
                webhook_server.settings = None
                webhook_server.queue = None
                webhook_server.rate_limiter = None
                with TestClient(webhook_server.app) as client:
                    resp = client.get("/metrics")
                    self.assertEqual(resp.status_code, 200)
                    self.assertIn("orchestrator_queue_jobs", resp.text)


if __name__ == "__main__":
    unittest.main()
