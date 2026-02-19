from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from fsqueue.file_queue import DuplicateJobError, FileQueue


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
            self.assertTrue(any(q.pending.glob("job-2*.json")))

    def test_approve_moves_job_from_awaiting_to_pending(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            q = FileQueue(Path(td))
            q.enqueue({"job_id": "job-approve-1", "goal": "x"}, state="awaiting_approval")

            self.assertEqual(q.queue_state("job-approve-1"), "awaiting_approval")
            approved = q.approve("job-approve-1")
            self.assertTrue(approved)
            self.assertEqual(q.queue_state("job-approve-1"), "pending")

    def test_unlock_moves_running_job_to_failed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            q = FileQueue(Path(td))
            running_file = q.running / "job-unlock-1.json"
            running_file.write_text(json.dumps({"job_id": "job-unlock-1", "goal": "x"}), encoding="utf-8")

            unlocked = q.unlock("job-unlock-1")
            self.assertTrue(unlocked)
            self.assertEqual(q.queue_state("job-unlock-1"), "failed")


if __name__ == "__main__":
    unittest.main()
