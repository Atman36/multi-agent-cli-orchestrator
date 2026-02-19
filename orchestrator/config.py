from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v is not None and v != "" else default


def _env_csv(name: str, default: str) -> set[str]:
    raw = os.getenv(name, default)
    return {item.strip() for item in raw.split(",") if item.strip()}


@dataclass(frozen=True)
class Settings:
    queue_root: Path
    artifacts_root: Path
    workspaces_root: Path

    webhook_token: str

    runner_poll_interval_sec: int
    runner_max_idle_sec: int
    runner_reclaim_after_sec: int

    enable_real_cli: bool

    sandbox: bool
    sandbox_wrapper: str | None
    sandbox_wrapper_args: list[str]

    allowed_binaries: set[str]
    network_policy: str

    env_allowlist: set[str]
    sensitive_env_vars: set[str]
    max_input_artifacts_chars: int
    max_webhook_body_bytes: int

    log_level: str

    @staticmethod
    def load() -> "Settings":
        queue_root = Path(_env_str("QUEUE_ROOT", "var/queue")).resolve()
        artifacts_root = Path(_env_str("ARTIFACTS_ROOT", "artifacts")).resolve()
        workspaces_root = Path(_env_str("WORKSPACES_ROOT", "workspaces")).resolve()

        webhook_token = _env_str("WEBHOOK_TOKEN", "dev-token")

        runner_poll_interval_sec = _env_int("RUNNER_POLL_INTERVAL_SEC", 1)
        runner_max_idle_sec = _env_int("RUNNER_MAX_IDLE_SEC", 120)
        runner_reclaim_after_sec = _env_int("RUNNER_RECLAIM_AFTER_SEC", 600)

        enable_real_cli = _env_bool("ENABLE_REAL_CLI", False)

        sandbox = _env_bool("SANDBOX", True)
        sandbox_wrapper = os.getenv("SANDBOX_WRAPPER") or None
        sandbox_wrapper_args = (os.getenv("SANDBOX_WRAPPER_ARGS") or "").split()
        sandbox_wrapper_args = [a for a in sandbox_wrapper_args if a.strip()]

        allowed_binaries = set(
            [b.strip() for b in (os.getenv("ALLOWED_BINARIES") or "").split(",") if b.strip()]
        )

        network_policy = _env_str("NETWORK_POLICY", "deny")
        env_allowlist = _env_csv(
            "ENV_ALLOWLIST",
            "ANTHROPIC_API_KEY,OPENAI_API_KEY,PATH,HOME,TMPDIR",
        )
        sensitive_env_vars = _env_csv(
            "SENSITIVE_ENV_VARS",
            "ANTHROPIC_API_KEY,OPENAI_API_KEY",
        )
        max_input_artifacts_chars = _env_int("MAX_INPUT_ARTIFACTS_CHARS", 40000)
        max_webhook_body_bytes = _env_int("MAX_WEBHOOK_BODY_BYTES", 262144)
        log_level = _env_str("LOG_LEVEL", "INFO")

        # Ensure directories exist
        for p in [queue_root, artifacts_root, workspaces_root]:
            p.mkdir(parents=True, exist_ok=True)

        return Settings(
            queue_root=queue_root,
            artifacts_root=artifacts_root,
            workspaces_root=workspaces_root,
            webhook_token=webhook_token,
            runner_poll_interval_sec=runner_poll_interval_sec,
            runner_max_idle_sec=runner_max_idle_sec,
            runner_reclaim_after_sec=runner_reclaim_after_sec,
            enable_real_cli=enable_real_cli,
            sandbox=sandbox,
            sandbox_wrapper=sandbox_wrapper,
            sandbox_wrapper_args=sandbox_wrapper_args,
            allowed_binaries=allowed_binaries,
            network_policy=network_policy,
            env_allowlist=env_allowlist,
            sensitive_env_vars=sensitive_env_vars,
            max_input_artifacts_chars=max_input_artifacts_chars,
            max_webhook_body_bytes=max_webhook_body_bytes,
            log_level=log_level,
        )
