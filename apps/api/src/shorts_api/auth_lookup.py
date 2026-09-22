"""Identity lookup boundaries shared by middleware and dependency authentication."""

import hashlib
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from asyncpg import InterfaceError, PostgresError
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: int
    workspace_id: int
    workspace_name: str | None = None
    key_id: int | None = None


class KeyIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: int
    key_id: int | None = Field(default=None, validation_alias="id")


class KeyConnection(Protocol):
    async def fetchrow(self, query: str, key_hash: str) -> Mapping[str, int | str | None] | None: ...


@contextmanager
def authentication_database_boundary() -> Iterator[None]:
    try:
        yield
    except (PostgresError, InterfaceError, OSError, TimeoutError, RuntimeError):
        # Driver exception text can contain query parameters, including credential hashes.
        logger.error("Authentication database lookup failed")
        raise HTTPException(status_code=503, detail="Service unavailable") from None


async def resolve_api_key(api_key: str, connection: KeyConnection) -> KeyIdentity | None:
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    row = await connection.fetchrow(
        "SELECT id, user_id FROM api_keys WHERE key_hash = $1 AND revoked_at IS NULL",
        key_hash,
    )
    if row is None:
        return None
    try:
        return KeyIdentity.model_validate(dict(row))
    except ValidationError:
        return None


def resolve_workspace_id(workspace_header: str | None, member_workspace_ids: list[int]) -> int:
    if workspace_header is None:
        return member_workspace_ids[0]
    try:
        requested_workspace_id = int(workspace_header)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Not found") from None
    if requested_workspace_id not in member_workspace_ids:
        raise HTTPException(status_code=404, detail="Not found")
    return requested_workspace_id
