from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.subprocess_utils import run_command


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _env_map(stdout: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        pairs[key] = value
    return pairs


class SubprocessEnvTests(unittest.IsolatedAsyncioTestCase):
    async def test_allowlisted_variable_is_passed(self) -> None:
        with patch.dict(os.environ, {"MY_ALLOWED": "present"}, clear=False):
            result = await run_command(
                ["/usr/bin/env"],
                cwd=_repo_root(),
                env={},
                env_allowlist=["MY_ALLOWED"],
                clear_env=False,
                timeout_sec=5,
            )
        self.assertEqual(result.exit_code, 0)
        env_out = _env_map(result.stdout)
        self.assertEqual(env_out.get("MY_ALLOWED"), "present")
        self.assertIn("PATH", env_out)

    async def test_non_allowlisted_override_is_ignored(self) -> None:
        result = await run_command(
            ["/usr/bin/env"],
            cwd=_repo_root(),
            env={"NOT_ALLOWED": "1"},
            env_allowlist=[],
            clear_env=False,
            timeout_sec=5,
        )
        self.assertEqual(result.exit_code, 0)
        env_out = _env_map(result.stdout)
        self.assertNotIn("NOT_ALLOWED", env_out)

    async def test_clear_env_mode_reduces_base_environment(self) -> None:
        result = await run_command(
            ["/usr/bin/env"],
            cwd=_repo_root(),
            env={},
            env_allowlist=[],
            clear_env=True,
            timeout_sec=5,
        )
        self.assertEqual(result.exit_code, 0)
        env_out = _env_map(result.stdout)
        self.assertIn("PATH", env_out)
        self.assertNotIn("HOME", env_out)
        self.assertNotIn("TMPDIR", env_out)

    async def test_output_is_truncated_when_limit_is_reached(self) -> None:
        result = await run_command(
            [sys.executable, "-c", "import sys; sys.stdout.write('A'*120); sys.stderr.write('B'*120)"],
            cwd=_repo_root(),
            env={},
            env_allowlist=[],
            clear_env=False,
            timeout_sec=5,
            max_output_chars=50,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertTrue(result.stdout_truncated)
        self.assertTrue(result.stderr_truncated)
        self.assertIn("A" * 50, result.stdout)
        self.assertIn("B" * 50, result.stderr)
        self.assertIn("[truncated: output exceeded 50 chars]", result.stdout)
        self.assertIn("[truncated: output exceeded 50 chars]", result.stderr)

    async def test_returncode_none_maps_to_negative_one(self) -> None:
        def _stream(data: bytes) -> asyncio.StreamReader:
            stream = asyncio.StreamReader()
            stream.feed_data(data)
            stream.feed_eof()
            return stream

        class _FakeProc:
            def __init__(self) -> None:
                self.returncode = None
                self.pid = os.getpid()
                self.stdout = _stream(b"hello\n")
                self.stderr = _stream(b"")

            async def wait(self) -> int:
                return 0

            def send_signal(self, _sig: int) -> None:
                return None

            def kill(self) -> None:
                return None

        async def _fake_create_subprocess_exec(*_args, **_kwargs) -> _FakeProc:
            return _FakeProc()

        with patch("orchestrator.subprocess_utils.asyncio.create_subprocess_exec", side_effect=_fake_create_subprocess_exec):
            result = await run_command(
                ["/usr/bin/env"],
                cwd=_repo_root(),
                env={},
                env_allowlist=[],
                clear_env=False,
                timeout_sec=5,
            )
        self.assertEqual(result.exit_code, -1)
        self.assertEqual(result.stdout, "hello\n")


if __name__ == "__main__":
    unittest.main()
