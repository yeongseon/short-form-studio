import asyncio

import pytest
from creator_service.usage_service import InMemoryUsageStorage, UsageService


def test_record_usage_creates_event_with_correct_fields() -> None:
    service = UsageService(InMemoryUsageStorage())
    event = asyncio.run(
        service.record_usage(
            workspace_id=10,
            run_id=22,
            provider="openai",
            model_key="gpt-4o-mini",
            operation_type="llm",
            input_tokens=100,
            output_tokens=50,
            estimated_cost_usd=0.1,
            project_id=3,
        )
    )

    assert event.id == 1
    assert event.workspace_id == 10
    assert event.run_id == 22
    assert event.provider == "openai"
    assert event.model_key == "gpt-4o-mini"
    assert event.operation_type == "llm"
    assert event.input_tokens == 100
    assert event.output_tokens == 50
    assert event.estimated_cost_usd == 0.1
    assert event.project_id == 3


def test_get_monthly_summary_aggregates_correctly() -> None:
    service = UsageService(InMemoryUsageStorage())

    asyncio.run(
        service.record_usage(
            workspace_id=1,
            run_id=1,
            provider="openai",
            model_key="gpt-4o-mini",
            operation_type="llm",
            estimated_cost_usd=0.2,
        )
    )
    asyncio.run(
        service.record_usage(
            workspace_id=1,
            run_id=1,
            provider="openai",
            model_key="dall-e-3",
            operation_type="image_gen",
            image_count=2,
            estimated_cost_usd=0.08,
        )
    )
    asyncio.run(
        service.record_usage(
            workspace_id=1,
            run_id=1,
            provider="elevenlabs",
            model_key="multilingual-v2",
            operation_type="tts",
            audio_seconds=12.5,
            estimated_cost_usd=0.01,
        )
    )

    summary = asyncio.run(service.get_monthly_summary(1))

    assert summary.total_llm_calls == 1
    assert summary.total_image_generations == 2
    assert summary.total_tts_seconds == 12.5
    assert summary.total_estimated_cost_usd == pytest.approx(0.29)
    assert summary.by_provider["openai"] == pytest.approx(0.28)
    assert summary.by_operation["llm"] == 1
    assert summary.by_operation["image_gen"] == 1
    assert summary.by_operation["tts"] == 1


def test_check_quota_allows_when_under_limit() -> None:
    service = UsageService(InMemoryUsageStorage())
    allowed, reason = asyncio.run(service.check_quota(77, "llm"))

    assert allowed is True
    assert reason == "ok"


def test_check_quota_rejects_when_over_limit() -> None:
    service = UsageService(InMemoryUsageStorage())
    asyncio.run(service.set_quota(88, monthly_llm_calls=1, monthly_cost_usd=100.0))
    asyncio.run(
        service.record_usage(
            workspace_id=88,
            run_id=1,
            provider="openai",
            model_key="gpt-4o-mini",
            operation_type="llm",
            estimated_cost_usd=0.01,
        )
    )

    allowed, reason = asyncio.run(service.check_quota(88, "llm"))
    assert allowed is False
    assert "LLM call quota exceeded" in reason


def test_set_quota_and_get_quota_work() -> None:
    service = UsageService(InMemoryUsageStorage())
    asyncio.run(
        service.set_quota(
            99,
            monthly_llm_calls=123,
            monthly_image_generations=45,
            monthly_tts_seconds=678,
            monthly_cost_usd=9.5,
        )
    )

    quota = asyncio.run(service.get_quota(99))
    assert quota.workspace_id == 99
    assert quota.monthly_llm_calls == 123
    assert quota.monthly_image_generations == 45
    assert quota.monthly_tts_seconds == 678
    assert quota.monthly_cost_usd == 9.5
