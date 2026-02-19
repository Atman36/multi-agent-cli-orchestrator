from __future__ import annotations

from workers.registry import get_worker, list_workers


def ensure_workers_registered() -> None:
    # Side-effect imports register workers in the global registry.
    from workers import claude_worker as _claude  # noqa: F401
    from workers import codex_worker as _codex  # noqa: F401
    from workers import opencode_worker as _opencode  # noqa: F401


__all__ = ["ensure_workers_registered", "get_worker", "list_workers"]
