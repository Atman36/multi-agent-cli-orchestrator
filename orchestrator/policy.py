from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class PolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionPolicy:
    allowed_binaries: set[str]
    sandbox: bool
    sandbox_wrapper: str | None
    sandbox_wrapper_args: list[str]
    network_policy: str  # "deny" | "allow" (enforced only via sandbox wrapper)

    def assert_binary_allowed(self, binary: str) -> None:
        if not self.allowed_binaries:
            raise PolicyError(
                "ALLOWED_BINARIES is empty. Refusing to execute any external commands."
            )
        if binary not in self.allowed_binaries:
            raise PolicyError(f"Binary '{binary}' is not in allowlist (ALLOWED_BINARIES).")

    def wrap_command(self, cmd: Sequence[str]) -> list[str]:
        """Optionally wrap a command into a sandbox.

        MVP note:
          - We do NOT implement sandboxing ourselves.
          - If SANDBOX=1 and SANDBOX_WRAPPER is not set, and real CLI execution is enabled,
            we refuse to run.
        """
        cmd = list(cmd)
        self.assert_binary_allowed(cmd[0])

        if self.sandbox:
            if not self.sandbox_wrapper:
                raise PolicyError(
                    "SANDBOX=1 but SANDBOX_WRAPPER is not set. "
                    "Refusing to execute real commands without an isolation wrapper."
                )
            # Wrapper must also be allowlisted
            self.assert_binary_allowed(self.sandbox_wrapper)
            return [self.sandbox_wrapper, *self.sandbox_wrapper_args, *cmd]

        return cmd


def build_policy_from_env(allowed_binaries: set[str], sandbox: bool, sandbox_wrapper: str | None, sandbox_wrapper_args: list[str], network_policy: str) -> ExecutionPolicy:
    return ExecutionPolicy(
        allowed_binaries=allowed_binaries,
        sandbox=sandbox,
        sandbox_wrapper=sandbox_wrapper,
        sandbox_wrapper_args=sandbox_wrapper_args,
        network_policy=network_policy,
    )
