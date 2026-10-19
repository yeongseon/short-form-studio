import pytest
import anyio
from decimal import Decimal
from creator_service import db
from creator_service.memory_task_tracking_storage import InMemoryTaskTrackingStorage
from creator_service.postgres_task_tracking_storage import PostgresTaskTrackingStorage
from creator_service.task_tracking_service import TaskTrackingService
from creator_service.task_tracking_storage import BillingOutcome
from creator_service.run_service import RunStorageBackend
from creator_service.usage_service import InMemoryUsageStorage, UsageService
from creator_service.usage_service import UsageStorageBackend

from .quota_dispatch_support import quota_pool as quota_pool


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_only_claim_owner_can_finalize_timeout(quota_pool: object) -> None:
    # Given two deliveries for the same logical task, with A owning the running row.
    storage = PostgresTaskTrackingStorage() if quota_pool is not None else InMemoryTaskTrackingStorage()
    tracking = TaskTrackingService(storage)
    if quota_pool is not None:
        pool = await db.get_pool()
        await pool.execute("INSERT INTO creator_projects (id, workspace_id) VALUES (1, 1)")
        await pool.execute("INSERT INTO creator_runs (id, project_id, workspace_id, current_stage) VALUES (1, 1, 1, 'AUDIO_GENERATING')")
    winner = await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-a")
    assert winner is not None and winner.status == "running"
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-b") is None

    # When B tries to finalize a timeout before A.
    assert await tracking.mark_failed_if_claimed("delivery-1", "owner-b", "INTERNAL", "timed out") is None
    assert (await storage.get_by_celery_id("delivery-1"))["status"] == "running"

    # Then only the matching owner can transition the task to failed.
    failed = await tracking.mark_failed_if_claimed("delivery-1", "owner-a", "INTERNAL", "timed out")
    assert failed is not None and failed.status == "failed"
    assert await tracking.mark_failed_if_claimed("delivery-1", "owner-a", "INTERNAL", "timed out") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_stale_success_cannot_finalize_newer_claim(quota_pool: object) -> None:
    # Given a newer worker claimed the same task after the previous attempt failed.
    storage = PostgresTaskTrackingStorage() if quota_pool is not None else InMemoryTaskTrackingStorage()
    tracking = TaskTrackingService(storage)
    if quota_pool is not None:
        pool = await db.get_pool()
        await pool.execute("INSERT INTO creator_projects (id, workspace_id) VALUES (1, 1)")
        await pool.execute("INSERT INTO creator_runs (id, project_id, workspace_id, current_stage) VALUES (1, 1, 1, 'AUDIO_GENERATING')")
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-a")
    assert await tracking.mark_failed_if_claimed("delivery-1", "owner-a", "INTERNAL", "retry")
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-b")

    # When A reports success after B has won the retry claim.
    assert await tracking.mark_success_if_claimed("delivery-1", "owner-a") is None

    # Then B's running claim remains untouched until B finalizes it.
    assert (await storage.get_by_celery_id("delivery-1"))["status"] == "running"
    assert await tracking.mark_success_if_claimed("delivery-1", "owner-b")
    assert (await storage.get_by_celery_id("delivery-1"))["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_stale_failure_cannot_finalize_newer_claim(quota_pool: object) -> None:
    # Given a retried delivery B after A has failed.
    storage = PostgresTaskTrackingStorage() if quota_pool is not None else InMemoryTaskTrackingStorage()
    tracking = TaskTrackingService(storage)
    if quota_pool is not None:
        pool = await db.get_pool()
        await pool.execute("INSERT INTO creator_projects (id, workspace_id) VALUES (1, 1)")
        await pool.execute("INSERT INTO creator_runs (id, project_id, workspace_id, current_stage) VALUES (1, 1, 1, 'AUDIO_GENERATING')")
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-a")
    assert await tracking.mark_failed_if_claimed("delivery-1", "owner-a", "INTERNAL", "retry")
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-b")

    # When A reports its late failure.
    assert await tracking.mark_failed_if_claimed("delivery-1", "owner-a", "INTERNAL", "late") is None

    # Then B remains running until B itself fails.
    assert (await storage.get_by_celery_id("delivery-1"))["status"] == "running"
    assert await tracking.mark_failed_if_claimed("delivery-1", "owner-b", "INTERNAL", "failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_claimed_task_finishes_when_run_stage_cas_misses(quota_pool: object) -> None:
    # Given a claimed task whose run has already advanced beyond its expected stage.
    storage = PostgresTaskTrackingStorage() if quota_pool is not None else InMemoryTaskTrackingStorage()
    tracking = TaskTrackingService(storage)
    if quota_pool is not None:
        from creator_service.postgres_run_storage import PostgresRunStorage

        pool = await db.get_pool()
        await pool.execute("INSERT INTO creator_projects (id, workspace_id) VALUES (1, 1)")
        await pool.execute(
            "INSERT INTO creator_runs (id, project_id, workspace_id, current_stage) "
            "VALUES (1, 1, 1, 'RENDER_GENERATING')"
        )
        run_storage = PostgresRunStorage()
    else:
        from creator_service.run_service import InMemoryRunStorage

        run_storage = InMemoryRunStorage()
        await run_storage.create_run(
            {"id": 1, "project_id": 1, "workspace_id": 1, "current_stage": "RENDER_GENERATING"}
        )
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-a")

    # When the owner finishes against the stale expected stage.
    accepted = await tracking.finish_claimed_run(
        "delivery-1", "owner-a", "success", run_storage, 1,
        {"current_stage": "AUDIO_REVIEW", "status": "paused"},
        frozenset({"AUDIO_GENERATING"}), frozenset({"failed", "cancelled", "completed"}),
    )

    # Then the run CAS reports a miss while the owned task still reaches terminal state.
    task = await storage.get_by_celery_id("delivery-1")
    run = await run_storage.get_run(1)
    assert not accepted
    assert task is not None and task["status"] == "success"
    assert run is not None and run["current_stage"] == "RENDER_GENERATING"


@pytest.mark.asyncio
async def test_failure_finalization_prevents_successor_claim_during_quota_cleanup() -> None:
    # Given an old delivery whose atomic finalizer pauses while holding ownership.
    storage = InMemoryTaskTrackingStorage()
    tracking = TaskTrackingService(storage)
    usage_storage = InMemoryUsageStorage()
    usage = UsageService(usage_storage)
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-a")
    assert await usage.reserve_owned(1, "image_gen", "delivery-1")
    cleanup_started = anyio.Event()
    resume_cleanup = anyio.Event()
    original_cancel = usage_storage.cancel_owned

    async def pause_cancel(owner_id: str) -> bool:
        cleanup_started.set()
        await resume_cleanup.wait()
        return await original_cancel(owner_id)

    usage_storage.cancel_owned = pause_cancel
    finalization: list[bool] = []

    async def finalize() -> None:
        finalization.append(
            await tracking.fail_claimed_and_cancel_quota(
                "delivery-1", "owner-a", usage_storage, "INTERNAL", "failed",
            )
        )

    # When a successor tries to claim after finalization starts but before cleanup resumes.
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(finalize)
        await cleanup_started.wait()
        successor = await tracking.record_task_start(
            1, "generate_audio", "delivery-1", claim_token="owner-b",
        )
        resume_cleanup.set()

    # Then the successor cannot interleave and inherit quota owned by the old execution.
    assert successor is None
    assert finalization == [True]
    assert not await usage.cancel_owned("delivery-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_stale_atomic_failure_leaves_successor_task_run_and_quota_unchanged(
    quota_pool: object,
) -> None:
    # Given a successor claim and quota reservation after the old attempt failed.
    tracking_storage = (
        PostgresTaskTrackingStorage()
        if quota_pool is not None
        else InMemoryTaskTrackingStorage()
    )
    tracking = TaskTrackingService(tracking_storage)
    if quota_pool is not None:
        from creator_service.postgres_usage_storage import PostgresUsageStorage
        from creator_service.postgres_run_storage import PostgresRunStorage

        pool = await db.get_pool()
        await pool.execute("INSERT INTO creator_projects (id, workspace_id) VALUES (1, 1)")
        await pool.execute(
            "INSERT INTO creator_runs (id, project_id, workspace_id, current_stage) "
            "VALUES (1, 1, 1, 'AUDIO_GENERATING')"
        )
        usage_storage = PostgresUsageStorage()
        run_storage = PostgresRunStorage()
    else:
        from creator_service.run_service import InMemoryRunStorage

        usage_storage = InMemoryUsageStorage()
        run_storage = InMemoryRunStorage()
        await run_storage.create_run(
            {"id": 1, "project_id": 1, "workspace_id": 1, "current_stage": "AUDIO_GENERATING"}
        )
    usage = UsageService(usage_storage)
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-a")
    assert await tracking.mark_failed_if_claimed("delivery-1", "owner-a", "INTERNAL", "retry")
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-b")
    assert await usage.reserve_owned(1, "image_gen", "delivery-1")

    # When the old attempt resumes its atomic failure cleanup.
    accepted = await tracking.fail_claimed_and_cancel_quota(
        "delivery-1", "owner-a", usage_storage, "TIMEOUT", "late",
        run_storage, 1, frozenset({"AUDIO_GENERATING"}),
    )

    # Then the successor retains its task claim and quota reservation.
    successor = await tracking_storage.get_by_celery_id("delivery-1")
    assert not accepted
    assert successor is not None
    assert (successor["status"], successor["claim_token"]) == ("running", "owner-b")
    run = await run_storage.get_run(1)
    assert run is not None
    assert run["current_stage"] == "AUDIO_GENERATING"
    assert await usage.cancel_owned("delivery-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["postgres"], indirect=True)
async def test_postgres_atomic_failure_blocks_successor_claim_until_quota_cleanup(
    quota_pool: object,
) -> None:
    # Given PostgreSQL cleanup is blocked on the workspace quota advisory lock.
    if quota_pool is None:
        pytest.fail("PostgreSQL fixture required")
    from creator_service.postgres_usage_storage import PostgresUsageStorage
    from creator_service.postgres_run_storage import PostgresRunStorage

    pool = await db.get_pool()
    await pool.execute("INSERT INTO creator_projects (id, workspace_id) VALUES (1, 1)")
    await pool.execute(
        "INSERT INTO creator_runs (id, project_id, workspace_id, current_stage) "
        "VALUES (1, 1, 1, 'AUDIO_GENERATING')"
    )
    tracking_storage = PostgresTaskTrackingStorage()
    tracking = TaskTrackingService(tracking_storage)
    usage = UsageService(PostgresUsageStorage())
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-a")
    assert await usage.reserve_owned(1, "image_gen", "delivery-1")
    finalization: list[bool] = []
    finalization_blocked = anyio.Event()
    release_finalization = anyio.Event()
    original_finalize = tracking_storage.fail_claimed_and_cancel_quota

    async def blocked_finalize(
        celery_task_id: str, token: str, usage_storage: UsageStorageBackend,
        error_code: str, error_message: str, run_storage: RunStorageBackend | None = None,
        run_id: int | None = None, expected_stages: frozenset[str] = frozenset(),
        billing_outcome: BillingOutcome = BillingOutcome.NOT_STARTED,
    ) -> bool:
        finalization_blocked.set()
        await release_finalization.wait()
        return await original_finalize(
            celery_task_id, token, usage_storage, error_code, error_message,
            run_storage, run_id, expected_stages, billing_outcome,
        )

    tracking_storage.fail_claimed_and_cancel_quota = blocked_finalize

    async def finalize() -> None:
        finalization.append(await tracking.fail_claimed_and_cancel_quota(
            "delivery-1", "owner-a", usage.storage, "TIMEOUT", "failed",
            PostgresRunStorage(), 1, frozenset({"AUDIO_GENERATING"}),
        ))

    # When finalization is blocked, the still-running owner rejects a successor claim.
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(finalize)
        await finalization_blocked.wait()
        successor = await tracking.record_task_start(
            1, "generate_audio", "delivery-1", claim_token="owner-b",
        )
        assert successor is None
        release_finalization.set()

    # Then releasing the lock commits one terminal task/run/quota outcome.
    assert finalization == [True]
    replacement = await tracking.record_task_start(
        1, "generate_audio", "delivery-1", claim_token="owner-b",
    )
    assert replacement is not None
    task = await tracking_storage.get_by_celery_id("delivery-1")
    run = await PostgresRunStorage().get_run(1)
    owner_status = await pool.fetchval(
        "SELECT status FROM workspace_quota_reservation_owners WHERE owner_id=$1",
        "delivery-1",
    )
    assert task is not None and (task["status"], task["claim_token"]) == ("running", "owner-b")
    assert run is not None and (run["status"], run["current_stage"]) == ("failed", "FAILED")
    assert owner_status == "cancelled"
    assert not await usage.cancel_owned("delivery-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["postgres"], indirect=True)
async def test_postgres_atomic_failure_cancels_all_reserved_units_and_cost(
    quota_pool: object,
) -> None:
    # Given a claimed task owns a three-unit reservation.
    if quota_pool is None:
        pytest.fail("PostgreSQL fixture required")
    from creator_service.postgres_usage_storage import PostgresUsageStorage

    pool = await db.get_pool()
    await pool.execute("INSERT INTO creator_projects (id, workspace_id) VALUES (1, 1)")
    await pool.execute(
        "INSERT INTO creator_runs (id, project_id, workspace_id, current_stage) "
        "VALUES (1, 1, 1, 'AUDIO_GENERATING')"
    )
    tracking = TaskTrackingService(PostgresTaskTrackingStorage())
    usage = UsageService(PostgresUsageStorage())
    await usage.set_quota(1, monthly_image_generations=3, monthly_cost_usd=10)
    assert await tracking.record_task_start(
        1, "generate_audio", "delivery-1", claim_token="owner-a",
    )
    assert await usage.reserve_owned(
        1, "image_gen", "delivery-1", estimated_cost_usd=Decimal("6"), units=3,
    )

    # When pre-provider failure atomically finalizes the task.
    assert await tracking.fail_claimed_and_cancel_quota(
        "delivery-1", "owner-a", usage.storage, "INTERNAL", "failed",
    )

    # Then every reserved unit and dollar is released and the owner is terminal.
    reservation = await pool.fetchrow(
        "SELECT image_count, reserved_estimated_cost_usd "
        "FROM workspace_quota_reservations WHERE workspace_id=1"
    )
    owner = await pool.fetchrow(
        "SELECT status, reserved_units FROM workspace_quota_reservation_owners "
        "WHERE owner_id='delivery-1'"
    )
    assert reservation is not None
    assert (reservation["image_count"], reservation["reserved_estimated_cost_usd"]) == (
        0, Decimal("0"),
    )
    assert owner is not None
    assert (owner["status"], owner["reserved_units"]) == ("cancelled", 0)
