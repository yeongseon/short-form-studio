"""Visual plan service with versioned scene document storage.

Provides persistence and versioning for visual plans — ordered scene
documents that map script sections to image-generation prompts. Follows
the same Protocol→InMemory→Service pattern as ScriptService.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

_DOMAIN_DIR = str(Path(__file__).resolve().parent.parent / "creator-domain")
if _DOMAIN_DIR not in sys.path:
    sys.path.insert(0, _DOMAIN_DIR)

from models.visual_plan import VisualPlan, VisualScene  # type: ignore[reportMissingImports]  # noqa: E402, I001


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


# ---------------------------------------------------------------------------
# In-Memory Storage
# ---------------------------------------------------------------------------


class InMemoryVisualPlanStorage:
    """In-memory storage with atomic per-run_id version allocation."""

    def __init__(self) -> None:
        self._plans: dict[int, list[dict[str, Any]]] = {}
        self._next_id = 1
        self._run_locks: dict[int, asyncio.Lock] = {}

    async def save_plan(self, row: dict[str, Any]) -> dict[str, Any]:
        run_id = row["run_id"]
        lock = self._run_locks.setdefault(run_id, asyncio.Lock())
        async with lock:
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
        return dict(saved)

    async def get_active_plan(self, run_id: int) -> dict[str, Any] | None:
        plans = self._plans.get(run_id, [])
        if not plans:
            return None
        return dict(max(plans, key=lambda p: p["version"]))

    async def list_plan_versions(self, run_id: int) -> list[dict[str, Any]]:
        plans = self._plans.get(run_id, [])
        return [dict(p) for p in sorted(plans, key=lambda p: p["version"], reverse=True)]


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
    ) -> VisualPlan:
        """Save a new visual plan version (full replace).

        Version allocation is delegated to the storage backend to
        guarantee atomicity regardless of how many service instances
        share the same backend.
        """
        scenes_json = json.dumps(
            [scene.model_dump(mode="json") for scene in scenes]
        )

        row = await self.storage.save_plan(
            {
                "run_id": run_id,
                "scenes_json": scenes_json,
            }
        )

        return self._row_to_plan(row)

    # -- Single-scene patch -------------------------------------------------

    async def patch_scene(
        self,
        run_id: int,
        scene_id: str,
        updates: dict[str, Any],
    ) -> VisualPlan:
        """Patch a single scene in the active plan and save a new version.

        Loads the active plan, applies *updates* to the scene matching
        *scene_id*, then persists the entire plan as a new version.

        Raises:
            ValueError: If no active plan exists or scene_id not found.
        """
        active_row = await self.storage.get_active_plan(run_id)
        if active_row is None:
            raise ValueError(f"No active visual plan for run {run_id}")

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
            raise ValueError(
                f"Scene '{scene_id}' not found in visual plan for run {run_id}"
            )

        return await self.save_plan(run_id, scenes)

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
        """Parse scenes_json from a storage row into domain objects."""
        scenes_json = row.get("scenes_json")
        if not scenes_json:
            return []
        try:
            data = json.loads(scenes_json)
            return [VisualScene.model_validate(s) for s in data]
        except (json.JSONDecodeError, Exception):
            return []

    @staticmethod
    def _row_to_plan(row: dict[str, Any]) -> VisualPlan:
        """Convert a storage row to a VisualPlan domain model."""
        scenes_json = row.get("scenes_json")
        scenes: list[VisualScene] = []
        if scenes_json:
            try:
                data = json.loads(scenes_json)
                scenes = [VisualScene.model_validate(s) for s in data]
            except (json.JSONDecodeError, Exception):
                scenes = []

        return VisualPlan(
            id=row["id"],
            run_id=row["run_id"],
            version=row.get("version", 1),
            scenes=scenes,
            created_at=row["created_at"],
        )


visual_plan_service = VisualPlanService()
