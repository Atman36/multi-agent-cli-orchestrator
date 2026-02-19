from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from fsqueue.file_queue import DuplicateJobError, FileQueue
from fsqueue.file_queue import ClaimedJob


class FileQueueTests(unittest.TestCase):
    def test_enqueue_rejects_duplicate_job_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            q = FileQueue(Path(td))
            q.enqueue({"job_id": "job-1", "goal": "a"})
            with self.assertRaises(DuplicateJobError):
                q.enqueue({"job_id": "job-1", "goal": "b"})

    def test_claim_reads_job_id_from_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            q = FileQueue(Path(td))
            custom_file = q.pending / "job-1.recovered.json"
            custom_file.write_text(json.dumps({"job_id": "job-1", "goal": "x"}), encoding="utf-8")
            claimed = q.claim()
            self.assertEqual(claimed.job_id, "job-1")

    def test_reclaim_stale_running_moves_back_to_pending(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            q = FileQueue(Path(td))
            running_file = q.running / "job-2.json"
            running_file.write_text(json.dumps({"job_id": "job-2", "goal": "x"}), encoding="utf-8")
            old_ts = time.time() - 3600
            # Simulate stale "running" entry.
            os.utime(running_file, (old_ts, old_ts))

            reclaimed = q.reclaim_stale_running(60)
            self.assertEqual(reclaimed, 1)
            self.assertFalse(running_file.exists())
            self.assertTrue((q.pending / "job-2.json").exists())

    def test_enqueue_allows_non_colliding_prefix_job_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            q = FileQueue(Path(td))
            q.enqueue({"job_id": "job-1", "goal": "a"})
            q.enqueue({"job_id": "job-12", "goal": "b"})
            self.assertEqual(q.queue_state("job-1"), "pending")
            self.assertEqual(q.queue_state("job-12"), "pending")

    def test_approve_moves_job_from_awaiting_to_pending(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            q = FileQueue(Path(td))
            q.enqueue({"job_id": "job-approve-1", "goal": "x"}, state="awaiting_approval")

            self.assertEqual(q.queue_state("job-approve-1"), "awaiting_approval")
            approved = q.approve("job-approve-1")
            self.assertTrue(approved)
            self.assertEqual(q.queue_state("job-approve-1"), "pending")

    def test_approve_uses_exact_job_id_not_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            q = FileQueue(Path(td))
            q.enqueue({"job_id": "job-1", "goal": "x"}, state="awaiting_approval")
            q.enqueue({"job_id": "job-12", "goal": "y"}, state="awaiting_approval")

            approved = q.approve("job-1")
            self.assertTrue(approved)
            self.assertEqual(q.queue_state("job-1"), "pending")
            self.assertEqual(q.queue_state("job-12"), "awaiting_approval")

    def test_unlock_moves_running_job_to_failed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            q = FileQueue(Path(td))
            running_file = q.running / "job-unlock-1.json"
            running_file.write_text(json.dumps({"job_id": "job-unlock-1", "goal": "x"}), encoding="utf-8")

            unlocked = q.unlock("job-unlock-1")
            self.assertTrue(unlocked)
            self.assertEqual(q.queue_state("job-unlock-1"), "failed")

    def test_unlock_uses_exact_job_id_not_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            q = FileQueue(Path(td))
            (q.running / "job-1.json").write_text(json.dumps({"job_id": "job-1", "goal": "x"}), encoding="utf-8")
            (q.running / "job-12.json").write_text(json.dumps({"job_id": "job-12", "goal": "y"}), encoding="utf-8")

            unlocked = q.unlock("job-1")
            self.assertTrue(unlocked)
            self.assertEqual(q.queue_state("job-1"), "failed")
            self.assertEqual(q.queue_state("job-12"), "running")

    def test_await_approval_moves_claimed_job_to_awaiting(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            q = FileQueue(Path(td))
            running_file = q.running / "job-await-1.json"
            running_file.write_text(json.dumps({"job_id": "job-await-1", "goal": "x"}), encoding="utf-8")
            claimed = ClaimedJob(job_id="job-await-1", path=running_file)

            q.await_approval(claimed)
            self.assertEqual(q.queue_state("job-await-1"), "awaiting_approval")


if __name__ == "__main__":
    unittest.main()
