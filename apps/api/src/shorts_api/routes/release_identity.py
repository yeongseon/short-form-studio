import os
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis

from shorts_api.auth import CurrentUser, get_current_user
from shorts_api.lifecycle import REDIS_URL


router = APIRouter(prefix="/release", tags=["release"])
ALEMBIC_REVISION_PATH = Path("/app/alembic-revision")


class ServiceIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_sha: str
    digest: str


class ApiIdentity(ServiceIdentity):
    alembic_revision: str


async def load_worker_identity() -> ServiceIdentity:
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        values = await client.hgetall("release:worker-identity")
    finally:
        await client.aclose()
    return ServiceIdentity(source_sha=values["source_sha"], digest=values["digest"])


@router.get("/identity", response_model=ApiIdentity)
async def api_identity(_user: CurrentUser = Depends(get_current_user)) -> ApiIdentity:
    revision = ALEMBIC_REVISION_PATH.read_text().strip()
    return ApiIdentity(
        source_sha=os.environ["SOURCE_SHA"],
        digest=os.environ["API_IMAGE_DIGEST"],
        alembic_revision=revision,
    )


@router.get("/worker-identity", response_model=ServiceIdentity)
async def worker_identity(
    identity: ServiceIdentity = Depends(load_worker_identity),
    _user: CurrentUser = Depends(get_current_user),
) -> ServiceIdentity:
    return identity
