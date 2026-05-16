"""Visual plan service with versioned scene document storage.

Provides persistence and versioning for visual plans — ordered scene
documents that map script sections to image-generation prompts. Follows
the same Protocol→InMemory→Service pattern as ScriptService.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Protocol

from creator_domain.models.visual_plan import VisualPlan, VisualScene

# ---------------------------------------------------------------------------
# Patchable field allowlist
# ---------------------------------------------------------------------------

# Fields that patch_scene is allowed to modify.  Immutable identity fields
# (scene_id, section_id, scene_index, section_type, original_text) and
# system-managed fields (latest_asset_id, generation_status) are excluded.
_PATCHABLE_SCENE_FIELDS: frozenset[str] = frozenset(
    {
        "prompt",
        "prompt_edited",
        "prompt_source",
        "style_tags",
        "mood",
        "composition",
    }
)


class VersionConflictError(Exception):
    """Raised when a patch targets a stale plan version."""

    def __init__(self, run_id: int, expected: int, actual: int) -> None:
        self.run_id = run_id
        self.expected_version = expected
        self.actual_version = actual
        super().__init__(
            f"Version conflict for run {run_id}: expected version {expected}, active is {actual}"
        )


class DataIntegrityError(Exception):
    """Raised when stored scenes_json is malformed or unparseable."""


# ---------------------------------------------------------------------------
# Storage Protocol
# ---------------------------------------------------------------------------


class VisualPlanStorageBackend(Protocol):
    async def save_plan(self, row: dict[str, Any]) -> dict[str, Any]:
        """Persist a visual plan row and return stored row with version assigned.

        The storage backend atomically allocates the next version number
        for the given ``run_id``.  Callers MUST NOT include a ``version``
        key in *row*; the returned dict MUST contain the allocated
        ``version``.
        """
        ...

    async def get_active_plan(self, run_id: int) -> dict[str, Any] | None:
        """Fetch the active (latest version) plan for a run."""
        ...

    async def list_plan_versions(self, run_id: int) -> list[dict[str, Any]]:
        """List all plan versions for a run, newest first."""
        ...

    async def save_plan_if_version(
        self,
        row: dict[str, Any],
        expected_version: int,
    ) -> tuple[bool, dict[str, Any] | None, int | None]:
        """Atomically save only if the current active version matches expected_version."""
        ...


# ---------------------------------------------------------------------------
# In-Memory Storage
# ---------------------------------------------------------------------------


class InMemoryVisualPlanStorage:
    """In-memory storage with atomic per-run_id version allocation."""

    def __init__(self) -> None:
        self._plans: dict[int, list[dict[str, Any]]] = {}
        self._next_id = 1
        self._run_locks: dict[int, asyncio.Lock] = {}
        self._by_idempotency_key: dict[str, dict[str, Any]] = {}

    async def save_plan(self, row: dict[str, Any]) -> dict[str, Any]:
        run_id = row["run_id"]
        lock = self._run_locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            idem_key = row.get("idempotency_key")
            if isinstance(idem_key, str) and idem_key in self._by_idempotency_key:
                return dict(self._by_idempotency_key[idem_key])
            plans = self._plans.setdefault(run_id, [])
            next_version = max((p["version"] for p in plans), default=0) + 1
            now = datetime.now(timezone.utc)
            saved = {
                "id": self._next_id,
                "created_at": now,
                "version": next_version,
                **row,
            }
            self._next_id += 1
            plans.append(saved)
            if isinstance(idem_key, str):
                self._by_idempotency_key[idem_key] = saved
        return dict(saved)

    async def get_active_plan(self, run_id: int) -> dict[str, Any] | None:
        plans = self._plans.get(run_id, [])
        if not plans:
            return None
        return dict(max(plans, key=lambda p: p["version"]))

    async def list_plan_versions(self, run_id: int) -> list[dict[str, Any]]:
        plans = self._plans.get(run_id, [])
        return [dict(p) for p in sorted(plans, key=lambda p: p["version"], reverse=True)]

    async def save_plan_if_version(
        self,
        row: dict[str, Any],
        expected_version: int,
    ) -> tuple[bool, dict[str, Any] | None, int | None]:
        run_id = row["run_id"]
        lock = self._run_locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            plans = self._plans.setdefault(run_id, [])
            actual_version = max((p["version"] for p in plans), default=0)
            if actual_version != expected_version:
                current = max(plans, key=lambda p: p["version"]) if plans else None
                return False, dict(current) if current is not None else None, actual_version

            now = datetime.now(timezone.utc)
            saved = {
                "id": self._next_id,
                "created_at": now,
                "version": actual_version + 1,
                **row,
            }
            self._next_id += 1
            plans.append(saved)
            return True, dict(saved), actual_version


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class VisualPlanService:
    def __init__(self, storage: VisualPlanStorageBackend | None = None) -> None:
        self.storage = storage if storage is not None else InMemoryVisualPlanStorage()

    # -- Full replace -------------------------------------------------------

    async def save_plan(
        self,
        run_id: int,
        scenes: list[VisualScene],
        *,
        idempotency_key: str | None = None,
    ) -> VisualPlan:
        """Save a new visual plan version (full replace).

        Version allocation is delegated to the storage backend to
        guarantee atomicity regardless of how many service instances
        share the same backend.
        """
        scenes_json = json.dumps([scene.model_dump(mode="json") for scene in scenes])

        row = await self.storage.save_plan(
            {
                "run_id": run_id,
                "scenes_json": scenes_json,
                "idempotency_key": idempotency_key,
            }
        )

        return self._row_to_plan(row)

    # -- Single-scene patch -------------------------------------------------

    async def patch_scene(
        self,
        run_id: int,
        scene_id: str,
        updates: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> VisualPlan:
        """Patch a single scene in the active plan and save a new version.

        Loads the active plan, validates *expected_version* if provided,
        applies *updates* (restricted to patchable fields) to the scene
        matching *scene_id*, then persists the entire plan as a new version.

        Raises:
            ValueError: If no active plan, scene_id not found, or unknown keys.
            VersionConflictError: If expected_version doesn't match active version.
        """
        # Validate update keys against allowlist
        unknown_keys = set(updates.keys()) - _PATCHABLE_SCENE_FIELDS
        if unknown_keys:
            raise ValueError(f"Cannot patch immutable/unknown fields: {sorted(unknown_keys)}")

        active_row = await self.storage.get_active_plan(run_id)
        if active_row is None:
            raise ValueError(f"No active visual plan for run {run_id}")

        active_version = active_row.get("version", 1)
        if expected_version is not None and active_version != expected_version:
            raise VersionConflictError(run_id, expected_version, active_version)

        scenes = self._parse_scenes(active_row)
        patched = False

        for i, scene in enumerate(scenes):
            if scene.scene_id == scene_id:
                scene_dict = scene.model_dump()
                scene_dict.update(updates)
                scenes[i] = VisualScene.model_validate(scene_dict)
                patched = True
                break

        if not patched:
            raise ValueError(f"Scene '{scene_id}' not found in visual plan for run {run_id}")

        scenes_json = json.dumps([scene.model_dump(mode="json") for scene in scenes])
        if expected_version is None:
            row = await self.storage.save_plan(
                {
                    "run_id": run_id,
                    "scenes_json": scenes_json,
                }
            )
            return self._row_to_plan(row)

        applied, row, actual_version = await self.storage.save_plan_if_version(
            {
                "run_id": run_id,
                "scenes_json": scenes_json,
            },
            expected_version,
        )
        if not applied:
            raise VersionConflictError(
                run_id,
                expected_version,
                actual_version if actual_version is not None else 0,
            )
        if row is None:
            raise ValueError(f"No active visual plan for run {run_id}")
        return self._row_to_plan(row)

    # -- Reads --------------------------------------------------------------

    async def get_active_plan(self, run_id: int) -> VisualPlan | None:
        """Get the active (latest version) visual plan for a run."""
        row = await self.storage.get_active_plan(run_id)
        if row is None:
            return None
        return self._row_to_plan(row)

    async def list_plan_versions(self, run_id: int) -> list[VisualPlan]:
        """List all plan versions for a run, newest first."""
        rows = await self.storage.list_plan_versions(run_id)
        return [self._row_to_plan(row) for row in rows]

    # -- Internal -----------------------------------------------------------

    @staticmethod
    def _parse_scenes(row: dict[str, Any]) -> list[VisualScene]:
        """Parse scenes_json from a storage row into domain objects.

        Raises DataIntegrityError if the stored JSON is malformed or
        contains invalid scene data — callers should NOT silently
        swallow corruption.
        """
        scenes_json = row.get("scenes_json")
        if not scenes_json:
            return []
        try:
            data = json.loads(scenes_json)
        except json.JSONDecodeError as exc:
            raise DataIntegrityError(
                f"Malformed scenes_json for run {row.get('run_id')}: {exc}"
            ) from exc

        if not isinstance(data, list):
            raise DataIntegrityError(f"scenes_json for run {row.get('run_id')} is not a JSON array")

        try:
            return [VisualScene.model_validate(s) for s in data]
        except Exception as exc:
            raise DataIntegrityError(
                f"Invalid scene data for run {row.get('run_id')}: {exc}"
            ) from exc

    @staticmethod
    def _row_to_plan(row: dict[str, Any]) -> VisualPlan:
        """Convert a storage row to a VisualPlan domain model.

        Raises DataIntegrityError on malformed scenes_json.
        """
        scenes = VisualPlanService._parse_scenes(row)

        return VisualPlan(
            id=row["id"],
            run_id=row["run_id"],
            version=row.get("version", 1),
            scenes=scenes,
            created_at=row["created_at"],
        )


def _create_storage() -> VisualPlanStorageBackend:
    import os

    if os.getenv("DATABASE_URL"):
        from .postgres_visual_plan_storage import PostgresVisualPlanStorage

        return PostgresVisualPlanStorage()
    return InMemoryVisualPlanStorage()


visual_plan_service = VisualPlanService(_create_storage())
