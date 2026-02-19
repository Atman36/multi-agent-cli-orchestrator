from __future__ import annotations

import os
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


if __name__ == "__main__":
    unittest.main()
