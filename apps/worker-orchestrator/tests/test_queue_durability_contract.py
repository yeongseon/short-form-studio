from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def test_compose_persists_redis_and_dlq_fallback() -> None:
    # Given / When: the shipped beta topology is parsed as data.
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    # Then: Redis uses AOF on a named volume and worker fallback storage survives replacement.
    assert services["redis"]["command"] == [
        "redis-server",
        "--appendonly",
        "yes",
        "--appendfsync",
        "everysec",
    ]
    assert "redis_data:/data" in services["redis"]["volumes"]
    assert "dlq_data:/var/lib/short-form-studio/dlq" in services["worker"]["volumes"]
    assert services["worker"]["environment"]["DLQ_FALLBACK_PATH"].startswith(
        "/var/lib/short-form-studio/dlq/"
    )
    assert {"redis_data", "dlq_data"} <= compose["volumes"].keys()
    assert "dlq_data:/var/lib/short-form-studio/dlq" in services["beat"]["volumes"]
    assert services["beat"]["environment"]["BROKER_EPOCH_STATE_PATH"].startswith(
        "/var/lib/short-form-studio/dlq/"
    )


def test_scaled_workers_share_durable_dlq_fallback() -> None:
    # Given / When
    compose = yaml.safe_load(
        (ROOT / "docker-compose.scaled-workers.yml").read_text(encoding="utf-8")
    )

    # Then
    worker_names = {name for name in compose["services"] if name.startswith("worker-")}
    assert worker_names
    for worker_name in worker_names:
        worker = compose["services"][worker_name]
        assert "dlq_data:/var/lib/short-form-studio/dlq" in worker["volumes"]
        assert worker["environment"]["DLQ_FALLBACK_PATH"].startswith(
            "/var/lib/short-form-studio/dlq/"
        )
