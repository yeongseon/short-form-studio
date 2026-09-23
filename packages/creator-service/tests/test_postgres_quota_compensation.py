import anyio
import pytest
from creator_domain.exceptions import ServiceUnavailableError

from .quota_dispatch_support import QuotaDispatch, quota_dispatch, quota_pool  # noqa: F401

pytestmark = [pytest.mark.asyncio, pytest.mark.parametrize("quota_pool", ["postgres"], indirect=True)]


@pytest.mark.parametrize("other_reservation", [False, True])
async def test_database_stage_exception_returns_only_its_reserved_capacity(
    quota_dispatch: QuotaDispatch, other_reservation: bool,
) -> None:
    # Given migrated PostgreSQL run/quota storage and a real failing UPDATE trigger.
    case = quota_dispatch
    assert case.pool is not None
    if other_reservation:
        await case.usage.set_quota(1, monthly_tts_requests=2)
        assert (await case.usage.check_quota(1, "render"))[0]
    before = await case.runs.get_run(case.run_id, workspace_id=1)
    await case.pool.execute("""
        CREATE FUNCTION reject_stage() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.current_stage = 'RENDER_GENERATING' THEN
                RAISE EXCEPTION 'private-stage-storage-token';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER reject_stage BEFORE UPDATE ON creator_runs
        FOR EACH ROW EXECUTE FUNCTION reject_stage();
    """)
    # When the actual SQL update fails after quota committed its reservation.
    with pytest.raises(ServiceUnavailableError) as caught:
        await case.dispatch()
    # Then run state is unchanged, nothing enqueues, and only one slot is available.
    assert str(caught.value) == "Storage failure during dispatch stage update"
    assert caught.value.__suppress_context__ is True
    assert await case.runs.get_run(case.run_id, workspace_id=1) == before
    assert case.port.submissions == []
    assert await case.tracking.list_run_tasks(case.run_id) == []
    results: list[bool] = []

    async def compete() -> None:
        results.append((await case.usage.check_quota(1, "render"))[0])

    async with anyio.create_task_group() as group:
        for _ in range(8):
            group.start_soon(compete)
    assert results.count(True) == 1
    assert results.count(False) == 7


async def test_successful_dispatch_consumes_quota_when_usage_is_recorded(quota_dispatch: QuotaDispatch) -> None:
    # Given a migrated one-slot workspace and a successful real SQL stage update.
    case = quota_dispatch
    # When dispatch succeeds and its provider usage is recorded.
    result = await case.dispatch()
    assert (await case.usage.check_quota(1, "render"))[0] is False
    await case.usage.record_usage(1, case.run_id, "test", "test", "render")
    # Then usage, rather than a leaked reservation, continues to consume the quota.
    assert result["current_stage"] == "RENDER_GENERATING"
    assert len(case.port.submissions) == 1
    assert (await case.usage.check_quota(1, "render"))[0] is False
    assert case.pool is not None
    assert await case.pool.fetchval("SELECT tts_request_count FROM workspace_quota_reservations") == 0
    assert await case.pool.fetchval("SELECT count(*) FROM usage_events") == 1
