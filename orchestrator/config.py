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


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v is not None and v != "" else default


def _env_csv(name: str, default: str) -> set[str]:
    raw = os.getenv(name, default)
    return {item.strip() for item in raw.split(",") if item.strip()}


def _env_path_map(name: str, default: str = "") -> dict[str, Path]:
    raw = os.getenv(name, default).strip()
    out: dict[str, Path] = {}
    if not raw:
        return out
    for part in raw.split(","):
        item = part.strip()
        if not item or "=" not in item:
            continue
        alias, path_value = item.split("=", 1)
        alias = alias.strip()
        path_value = path_value.strip()
        if not alias or not path_value:
            continue
        out[alias] = Path(path_value).expanduser().resolve()
    return out


def _env_str_map(name: str, default: str = "") -> dict[str, str]:
    raw = os.getenv(name, default).strip()
    out: dict[str, str] = {}
    if not raw:
        return out
    for part in raw.split(","):
        item = part.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            out[key] = value
    return out


def _env_token_scopes(name: str, default: str = "") -> dict[str, set[str]]:
    raw = os.getenv(name, default).strip()
    out: dict[str, set[str]] = {}
    if not raw:
        return out
    for part in raw.split(","):
        item = part.strip()
        if not item or "=" not in item:
            continue
        token, scopes_raw = item.split("=", 1)
        token = token.strip()
        if not token:
            continue
        scopes = {scope.strip() for scope in scopes_raw.split("|") if scope.strip()}
        if not scopes:
            continue
        if "*" in scopes:
            scopes = {"*"}
        out[token] = scopes
    return out


def _normalize_artifact_handoff(value: str) -> str:
    mode = value.strip().lower()
    if mode in {"manual", "patch_first", "workspace_first"}:
        return mode
    return "manual"


