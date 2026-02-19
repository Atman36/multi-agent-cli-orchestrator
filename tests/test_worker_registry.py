from __future__ import annotations

import unittest
from unittest import mock

import workers
from workers import registry
from workers.base import BaseWorker


class _DummyExternalWorker(BaseWorker):
    AGENT_NAME = "dummy_external"


class _FakeEntryPoint:
    def __init__(self, *, group: str, name: str, value: str, loaded_obj: object):
        self.group = group
        self.name = name
        self.value = value
        self._loaded_obj = loaded_obj

    def load(self) -> object:
        return self._loaded_obj


class _FakeEntryPoints(list):
    def select(self, *, group: str) -> list[_FakeEntryPoint]:
        return [ep for ep in self if ep.group == group]


class WorkerRegistryTests(unittest.TestCase):
    def test_load_worker_plugins_registers_entry_point_worker(self) -> None:
        fake_eps = _FakeEntryPoints(
            [
                _FakeEntryPoint(
                    group=registry.DEFAULT_WORKER_ENTRYPOINT_GROUP,
                    name="dummy",
                    value="acme.workers:DummyWorker",
                    loaded_obj=_DummyExternalWorker,
                )
            ]
        )

        with mock.patch.dict(registry._WORKERS, {}, clear=True):
            with mock.patch("workers.registry.metadata.entry_points", return_value=fake_eps):
                loaded = registry.load_worker_plugins()
                worker = registry.get_worker("dummy_external")

                self.assertEqual(loaded, ["dummy_external"])
                self.assertIsInstance(worker, _DummyExternalWorker)

    def test_load_worker_plugins_skips_invalid_plugin(self) -> None:
        fake_eps = _FakeEntryPoints(
            [
                _FakeEntryPoint(
                    group=registry.DEFAULT_WORKER_ENTRYPOINT_GROUP,
                    name="invalid",
                    value="acme.workers:invalid",
                    loaded_obj=object(),
                )
            ]
        )

        with mock.patch.dict(registry._WORKERS, {}, clear=True):
            with mock.patch("workers.registry.metadata.entry_points", return_value=fake_eps):
                loaded = registry.load_worker_plugins()
                self.assertEqual(loaded, [])
                self.assertIsNone(registry.get_worker("dummy_external"))

    def test_ensure_workers_registered_bootstraps_once(self) -> None:
        with mock.patch("workers.load_worker_plugins") as load_plugins:
            with mock.patch("workers._BOOTSTRAPPED", False):
                workers.ensure_workers_registered()
                workers.ensure_workers_registered()

        self.assertEqual(load_plugins.call_count, 1)


if __name__ == "__main__":
    unittest.main()
