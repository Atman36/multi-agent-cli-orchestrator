from __future__ import annotations

import unittest

from orchestrator.policy import (
    ExecutionPolicy,
    PolicyError,
    assert_startup_policy_safe,
)


class RunnerStartupPolicyTests(unittest.TestCase):
    def test_skips_real_cli_policy_check_when_disabled(self) -> None:
        policy = ExecutionPolicy(
            allowed_binaries={"codex", "git"},
            sandbox=False,
            sandbox_wrapper=None,
            sandbox_wrapper_args=[],
            network_policy="deny",
        )
        assert_startup_policy_safe(enable_real_cli=False, policy=policy)

    def test_raises_for_unsafe_real_cli_configuration(self) -> None:
        policy = ExecutionPolicy(
            allowed_binaries={"codex", "git"},
            sandbox=False,
            sandbox_wrapper=None,
            sandbox_wrapper_args=[],
            network_policy="deny",
        )
        with self.assertRaises(PolicyError):
            assert_startup_policy_safe(enable_real_cli=True, policy=policy)

    def test_allows_safe_real_cli_configuration(self) -> None:
        policy = ExecutionPolicy(
            allowed_binaries={"codex", "git", "bwrap"},
            sandbox=True,
            sandbox_wrapper="bwrap",
            sandbox_wrapper_args=["--unshare-net"],
            network_policy="deny",
        )
        assert_startup_policy_safe(enable_real_cli=True, policy=policy)


if __name__ == "__main__":
    unittest.main()