@dataclass(frozen=True)
class Settings:
    queue_root: Path
    artifacts_root: Path
    workspaces_root: Path
    state_db_path: Path
    project_aliases: dict[str, Path]

    webhook_token: str
    webhook_tokens: dict[str, set[str]]
    webhook_rate_limit_window_sec: int
    webhook_rate_limit_max_requests: int
    default_artifact_handoff: str

    runner_poll_interval_sec: int
    runner_max_idle_sec: int
    runner_reclaim_after_sec: int

    enable_real_cli: bool

    sandbox: bool
    sandbox_wrapper: str | None
    sandbox_wrapper_args: list[str]

    allowed_binaries: set[str]
    min_binary_versions: dict[str, str]
    network_policy: str

    env_allowlist: set[str]
    sensitive_env_vars: set[str]
    sandbox_clear_env: bool
    max_input_artifacts_files: int
    max_input_artifact_chars: int
    max_input_artifacts_chars: int
    max_subprocess_output_chars: int
    max_webhook_body_bytes: int
    max_daily_api_calls: int
    max_daily_cost_usd: float
    non_git_workdir_status: str
    retention_interval_sec: int
    artifacts_ttl_sec: int
    workspaces_ttl_sec: int

    log_level: str
    log_json: bool

    @staticmethod
    def load() -> "Settings":
        queue_root = Path(_env_str("QUEUE_ROOT", "var/queue")).resolve()
        artifacts_root = Path(_env_str("ARTIFACTS_ROOT", "artifacts")).resolve()
        workspaces_root = Path(_env_str("WORKSPACES_ROOT", "workspaces")).resolve()
        state_db_path = Path(_env_str("STATE_DB_PATH", "var/state.db")).resolve()
        project_aliases = _env_path_map("PROJECT_ALIASES", "")

        webhook_token = _env_str("WEBHOOK_TOKEN", "dev-token")
        webhook_tokens = _env_token_scopes("WEBHOOK_TOKENS", "")
        webhook_rate_limit_window_sec = max(1, _env_int("WEBHOOK_RATE_LIMIT_WINDOW_SEC", 60))
        webhook_rate_limit_max_requests = max(0, _env_int("WEBHOOK_RATE_LIMIT_MAX_REQUESTS", 30))
        default_artifact_handoff = _normalize_artifact_handoff(_env_str("DEFAULT_ARTIFACT_HANDOFF", "manual"))

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
        min_binary_versions = _env_str_map("MIN_BINARY_VERSIONS", "")

        network_policy = _env_str("NETWORK_POLICY", "deny")
        env_allowlist = _env_csv(
            "ENV_ALLOWLIST",
            "ANTHROPIC_API_KEY,OPENAI_API_KEY,PATH,HOME,TMPDIR",
        )
        sensitive_env_vars = _env_csv(
            "SENSITIVE_ENV_VARS",
            "ANTHROPIC_API_KEY,OPENAI_API_KEY",
        )
        sandbox_clear_env = _env_bool("SANDBOX_CLEAR_ENV", False)
        max_input_artifacts_files = _env_int("MAX_INPUT_ARTIFACTS_FILES", 10)
        max_input_artifact_chars = _env_int("MAX_INPUT_ARTIFACT_CHARS", 12000)
        max_input_artifacts_chars = _env_int("MAX_INPUT_ARTIFACTS_CHARS", 40000)
        max_subprocess_output_chars = max(0, _env_int("MAX_SUBPROCESS_OUTPUT_CHARS", 200000))
        max_webhook_body_bytes = _env_int("MAX_WEBHOOK_BODY_BYTES", 262144)
        max_daily_api_calls = max(0, _env_int("MAX_DAILY_API_CALLS", 0))
        max_daily_cost_usd = max(0.0, _env_float("MAX_DAILY_COST_USD", 0.0))
        non_git_workdir_status = _env_str("NON_GIT_WORKDIR_STATUS", "needs_human").strip().lower()
        if non_git_workdir_status not in {"needs_human", "failed"}:
            non_git_workdir_status = "needs_human"
        retention_interval_sec = _env_int("RETENTION_INTERVAL_SEC", 300)
        artifacts_ttl_sec = _env_int("ARTIFACTS_TTL_SEC", 604800)
        workspaces_ttl_sec = _env_int("WORKSPACES_TTL_SEC", 172800)
        log_level = _env_str("LOG_LEVEL", "INFO")
        log_json = _env_bool("LOG_JSON", False)

        # Ensure directories exist
        for p in [queue_root, artifacts_root, workspaces_root]:
            p.mkdir(parents=True, exist_ok=True)
        state_db_path.parent.mkdir(parents=True, exist_ok=True)

        return Settings(
            queue_root=queue_root,
            artifacts_root=artifacts_root,
            workspaces_root=workspaces_root,
            state_db_path=state_db_path,
            project_aliases=project_aliases,
            webhook_token=webhook_token,
            webhook_tokens=webhook_tokens,
            webhook_rate_limit_window_sec=webhook_rate_limit_window_sec,
            webhook_rate_limit_max_requests=webhook_rate_limit_max_requests,
            default_artifact_handoff=default_artifact_handoff,
            runner_poll_interval_sec=runner_poll_interval_sec,
            runner_max_idle_sec=runner_max_idle_sec,
            runner_reclaim_after_sec=runner_reclaim_after_sec,
            enable_real_cli=enable_real_cli,
            sandbox=sandbox,
            sandbox_wrapper=sandbox_wrapper,
            sandbox_wrapper_args=sandbox_wrapper_args,
            allowed_binaries=allowed_binaries,
            min_binary_versions=min_binary_versions,
            network_policy=network_policy,
            env_allowlist=env_allowlist,
            sensitive_env_vars=sensitive_env_vars,
            sandbox_clear_env=sandbox_clear_env,
            max_input_artifacts_files=max_input_artifacts_files,
            max_input_artifact_chars=max_input_artifact_chars,
            max_input_artifacts_chars=max_input_artifacts_chars,
            max_subprocess_output_chars=max_subprocess_output_chars,
            max_webhook_body_bytes=max_webhook_body_bytes,
            max_daily_api_calls=max_daily_api_calls,
            max_daily_cost_usd=max_daily_cost_usd,
            non_git_workdir_status=non_git_workdir_status,
            retention_interval_sec=retention_interval_sec,
            artifacts_ttl_sec=artifacts_ttl_sec,
            workspaces_ttl_sec=workspaces_ttl_sec,
            log_level=log_level,
            log_json=log_json,
        )
