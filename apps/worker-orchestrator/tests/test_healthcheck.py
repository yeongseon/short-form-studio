from typing import Any

import healthcheck


class _InspectStub:
    def __init__(self, response: Any) -> None:
        self._response = response

    def ping(self) -> Any:
        return self._response


class _ControlStub:
    def __init__(self, response: Any) -> None:
        self._response = response

    def inspect(self, timeout: float) -> _InspectStub:
        assert timeout == 3.0
        return _InspectStub(self._response)


class _CeleryStub:
    def __init__(self, response: Any) -> None:
        self.control = _ControlStub(response)


def test_check_worker_health_passes_when_pong(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        healthcheck,
        "Celery",
        lambda *args, **kwargs: _CeleryStub({"worker@node": {"ok": "pong"}}),
    )

    assert healthcheck.check_worker_health("redis://redis:6379/0") is True


def test_check_worker_health_fails_without_pong(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        healthcheck,
        "Celery",
        lambda *args, **kwargs: _CeleryStub({"worker@node": {"ok": "not-pong"}}),
    )

    assert healthcheck.check_worker_health("redis://redis:6379/0") is False
