"""Import a heavy module on first attribute access (Lambda cold starts).

    httpx = lazy_module("httpx")   # costs nothing until httpx.Client is used

Tests can still monkeypatch attributes on the proxy (`module.httpx.Client`).
"""

import importlib


class LazyModule:
    def __init__(self, name: str):
        self._name = name

    def __getattr__(self, attr: str):
        return getattr(importlib.import_module(self._name), attr)


def lazy_module(name: str) -> LazyModule:
    return LazyModule(name)
