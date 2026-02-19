from __future__ import annotations

import unittest

from orchestrator.policy import ExecutionPolicy, PolicyError, build_policy_from_env


class PolicyTests(unittest.TestCase):
    def test_real_cli_rejects_network_deny_without_enforced_sandbox(self) -> None:
        policy = ExecutionPolicy(
            allowed_binaries={"claude", "git"},
            sandbox=False,
            sandbox_wrapper=None,
            sandbox_wrapper_args=[],
            network_policy="deny",
        )
        with self.assertRaises(PolicyError):
            policy.assert_real_cli_safe()

    def test_real_cli_allows_network_deny_with_sandbox_wrapper(self) -> None:
        policy = ExecutionPolicy(
            allowed_binaries={"claude", "git", "bwrap"},
            sandbox=True,
            sandbox_wrapper="bwrap",
            sandbox_wrapper_args=["--unshare-net"],
            network_policy="deny",
        )
        policy.assert_real_cli_safe()

    def test_for_job_merges_network_policy_with_deny_precedence(self) -> None:
        base = ExecutionPolicy(
            allowed_binaries={"claude", "git", "bwrap"},
            sandbox=True,
            sandbox_wrapper="bwrap",
            sandbox_wrapper_args=[],
            network_policy="allow",
        )
        merged = base.for_job(
            job_sandbox=True,
            job_network_policy="deny",
            job_allowed_binaries=None,
        )
        self.assertEqual(merged.network_policy, "deny")

    def test_for_job_intersects_allowed_binaries_when_override_present(self) -> None:
        base = ExecutionPolicy(
            allowed_binaries={"claude", "git", "bwrap"},
            sandbox=True,
            sandbox_wrapper="bwrap",
            sandbox_wrapper_args=[],
            network_policy="allow",
        )
        merged = base.for_job(
            job_sandbox=True,
            job_network_policy="allow",
            job_allowed_binaries=["claude"],
        )
        # "claude" from intersection + "bwrap" preserved as sandbox wrapper.
        self.assertEqual(merged.allowed_binaries, {"claude", "bwrap"})

    def test_for_job_preserves_sandbox_wrapper_in_allowed_binaries(self) -> None:
        base = ExecutionPolicy(
            allowed_binaries={"claude", "git", "bwrap"},
            sandbox=True,
            sandbox_wrapper="bwrap",
            sandbox_wrapper_args=["--unshare-net"],
            network_policy="deny",
        )
        merged = base.for_job(
            job_sandbox=True,
            job_network_policy="deny",
            job_allowed_binaries=["claude"],
        )
        # Job only requested "claude", but bwrap must survive intersection.
        self.assertIn("bwrap", merged.allowed_binaries)
        self.assertIn("claude", merged.allowed_binaries)
        self.assertNotIn("git", merged.allowed_binaries)

    def test_build_policy_from_env_rejects_invalid_network_value(self) -> None:
        with self.assertRaises(PolicyError):
            build_policy_from_env(
                allowed_binaries={"claude"},
                sandbox=False,
                sandbox_wrapper=None,
                sandbox_wrapper_args=[],
                network_policy="blocked",
            )


if __name__ == "__main__":
    unittest.main()
