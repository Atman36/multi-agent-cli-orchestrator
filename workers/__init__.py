from __future__ import annotations

import os

from workers.registry import DEFAULT_WORKER_ENTRYPOINT_GROUP, get_worker, list_workers, load_worker_plugins


_BOOTSTRAPPED = False

def ensure_workers_registered() -> None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    # Side-effect imports register workers in the global registry.
    from workers import claude_worker as _claude  # noqa: F401
    from workers import codex_worker as _codex  # noqa: F401
    from workers import kimi_worker as _kimi  # noqa: F401
    from workers import opencode_worker as _opencode  # noqa: F401
    entrypoint_group = os.getenv("WORKER_ENTRYPOINT_GROUP", DEFAULT_WORKER_ENTRYPOINT_GROUP).strip()
    if entrypoint_group:
        load_worker_plugins(entrypoint_group=entrypoint_group)
    _BOOTSTRAPPED = True


__all__ = ["ensure_workers_registered", "get_worker", "list_workers"]
