from __future__ import annotations

import logging
from importlib import metadata
from typing import Any

from workers.base import BaseWorker


_WORKERS: dict[str, BaseWorker] = {}
DEFAULT_WORKER_ENTRYPOINT_GROUP = "multi_agent_cli_orchestrator.workers"
log = logging.getLogger("workers.registry")


def register_worker(worker: BaseWorker) -> None:
    previous = _WORKERS.get(worker.AGENT_NAME)
    if previous is not None and type(previous) is not type(worker):
        log.warning(
            "Worker '%s' was replaced: %s -> %s",
            worker.AGENT_NAME,
            type(previous).__name__,
            type(worker).__name__,
        )
    _WORKERS[worker.AGENT_NAME] = worker


def get_worker(agent_name: str) -> BaseWorker | None:
    return _WORKERS.get(agent_name)


def list_workers() -> dict[str, BaseWorker]:
    return dict(_WORKERS)


def _entry_points_for_group(group: str) -> list[metadata.EntryPoint]:
    eps = metadata.entry_points()
    if hasattr(eps, "select"):
        return list(eps.select(group=group))
    return list(eps.get(group, []))


def _coerce_plugin_worker(loaded: Any) -> BaseWorker:
    if isinstance(loaded, BaseWorker):
        return loaded
    if isinstance(loaded, type) and issubclass(loaded, BaseWorker):
        return loaded()
    if callable(loaded):
        candidate = loaded()
        if isinstance(candidate, BaseWorker):
            return candidate
    raise TypeError(f"Unsupported plugin object type: {type(loaded)!r}")


def load_worker_plugins(entrypoint_group: str = DEFAULT_WORKER_ENTRYPOINT_GROUP) -> list[str]:
    loaded_agents: list[str] = []
    for ep in _entry_points_for_group(entrypoint_group):
        try:
            worker = _coerce_plugin_worker(ep.load())
        except Exception:
            log.exception("Failed to load worker plugin from entry point '%s' (%s)", ep.name, ep.value)
            continue
        register_worker(worker)
        loaded_agents.append(worker.AGENT_NAME)
        log.info("Loaded worker plugin '%s' from entry point '%s'", worker.AGENT_NAME, ep.name)
    return loaded_agents
