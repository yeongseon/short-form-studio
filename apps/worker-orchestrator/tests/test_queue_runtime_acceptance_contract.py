from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_runtime_acceptance_writes_queue_state_from_every_container_topology() -> None:
    # Given / When
    acceptance = (ROOT / "scripts/cutover_runtime_acceptance.sh").read_text(
        encoding="utf-8"
    )

    # Then
    assert "run --rm --no-deps beat sh -c" in acceptance
    assert "/var/lib/short-form-studio/dlq/observed-broker-epoch" in acceptance
    for service in (
        "worker",
        "worker-script",
        "worker-image",
        "worker-audio",
        "worker-render",
    ):
        assert f'assert_dlq_write "{service}"' in acceptance


def test_runtime_acceptance_executes_all_redis_lifecycle_scenarios() -> None:
    # Given / When
    acceptance = (ROOT / "scripts/cutover_runtime_acceptance.sh").read_text(
        encoding="utf-8"
    )

    # Then
    for scenario in (
        "redis_process_restart",
        "redis_force_recreate_retained_volume",
        "redis_fresh_volume_replacement",
    ):
        assert f'run_redis_lifecycle "{scenario}"' in acceptance
    assert "for status in pending queued running success" in acceptance
    assert "${scenario}-lifecycle-${status}" in acceptance
    assert "assert_late_worker_fenced" in acceptance
    assert "workspace_quota_reservation_owners" in acceptance


def test_runtime_acceptance_preserves_real_routed_messages() -> None:
    # Given / When
    acceptance = (ROOT / "scripts/cutover_runtime_acceptance.sh").read_text(
        encoding="utf-8"
    )

    # Then
    assert "enqueue_lifecycle_marker" in acceptance
    assert "acceptance.marker" in acceptance
    assert "durability-marker" in acceptance
    assert "assert_lifecycle_marker" in acceptance


def test_runtime_acceptance_recovers_redacted_dlq_fallback_after_recreate() -> None:
    # Given / When
    acceptance = (ROOT / "scripts/cutover_runtime_acceptance.sh").read_text(
        encoding="utf-8"
    )

    # Then
    assert "_record_failed_task_to_dlq" in acceptance
    assert "read_dlq_fallback" in acceptance
    assert "--force-recreate --no-deps worker" in acceptance
    assert '"password": "[REDACTED]"' in acceptance
