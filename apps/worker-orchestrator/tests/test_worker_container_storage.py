from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DLQ_DIRECTORY = "/var/lib/short-form-studio/dlq"


def test_worker_image_owns_durable_queue_state_directory_before_dropping_root() -> None:
    # Given / When: the worker runtime Dockerfile is read in build order.
    instructions = (
        (ROOT / "apps/worker-orchestrator/Dockerfile")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    # Then: the named-volume mountpoint exists with runtime ownership before USER.
    user_index = instructions.index("USER appuser")
    ownership_index = next(
        index
        for index, instruction in enumerate(instructions)
        if DLQ_DIRECTORY in instruction and "-o appuser -g appuser" in instruction
    )
    assert ownership_index < user_index
