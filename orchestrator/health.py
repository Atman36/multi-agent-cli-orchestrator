from __future__ import annotations

import importlib.metadata
import os
import shutil
import socket
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from orchestrator.budget import BudgetTracker
from orchestrator.config import Settings


@dataclass(frozen=True)
class CheckResult:
    status: str  # OK | WARN | FAIL
    title: str
    detail: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _requirements_file() -> Path:
    return _repo_root() / "requirements.txt"


def _parse_requirement_names(path: Path) -> list[str]:
    names: list[str] = []
    if not path.exists():
        return names

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        base = line.split("#", 1)[0].strip()
        for sep in ("==", ">=", "<=", "~=", "!=", ">", "<"):
            if sep in base:
                base = base.split(sep, 1)[0].strip()
                break
        if "[" in base:
            base = base.split("[", 1)[0].strip()
        if base:
            names.append(base)
    return names


def _is_writable_dir(path: Path) -> bool:
    return path.exists() and path.is_dir() and os.access(path, os.W_OK)


def _check_port_free(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def run_doctor_checks(settings: Settings) -> list[CheckResult]:
    out: list[CheckResult] = []

    if sys.version_info >= (3, 11):
        out.append(CheckResult("OK", "Python", f"{sys.version.split()[0]}"))
    else:
        out.append(CheckResult("FAIL", "Python", f"{sys.version.split()[0]} (нужно >= 3.11)"))

    reqs = _parse_requirement_names(_requirements_file())
    missing: list[str] = []
    for req in reqs:
        try:
            importlib.metadata.version(req)
        except importlib.metadata.PackageNotFoundError:
            missing.append(req)
    if missing:
        out.append(CheckResult("FAIL", "Requirements", "Отсутствуют пакеты: " + ", ".join(missing)))
    else:
        out.append(CheckResult("OK", "Requirements", f"Установлено: {len(reqs)}"))

    if settings.webhook_token == "dev-token":
        out.append(CheckResult("WARN", "WEBHOOK_TOKEN", "Используется dev-token"))
    else:
        out.append(CheckResult("OK", "WEBHOOK_TOKEN", "Настроен"))

    queue_dirs = [
        settings.queue_root / "pending",
        settings.queue_root / "running",
        settings.queue_root / "done",
        settings.queue_root / "failed",
        settings.queue_root / "awaiting_approval",
    ]
    bad_queue_dirs = [str(p) for p in queue_dirs if not _is_writable_dir(p)]
    if bad_queue_dirs:
        out.append(CheckResult("FAIL", "Queue dirs", "Недоступны для записи: " + ", ".join(bad_queue_dirs)))
    else:
        out.append(CheckResult("OK", "Queue dirs", "Все каталоги доступны"))

    roots = [settings.artifacts_root, settings.workspaces_root]
    bad_roots = [str(p) for p in roots if not _is_writable_dir(p)]
    if bad_roots:
        out.append(CheckResult("FAIL", "Artifacts/workspaces", "Недоступны: " + ", ".join(bad_roots)))
    else:
        out.append(CheckResult("OK", "Artifacts/workspaces", "Каталоги доступны"))

    if settings.enable_real_cli:
        missing_bins = [name for name in ("claude", "codex", "opencode") if shutil.which(name) is None]
        if missing_bins:
            out.append(CheckResult("FAIL", "Real CLI binaries", "Не найдены: " + ", ".join(missing_bins)))
        else:
            out.append(CheckResult("OK", "Real CLI binaries", "Все бинарники найдены"))
    else:
        out.append(CheckResult("WARN", "ENABLE_REAL_CLI", "Выключен (simulation mode)"))

    if settings.max_daily_api_calls > 0 or settings.max_daily_cost_usd > 0:
        try:
            BudgetTracker(
                db_path=settings.state_db_path,
                max_daily_api_calls=settings.max_daily_api_calls,
                max_daily_cost_usd=settings.max_daily_cost_usd,
            )
            with sqlite3.connect(settings.state_db_path) as conn:
                conn.execute("SELECT 1").fetchone()
            out.append(CheckResult("OK", "Budget DB", str(settings.state_db_path)))
        except Exception as e:
            out.append(CheckResult("FAIL", "Budget DB", str(e)))
    else:
        out.append(CheckResult("WARN", "Budget gate", "Отключен (лимиты = 0)"))

    if _check_port_free("127.0.0.1", 8080):
        out.append(CheckResult("OK", "Port 8080", "Свободен"))
    else:
        out.append(CheckResult("WARN", "Port 8080", "Уже занят"))

    return out
