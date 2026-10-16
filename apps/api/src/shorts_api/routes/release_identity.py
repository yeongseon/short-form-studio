import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError
from starlette import status

from shorts_api.auth import CurrentUser, get_current_user
from shorts_api.lifecycle import REDIS_URL


router = APIRouter(prefix="/release", tags=["release"])
ALEMBIC_REVISION_PATH = Path("/app/alembic-revision")


class ServiceIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ApiIdentity(ServiceIdentity):
    alembic_revision: str


async def load_worker_identity() -> ServiceIdentity:
    client: AsyncRedis = AsyncRedis.from_url(REDIS_URL, decode_responses=True)
    try:
        values = await client.hgetall("release:worker-identity")
    finally:
        await client.aclose()
    return ServiceIdentity(source_sha=values["source_sha"], digest=values["digest"])


async def resolve_worker_identity() -> ServiceIdentity:
    try:
        return await load_worker_identity()
    except (KeyError, RedisError, ValidationError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker identity unavailable",
        ) from error


@router.get("/identity", response_model=ApiIdentity)
async def api_identity(_user: CurrentUser = Depends(get_current_user)) -> ApiIdentity:
    try:
        revision = ALEMBIC_REVISION_PATH.read_text().strip()
    except OSError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Release identity unavailable",
        ) from error
    try:
        return ApiIdentity(
            source_sha=os.environ["SOURCE_SHA"],
            digest=os.environ["API_IMAGE_DIGEST"],
            alembic_revision=revision,
        )
    except (KeyError, ValidationError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Release identity unavailable",
        ) from error


@router.get("/worker-identity", response_model=ServiceIdentity)
async def worker_identity(
    identity: ServiceIdentity = Depends(resolve_worker_identity),
    _user: CurrentUser = Depends(get_current_user),
) -> ServiceIdentity:
    return identity
