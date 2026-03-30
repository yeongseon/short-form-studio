import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "creator-domain"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_service import InMemoryRunStorage, RunService

domain_models = importlib.import_module("models")
ModelSelection = domain_models.ModelSelection
RunStage = domain_models.RunStage


def test_create_run_with_model_defaults_and_style_preset() -> None:
    service = RunService(InMemoryRunStorage())

    run = asyncio.run(
        service.create_run(
            project_id=7,
            model_defaults=ModelSelection(script_model="qwen3-4b", image_model="sd15"),
            style_preset="cinematic",
        )
    )

    assert run.project_id == 7
    assert run.current_stage == RunStage.IDEA_READY.value
    assert run.status == "pending"
    assert run.style_preset == "cinematic"
    assert run.model_defaults is not None
    assert run.model_defaults.script_model == "qwen3-4b"
    assert run.model_defaults.image_model == "sd15"


def test_create_run_stores_metadata_in_metadata_json() -> None:
    storage = InMemoryRunStorage()
    service = RunService(storage)
    metadata = {"origin": "manual", "attempt": 1}

    run = asyncio.run(
        service.create_run(
            project_id=8,
            model_defaults={"script_model": "qwen3-8b"},
            style_preset="default",
            metadata=metadata,
        )
    )
    row = asyncio.run(storage.get_run(run.id))

    assert row is not None
    assert row["metadata_json"] == json.dumps(metadata)


def test_get_run_returns_none_for_missing() -> None:
    service = RunService(InMemoryRunStorage())

    run = asyncio.run(service.get_run(9999))

    assert run is None


def test_get_run_returns_existing_run() -> None:
    service = RunService(InMemoryRunStorage())
    created = asyncio.run(
        service.create_run(
            project_id=9,
            model_defaults={"script_model": "qwen3-4b"},
            style_preset="default",
        )
    )

    fetched = asyncio.run(service.get_run(created.id))

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.project_id == 9


def test_restart_run_transitions_correctly() -> None:
    service = RunService(InMemoryRunStorage())
    created = asyncio.run(
        service.create_run(
            project_id=10,
            model_defaults={"script_model": "qwen3-4b"},
            style_preset="default",
        )
    )

    restarted = asyncio.run(service.restart_run(created.id, RunStage.SCRIPT_GENERATING.value))

    assert restarted.current_stage == RunStage.SCRIPT_GENERATING.value
    assert restarted.restart_from == RunStage.SCRIPT_GENERATING.value


def test_restart_run_rejects_invalid_stage_transition() -> None:
    service = RunService(InMemoryRunStorage())
    created = asyncio.run(
        service.create_run(
            project_id=11,
            model_defaults={"script_model": "qwen3-4b"},
            style_preset="default",
        )
    )

    with pytest.raises(ValueError, match="Cannot transition"):
        asyncio.run(service.restart_run(created.id, RunStage.PUBLISHED.value))


def test_restart_run_rejects_review_stage_from_non_review_stage() -> None:
    """Verify that IDEA_READY cannot jump directly to SCRIPT_REVIEW (was incorrectly allowed)."""
    service = RunService(InMemoryRunStorage())
    created = asyncio.run(
        service.create_run(
            project_id=12,
            model_defaults={"script_model": "qwen3-4b"},
            style_preset="default",
        )
    )

    with pytest.raises(ValueError, match="Cannot transition"):
        asyncio.run(service.restart_run(created.id, RunStage.SCRIPT_REVIEW.value))


def test_restart_run_allows_valid_review_stage_restart() -> None:
    """Verify that review stages can restart to their generating stage via TRANSITIONS."""
    service = RunService(InMemoryRunStorage())
    created = asyncio.run(
        service.create_run(
            project_id=13,
            model_defaults={"script_model": "qwen3-4b"},
            style_preset="default",
        )
    )

    # First transition to SCRIPT_GENERATING (valid from IDEA_READY)
    stage1 = asyncio.run(service.restart_run(created.id, RunStage.SCRIPT_GENERATING.value))
    assert stage1.current_stage == RunStage.SCRIPT_GENERATING.value

    # Now manually set the stage to SCRIPT_REVIEW for testing (simulate it was reviewed)
    # We need to restart from SCRIPT_GENERATING to SCRIPT_REVIEW first
    # But since we can't directly manipulate, let's test SCRIPT_GENERATING -> SCRIPT_REVIEW transition
    # by using the fact that stage1 is now in SCRIPT_GENERATING
    
    # Test: from SCRIPT_REVIEW, can restart to SCRIPT_GENERATING (the generating stage)
    # We'll create a test scenario differently:
    storage = InMemoryRunStorage()
    service2 = RunService(storage)
    created2 = asyncio.run(service2.create_run(project_id=14, model_defaults={"script_model": "qwen3-4b"}, style_preset="default"))
    
    # Simulate being in SCRIPT_REVIEW by manually updating storage
    asyncio.run(storage.update_run(created2.id, {"current_stage": RunStage.SCRIPT_REVIEW.value}))
    
    # Now restart from SCRIPT_REVIEW to SCRIPT_GENERATING should succeed (per TRANSITIONS dict)
    restarted = asyncio.run(service2.restart_run(created2.id, RunStage.SCRIPT_GENERATING.value))
    assert restarted.current_stage == RunStage.SCRIPT_GENERATING.value
