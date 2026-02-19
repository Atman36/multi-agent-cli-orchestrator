from __future__ import annotations

from workers.base import BaseWorker


_WORKERS: dict[str, BaseWorker] = {}


def register_worker(worker: BaseWorker) -> None:
    _WORKERS[worker.AGENT_NAME] = worker


def get_worker(agent_name: str) -> BaseWorker | None:
    return _WORKERS.get(agent_name)


def list_workers() -> dict[str, BaseWorker]:
    return dict(_WORKERS)
