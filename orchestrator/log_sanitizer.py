from __future__ import annotations

import os
import re
from typing import Iterable


_ANTHROPIC_KEY_RE = re.compile(r"sk-ant-[a-zA-Z0-9\-_]{20,}")
_OPENAI_KEY_RE = re.compile(r"sk-[a-zA-Z0-9]{20,}")


def _env_var_names(explicit_vars: Iterable[str] | None) -> list[str]:
    if explicit_vars is not None:
        return [v for v in explicit_vars if v]
    raw = os.getenv("SENSITIVE_ENV_VARS", "ANTHROPIC_API_KEY,OPENAI_API_KEY")
    return [v.strip() for v in raw.split(",") if v.strip()]


def redact(text: str, *, sensitive_env_vars: Iterable[str] | None = None) -> str:
    if not text:
        return text

    redacted = _ANTHROPIC_KEY_RE.sub("[REDACTED:anthropic_key]", text)
    redacted = _OPENAI_KEY_RE.sub("[REDACTED:openai_key]", redacted)

    for env_var in _env_var_names(sensitive_env_vars):
        env_val = os.getenv(env_var)
        if not env_val:
            continue
        redacted = redacted.replace(env_val, f"[REDACTED:env:{env_var}]")

    return redacted
