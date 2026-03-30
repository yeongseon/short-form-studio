from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Protocol

_DOMAIN_DIR = str(Path(__file__).resolve().parent.parent / "creator-domain")
if _DOMAIN_DIR not in sys.path:
    sys.path.insert(0, _DOMAIN_DIR)

from models.script_draft import ScriptDraft, ScriptSection  # type: ignore[reportMissingImports]

from markdown_parser import parse_markdown


class ScriptStorageBackend(Protocol):
    async def save_draft(self, row: dict[str, Any]) -> dict[str, Any]:
        """Persist a script draft row and return stored row with version assigned.

        The storage backend is responsible for atomically allocating the
        next version number for the given ``run_id``.  Callers MUST NOT
        include a ``version`` key in *row*; the returned dict MUST
        contain the allocated ``version``.
        """
        ...

    async def get_active_draft(self, run_id: int) -> dict[str, Any] | None:
        """Fetch the active (latest version) draft for a run."""
        ...

    async def list_draft_versions(self, run_id: int) -> list[dict[str, Any]]:
        """List all draft versions for a run, newest first."""
        ...


class InMemoryScriptStorage:
    """In-memory storage with atomic per-run_id version allocation."""

    def __init__(self) -> None:
        self._drafts: dict[int, list[dict[str, Any]]] = {}
        self._next_id = 1
        self._run_locks: dict[int, asyncio.Lock] = {}

    async def save_draft(self, row: dict[str, Any]) -> dict[str, Any]:
        run_id = row["run_id"]
        lock = self._run_locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            drafts = self._drafts.setdefault(run_id, [])
            next_version = max((d["version"] for d in drafts), default=0) + 1
            now = datetime.now(timezone.utc)
            saved = {
                "id": self._next_id,
                "created_at": now,
                "version": next_version,
                **row,
            }
            self._next_id += 1
            drafts.append(saved)
        return dict(saved)

    async def get_active_draft(self, run_id: int) -> dict[str, Any] | None:
        drafts = self._drafts.get(run_id, [])
        if not drafts:
            return None
        return dict(max(drafts, key=lambda d: d["version"]))

    async def list_draft_versions(self, run_id: int) -> list[dict[str, Any]]:
        drafts = self._drafts.get(run_id, [])
        return [dict(d) for d in sorted(drafts, key=lambda d: d["version"], reverse=True)]


class ScriptService:
    def __init__(self, storage: ScriptStorageBackend | None = None) -> None:
        self.storage = storage if storage is not None else InMemoryScriptStorage()

    async def save_draft(
        self,
        run_id: int,
        source_type: str,
        markdown_content: str | None = None,
        structured_script: list[ScriptSection] | None = None,
    ) -> ScriptDraft:
        """Save a new script draft version.

        If markdown_content is provided and structured_script is not,
        parse the markdown to generate the structured script.
        If this run already has drafts, use existing sections for stable IDs.

        Version allocation is delegated to the storage backend to
        guarantee atomicity regardless of how many ScriptService
        instances share the same backend.
        """
        current = await self.storage.get_active_draft(run_id)
        existing_sections: list[ScriptSection] | None = None

        if current is not None:
            existing_json = current.get("structured_script_json")
            if existing_json:
                try:
                    existing_data = json.loads(existing_json)
                    existing_sections = [ScriptSection.model_validate(section) for section in existing_data]
                except (json.JSONDecodeError, Exception):
                    existing_sections = None

        if markdown_content is not None and structured_script is None:
            structured_script = parse_markdown(markdown_content, existing_sections=existing_sections)

        structured_script_json: str | None = None
        if structured_script is not None:
            structured_script_json = json.dumps([section.model_dump(mode="json") for section in structured_script])

        row = await self.storage.save_draft(
            {
                "run_id": run_id,
                "source_type": source_type,
                "markdown_content": markdown_content,
                "structured_script_json": structured_script_json,
            }
        )

        return self._row_to_draft(row)

    async def get_active_draft(self, run_id: int) -> ScriptDraft | None:
        """Get the active (latest version) draft for a run."""
        row = await self.storage.get_active_draft(run_id)
        if row is None:
            return None
        return self._row_to_draft(row)

    async def list_draft_versions(self, run_id: int) -> list[ScriptDraft]:
        """List all draft versions for a run, newest first."""
        rows = await self.storage.list_draft_versions(run_id)
        return [self._row_to_draft(row) for row in rows]

    @staticmethod
    def _row_to_draft(row: dict[str, Any]) -> ScriptDraft:
        """Convert a storage row to a ScriptDraft domain model."""
        structured_script: list[ScriptSection] | None = None
        structured_json = row.get("structured_script_json")
        if structured_json:
            try:
                data = json.loads(structured_json)
                structured_script = [ScriptSection.model_validate(section) for section in data]
            except (json.JSONDecodeError, Exception):
                structured_script = None

        return ScriptDraft(
            id=row["id"],
            run_id=row["run_id"],
            source_type=row["source_type"],
            markdown_content=row.get("markdown_content"),
            structured_script=structured_script,
            version=row.get("version", 1),
            created_at=row["created_at"],
        )


script_service = ScriptService()
