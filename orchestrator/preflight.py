from __future__ import annotations

import re
import shutil
import subprocess


class PreflightError(RuntimeError):
    pass


_VERSION_RE = re.compile(r"(\d+(?:\.\d+){1,3})")


def _extract_version(text: str) -> str | None:
    m = _VERSION_RE.search(text)
    if not m:
        return None
    return m.group(1)


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


def assert_real_cli_ready(
    *,
    allowed_binaries: set[str],
    min_binary_versions: dict[str, str],
    required_binaries: list[str],
) -> dict[str, str]:
    errors: list[str] = []
    resolved_versions: dict[str, str] = {}

    for binary in required_binaries:
        if binary not in allowed_binaries:
            errors.append(f"{binary}: not in ALLOWED_BINARIES")
            continue

        if shutil.which(binary) is None:
            errors.append(f"{binary}: executable not found in PATH")
            continue

        min_version = min_binary_versions.get(binary)
        if not min_version:
            continue

        proc = subprocess.run(
            [binary, "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
        text = (proc.stdout or proc.stderr or "").strip()
        actual_version = _extract_version(text)
        if proc.returncode != 0:
            errors.append(f"{binary}: failed to get version (--version), exit_code={proc.returncode}")
            continue
        if actual_version is None:
            errors.append(f"{binary}: cannot parse version from '{text[:120]}'")
            continue

        resolved_versions[binary] = actual_version
        if _version_tuple(actual_version) < _version_tuple(min_version):
            errors.append(f"{binary}: version {actual_version} is lower than required {min_version}")

    if errors:
        raise PreflightError("Real CLI preflight failed: " + "; ".join(errors))

    return resolved_versions
