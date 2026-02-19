from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


log = logging.getLogger("subprocess")
_missing_allowlist_warnings: set[str] = set()
_safe_base_env_keys_default = ("PATH", "HOME", "TMPDIR")
_safe_base_env_keys_clear = ("PATH",)


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    killed_by_watchdog: bool = False


async def _read_stream(stream: asyncio.StreamReader, sink: list[str], on_line=None):
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode(errors="replace")
        sink.append(text)
        if on_line:
            on_line(text)


async def _terminate_process_group(proc: asyncio.subprocess.Process, *, grace_sec: int = 2) -> None:
    if proc.returncode is not None:
        return

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        with contextlib.suppress(ProcessLookupError):
            proc.send_signal(signal.SIGTERM)

    try:
        await asyncio.wait_for(proc.wait(), timeout=grace_sec)
        return
    except asyncio.TimeoutError:
        pass

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    with contextlib.suppress(ProcessLookupError):
        await proc.wait()


async def run_command(
    cmd: Sequence[str],
    *,
    cwd: str | Path,
    env: Mapping[str, str] | None,
    env_allowlist: Sequence[str] | None,
    clear_env: bool = False,
    timeout_sec: int,
    idle_timeout_sec: int | None = None,
    log_file: Path | None = None,
) -> CommandResult:
    """Run a subprocess with hard timeout + optional idle watchdog.

    - cmd MUST be a list (no shell=True) to avoid injection.
    - env: pass secrets via env, NEVER via CLI args.
    """
    start = time.time()
    killed_by_watchdog = False

    allowlist = [k for k in (env_allowlist or []) if k]
    base_keys = _safe_base_env_keys_clear if clear_env else _safe_base_env_keys_default
    safe_env: dict[str, str] = {}
    for key in base_keys:
        val = os.environ.get(key)
        if val is not None:
            safe_env[key] = val

    for key in allowlist:
        val = os.environ.get(key)
        if val is None:
            if key not in _missing_allowlist_warnings:
                log.warning("ENV allowlist variable is missing in process env: %s", key)
                _missing_allowlist_warnings.add(key)
            continue
        safe_env[key] = val

    for key, val in (env or {}).items():
        if key not in allowlist:
            log.warning("Ignoring non-allowlisted env override: %s", key)
            continue
        safe_env[key] = val

    log.info("Passing env vars to subprocess: %s", ",".join(sorted(safe_env.keys())))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        env=safe_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    last_output = time.time()

    def _touch(_line: str):
        nonlocal last_output
        last_output = time.time()
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with log_file.open("a", encoding="utf-8") as f:
                f.write(_line)

    t_out = asyncio.create_task(_read_stream(proc.stdout, stdout_lines, on_line=_touch))  # type: ignore[arg-type]
    t_err = asyncio.create_task(_read_stream(proc.stderr, stderr_lines, on_line=_touch))  # type: ignore[arg-type]

    async def _watchdog():
        nonlocal killed_by_watchdog
        if idle_timeout_sec is None:
            return
        while proc.returncode is None:
            await asyncio.sleep(1)
            if time.time() - last_output > idle_timeout_sec:
                killed_by_watchdog = True
                await _terminate_process_group(proc, grace_sec=2)
                break

    wd = asyncio.create_task(_watchdog())

    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        await _terminate_process_group(proc, grace_sec=2)

    await t_out
    await t_err
    wd.cancel()

    duration_ms = int((time.time() - start) * 1000)
    return CommandResult(
        exit_code=int(proc.returncode or 0),
        stdout="".join(stdout_lines),
        stderr="".join(stderr_lines),
        duration_ms=duration_ms,
        killed_by_watchdog=killed_by_watchdog,
    )
