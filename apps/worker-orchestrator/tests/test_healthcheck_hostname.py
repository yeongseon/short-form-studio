from typing import Any

import pytest

import healthcheck


class _ControlStub:
    def __init__(self, response: Any) -> None:
        self._response = response

    def ping(self, destination: list[str], timeout: float) -> Any:
        assert destination == ["celery@test-worker"]
        assert timeout == 5.0
        return self._response


class _AppStub:
    def __init__(self, response: Any) -> None:
        self.control = _ControlStub(response)


def test_check_health_exits_zero_for_target_worker(monkeypatch: Any) -> None:
    monkeypatch.setattr(healthcheck.socket, "gethostname", lambda: "test-worker")
    monkeypatch.setattr(healthcheck, "app", _AppStub([{"celery@test-worker": {"ok": "pong"}}]))

    with pytest.raises(SystemExit) as exc:
        healthcheck.check_health()

    assert exc.value.code == 0


def test_check_health_exits_one_when_target_worker_not_found(monkeypatch: Any) -> None:
    monkeypatch.setattr(healthcheck.socket, "gethostname", lambda: "test-worker")
    monkeypatch.setattr(healthcheck, "app", _AppStub([]))

    with pytest.raises(SystemExit) as exc:
        healthcheck.check_health()

    assert exc.value.code == 1


def test_get_target_hostname_defaults_to_local_hostname(monkeypatch: Any) -> None:
    monkeypatch.delenv("CELERY_WORKER_HOSTNAME", raising=False)
    monkeypatch.delenv("WORKER_HOSTNAME", raising=False)
    monkeypatch.setattr(healthcheck.socket, "gethostname", lambda: "test-worker")

    assert healthcheck.get_target_hostname() == "celery@test-worker"


def test_get_target_hostname_uses_env_override(monkeypatch: Any) -> None:
    monkeypatch.setenv("CELERY_WORKER_HOSTNAME", "celery@deployed-worker")
    monkeypatch.setattr(healthcheck.socket, "gethostname", lambda: "test-worker")

    assert healthcheck.get_target_hostname() == "celery@deployed-worker"
