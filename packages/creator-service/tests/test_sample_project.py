# pyright: reportPrivateUsage=false

"""SF-75: reproducible sample-project builder invariants.

Locks the contract-loadability, provenance, secret-safety, and Preview/render
compile behavior of the shipped synthetic sample project so it stays a valid,
license-clean demonstration of uploaded + generated media and editable scenes.
"""

import re

import pytest
from creator_domain.models import (
    EncodingProfile,
    MediaAsset,
    MediaOrigin,
    MediaType,
    OutputSpec,
    Project,
    SetTransitionCommand,
    Timeline,
)
from creator_service.editor_command_applier import (
    EditorAssetRef,
    apply_editor_command,
)
from creator_service.sample_project import (
    SAMPLE_CREATED_AT,
    SAMPLE_PROJECT_ID,
    SAMPLE_WORKSPACE_ID,
    SampleProjectBundle,
    build_sample_asset_resolver,
    build_sample_media_assets,
    build_sample_project,
    build_sample_project_bundle,
    build_sample_timeline,
)
from creator_service.timeline_compiler import compile_timeline_to_render_plan
from creator_service.timeline_service import TimelineService

_SECRET_PATTERNS = (
    "http://",
    "https://",
    "file://",
    "/Users/",
    "/home/",
    ".env",
    "${",
    "BEGIN PRIVATE KEY",
    "sk-",
    "ghp_",
    "AKIA",
    "xoxb-",
    "password",
    "token",
    "secret",
)
_WINDOWS_DRIVE = re.compile(r"[A-Za-z]:\\")


