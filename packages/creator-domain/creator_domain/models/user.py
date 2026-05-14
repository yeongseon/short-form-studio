from datetime import datetime
from typing import ClassVar
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    email: str = Field(max_length=255)
    name: str | None = None
    workspace_id: int | None = Field(default=None, ge=1)
    auth_provider: str = "api_key"
    auth_subject: str = ""
    created_at: datetime
    updated_at: datetime


class Workspace(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    name: str
    slug: str = Field(max_length=100)
    owner_id: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class WorkspaceMember(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    workspace_id: int = Field(ge=1)
    user_id: int = Field(ge=1)
    role: Literal["member", "admin", "owner"] = "member"
    joined_at: datetime
