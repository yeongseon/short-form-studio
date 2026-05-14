from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tasks import render_video as render_video_module


class FakeStorage:
    def __init__(self, runs: dict[int, dict[str, object]] | None = None) -> None:
        self._runs: dict[int, dict[str, object]] = runs or {}
        self.calls: list[tuple[int, dict[str, object]]] = []
        self.cas_calls: list[tuple[int, dict[str, object], frozenset[str]]] = []

    async def get_run(self, run_id: int) -> dict[str, object] | None:
        return self._runs.get(run_id)

    async def conditional_update_run(
        self,
        run_id: int,
        updates: dict[str, object],
        expected_stages: frozenset[str],
    ) -> tuple[bool, dict[str, object] | None]:
        self.cas_calls.append((run_id, updates, expected_stages))
        row = self._runs.get(run_id)
        if row is None:
            return False, None
        if row.get("current_stage") not in expected_stages:
            return False, dict(row)
        self.calls.append((run_id, updates))
        row.update(updates)
        self._runs[run_id] = row
        return True, dict(row)


def _make_storage(run_id: int = 201, stage: str = "RENDER_GENERATING") -> FakeStorage:
    run_row: dict[str, object] = {"id": run_id, "current_stage": stage}
    return FakeStorage(runs={run_id: run_row})


@dataclass
class FakeVisualAsset:
    scene_id: str
    asset_path: str
    prompt_snapshot: str
    is_active: bool


class FakeVisualAssetService:
    def __init__(self, grouped_assets: dict[str, list[FakeVisualAsset]] | None = None) -> None:
        self.grouped_assets = grouped_assets or {}

    async def list_by_run(self, _run_id: int) -> dict[str, list[FakeVisualAsset]]:
        return self.grouped_assets


@dataclass
class FakeAudioArtifact:
    path: str
    section_id: str | None = None


class FakeAudioService:
    def __init__(
        self,
        artifact: FakeAudioArtifact | None = None,
        paragraph_artifacts: list[FakeAudioArtifact] | None = None,
    ) -> None:
        self.artifact = artifact
        self.paragraph_artifacts = paragraph_artifacts or []

    async def get_latest(self, _run_id: int) -> FakeAudioArtifact | None:
        return self.artifact

    async def list_paragraph_audio(self, _run_id: int) -> list[FakeAudioArtifact]:
        return self.paragraph_artifacts


@dataclass
class FakeSubtitleArtifact:
    path: str
    section_id: str | None = None


class FakeSubtitleService:
    def __init__(
        self,
        artifact: FakeSubtitleArtifact | None = None,
        paragraph_artifacts: list[FakeSubtitleArtifact] | None = None,
    ) -> None:
        self.artifact = artifact
        self.paragraph_artifacts = paragraph_artifacts or []

    async def get_latest(self, _run_id: int) -> FakeSubtitleArtifact | None:
        return self.artifact

    async def list_paragraph_subtitles(self, _run_id: int) -> list[FakeSubtitleArtifact]:
        return self.paragraph_artifacts


@dataclass
class FakePlanScene:
    scene_id: str
    section_id: str


@dataclass
class FakeVisualPlan:
    scenes: list[FakePlanScene]


class FakeVisualPlanService:
    def __init__(self, plan: FakeVisualPlan | None = None) -> None:
        self.plan = plan

    async def get_active_plan(self, _run_id: int) -> FakeVisualPlan | None:
        return self.plan


@dataclass
class FakeScriptSection:
    section_id: str


@dataclass
class FakeScriptDraft:
    structured_script: list[FakeScriptSection] | None


class FakeScriptService:
    def __init__(self, draft: FakeScriptDraft | None = None) -> None:
        self.draft = draft

    async def get_active_draft(self, _run_id: int) -> FakeScriptDraft | None:
        return self.draft


@dataclass
class FakeVideoArtifact:
    id: int
    path: str


class FakeRenderService:
    def __init__(
        self,
        manifest: dict[str, Any],
        artifact_id: int = 1,
        artifact_path: str = "data/artifacts/201/render/output.mp4",
    ) -> None:
        self.manifest = manifest
        self.artifact = FakeVideoArtifact(id=artifact_id, path=artifact_path)
        self.manifest_calls: list[dict[str, object]] = []
        self.create_calls: list[dict[str, object]] = []

    async def build_render_manifest(
        self,
        run_id: int,
        visual_asset_service: Any,
        audio_service: Any,
        subtitle_service: Any,
        render_profile_name: str = "shorts_default",
    ) -> dict[str, Any]:
        self.manifest_calls.append(
            {
                "run_id": run_id,
                "visual_asset_service": visual_asset_service,
                "audio_service": audio_service,
                "subtitle_service": subtitle_service,
                "render_profile_name": render_profile_name,
            }
        )
        return self.manifest

    async def create_artifact(
        self,
        run_id: int,
        path: str,
        *,
        render_profile: str | None = None,
        storage_provider: str | None = None,
        storage_key: str | None = None,
    ) -> FakeRenderArtifact:
        call_data = {
            "run_id": run_id,
            "path": path,
            "render_profile": render_profile,
            "storage_provider": storage_provider,
            "storage_key": storage_key,
        }