def _all_scalar_strings(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            found.append(str(key))
            found.extend(_all_scalar_strings(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_all_scalar_strings(item))
    return found


# --- 1. contract round-trip ---


def test_sample_objects_load_through_supported_contracts() -> None:
    bundle = build_sample_project_bundle()
    assert Project.from_dict(bundle.project.model_dump(mode="json")) == bundle.project
    for asset in bundle.assets:
        assert MediaAsset.from_dict(asset.model_dump(mode="json")) == asset
    assert Timeline.from_dict(bundle.timeline.model_dump(mode="json")) == bundle.timeline


# --- 2. determinism ---


def test_builders_are_deterministic() -> None:
    assert build_sample_project() == build_sample_project()
    assert build_sample_media_assets() == build_sample_media_assets()
    assert build_sample_timeline() == build_sample_timeline()


def test_overrides_only_change_expected_fields() -> None:
    base = build_sample_media_assets()
    overridden = build_sample_media_assets(workspace_id=7, project_id=9)
    for asset in overridden:
        assert asset.workspace_id == 7
        assert asset.project_id == 9
        assert "workspaces/7/" in (asset.storage_key or "")
    assert all(a.workspace_id == SAMPLE_WORKSPACE_ID for a in base)


# --- 3. media coverage ---


def test_media_coverage_uploaded_and_generated() -> None:
    assets = build_sample_media_assets()
    origins = {a.origin for a in assets}
    assert origins == {MediaOrigin.GENERATED, MediaOrigin.UPLOADED}
    media_types = {a.media_type for a in assets}
    assert MediaType.IMAGE in media_types
    assert MediaType.VIDEO in media_types

    timeline = build_sample_timeline()
    assert len(timeline.segments) >= 2
    scenes = {s.scene_id for s in timeline.segments}
    assert len(scenes) >= 2


# --- 4. provenance / license ---


def test_every_asset_has_license_and_provenance() -> None:
    for asset in build_sample_media_assets():
        assert asset.metadata.get("license") == "CC0-1.0"
        assert "provenance" in asset.metadata


def test_generated_asset_flags_synthetic_no_real_model_call() -> None:
    generated = next(
        a for a in build_sample_media_assets() if a.origin == MediaOrigin.GENERATED
    )
    assert generated.metadata.get("generator") == "synthetic-fixture"
    assert "no real model call" in str(generated.metadata.get("note", "")).lower()


def test_uploaded_asset_flagged_non_private() -> None:
    uploaded = next(
        a for a in build_sample_media_assets() if a.origin == MediaOrigin.UPLOADED
    )
    assert "not private" in str(uploaded.metadata.get("note", "")).lower()


# --- 5. no secrets / private media ---


def test_no_secrets_or_private_media_in_serialized_assets() -> None:
    for asset in build_sample_media_assets():
        assert asset.source_url is None
        assert (asset.storage_key or "").startswith("workspaces/")
        for text in _all_scalar_strings(asset.model_dump(mode="json")):
            lowered = text.lower()
            for pattern in _SECRET_PATTERNS:
                assert pattern.lower() not in lowered, f"leaked {pattern!r} in {text!r}"
            assert not text.startswith("/"), f"absolute path in {text!r}"
            assert not _WINDOWS_DRIVE.match(text), f"windows drive in {text!r}"


# --- 6. workspace / project consistency ---


def test_workspace_and_project_consistency() -> None:
    project = build_sample_project()
    assets = build_sample_media_assets()
    timeline = build_sample_timeline()
    assert project.id == SAMPLE_PROJECT_ID
    assert project.workspace_id == SAMPLE_WORKSPACE_ID
    for asset in assets:
        assert asset.workspace_id == SAMPLE_WORKSPACE_ID
        assert asset.project_id == SAMPLE_PROJECT_ID
    assert timeline.project_id == SAMPLE_PROJECT_ID


@pytest.mark.asyncio
async def test_resolver_returns_assets_for_correct_workspace_only() -> None:
    resolver = build_sample_asset_resolver()
    assets = build_sample_media_assets()
    for asset in assets:
        found = await resolver.get_asset(asset.id, SAMPLE_WORKSPACE_ID)
        assert found is not None and found.id == asset.id
        cross = await resolver.get_asset(asset.id, SAMPLE_WORKSPACE_ID + 999)
        assert cross is None


# --- 7. editable draft ---


@pytest.mark.asyncio
async def test_editable_scene_via_real_command_path_leaves_original_untouched() -> None:
    timeline = build_sample_timeline()
    original_dump = timeline.model_dump(mode="json")
    assets = {a.id: a for a in build_sample_media_assets()}

    class _Lookup:
        async def get_asset_for_editor(
            self, asset_id: int, workspace_id: int
        ) -> EditorAssetRef | None:
            asset = assets.get(asset_id)
            if asset is None or asset.workspace_id != workspace_id:
                return None
            return EditorAssetRef(
                id=asset.id,
                project_id=asset.project_id or SAMPLE_PROJECT_ID,
                media_type=asset.media_type.value.upper(),
                duration_seconds=asset.duration_seconds or 0.0,
            )

    target = timeline.segments[0].id
    original_transition = timeline.segments[0].transition
    assert original_transition == "fade"
    command = SetTransitionCommand(segment_id=target, transition="ken_burns_lite")
    edited = await apply_editor_command(
        timeline,
        command,
        workspace_id=SAMPLE_WORKSPACE_ID,
        base_revision=timeline.revision,
        asset_lookup=_Lookup(),
    )
    assert isinstance(edited, Timeline)
    assert edited is not timeline
    assert timeline.model_dump(mode="json") == original_dump
    assert timeline.segments[0].transition == "fade"
    edited_seg = next(s for s in edited.segments if s.id == target)
    assert edited_seg.transition == "ken_burns_lite"


# --- 8. preview compile ---


@pytest.mark.asyncio
async def test_preview_compiles_to_render_plan() -> None:
    bundle = build_sample_project_bundle()
    plan = await compile_timeline_to_render_plan(
        bundle.timeline,
        workspace_id=SAMPLE_WORKSPACE_ID,
        output_spec=OutputSpec.short_vertical(),
        encoding_profile=EncodingProfile.preview(),
        asset_resolver=bundle.resolver,
    )
    assert len(plan.segments) == 2
    assert [s.kind.value for s in plan.segments] == ["image", "video"]
    ordered_assets = sorted(
        bundle.timeline.segments, key=lambda s: s.timeline_start_seconds
    )
    expected_sources = [
        next(a for a in bundle.assets if a.id == seg.asset_id).storage_key
        for seg in ordered_assets
    ]
    assert [s.source for s in plan.segments] == expected_sources
    assert plan.encoding_profile.name == "preview"


# --- 9. render-profile compile ---


@pytest.mark.asyncio
async def test_render_profile_compiles_and_is_deterministic() -> None:
    bundle = build_sample_project_bundle()

    async def _compile(profile: EncodingProfile):
        return await compile_timeline_to_render_plan(
            bundle.timeline,
            workspace_id=SAMPLE_WORKSPACE_ID,
            output_spec=OutputSpec.short_vertical(),
            encoding_profile=profile,
            asset_resolver=bundle.resolver,
        )

    plan_a = await _compile(EncodingProfile.high_quality())
    plan_b = await _compile(EncodingProfile.high_quality())
    assert plan_a == plan_b
    assert plan_a.encoding_profile.name == "high_quality"


# --- 10. persistence contract ---


@pytest.mark.asyncio
async def test_sample_timeline_persists_and_bumps_revision() -> None:
    timeline = build_sample_timeline()

    class _Owner:
        async def get_asset_owner(
            self, asset_id: int, workspace_id: int
        ) -> int | None:
            return SAMPLE_PROJECT_ID if workspace_id == SAMPLE_WORKSPACE_ID else None

    service = TimelineService(asset_owner=_Owner())
    saved = await service.save_timeline(
        project_id=SAMPLE_PROJECT_ID,
        workspace_id=SAMPLE_WORKSPACE_ID,
        timeline=timeline,
        expected_revision=0,
    )
    assert saved.revision == 1
    loaded = await service.load_timeline(
        project_id=SAMPLE_PROJECT_ID, workspace_id=SAMPLE_WORKSPACE_ID
    )
    assert loaded is not None
    assert loaded.revision == 1
    assert [s.id for s in loaded.segments] == [s.id for s in timeline.segments]


def test_bundle_shape_and_constants() -> None:
    bundle = build_sample_project_bundle()
    assert isinstance(bundle, SampleProjectBundle)
    assert bundle.project == build_sample_project()
    assert bundle.assets == build_sample_media_assets()
    assert bundle.timeline == build_sample_timeline()
    assert SAMPLE_CREATED_AT.tzinfo is not None
