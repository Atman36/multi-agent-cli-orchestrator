from __future__ import annotations

from dataclasses import dataclass, replace
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

    def for_job(
        self,
        *,
        job_sandbox: bool | None,
        job_network_policy: str | None,
        job_allowed_binaries: Sequence[str] | None,
    ) -> "ExecutionPolicy":
        sandbox = self.sandbox if job_sandbox is None else (self.sandbox and job_sandbox)

        requested_network = (job_network_policy or self.network_policy).strip().lower()
        if requested_network not in {"allow", "deny"}:
            raise PolicyError(f"Unsupported network policy: '{requested_network}'")
        network_policy = "deny" if "deny" in {self.network_policy, requested_network} else "allow"

        allowed_binaries = set(self.allowed_binaries)
        if job_allowed_binaries:
            allowed_binaries &= {b.strip() for b in job_allowed_binaries if b.strip()}
        # Sandbox wrapper must stay in allowlist even after intersection.
        if sandbox and self.sandbox_wrapper:
            allowed_binaries.add(self.sandbox_wrapper)

        return replace(
            self,
            sandbox=sandbox,
            network_policy=network_policy,
            allowed_binaries=allowed_binaries,
        )

    def assert_real_cli_safe(self) -> None:
        if self.network_policy == "deny" and (not self.sandbox or not self.sandbox_wrapper):
            raise PolicyError(
                "Network policy 'deny' requires SANDBOX=1 and SANDBOX_WRAPPER to enforce isolation "
                "for real CLI execution."
            )

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
    normalized_network_policy = (network_policy or "deny").strip().lower()
    if normalized_network_policy not in {"allow", "deny"}:
        raise PolicyError(f"Unsupported NETWORK_POLICY value: '{network_policy}'")
    return ExecutionPolicy(
        allowed_binaries=allowed_binaries,
        sandbox=sandbox,
        sandbox_wrapper=sandbox_wrapper,
        sandbox_wrapper_args=sandbox_wrapper_args,
        network_policy=normalized_network_policy,
    )


def assert_startup_policy_safe(*, enable_real_cli: bool, policy: ExecutionPolicy) -> None:
    if not enable_real_cli:
        return
    policy.assert_real_cli_safe()
