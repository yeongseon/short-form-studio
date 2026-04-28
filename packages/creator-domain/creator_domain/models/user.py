from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class User(BaseModel):
    id: int
    email: str
    name: str | None = None
    auth_provider: str = "api_key"
    auth_subject: str = ""
    created_at: datetime
    updated_at: datetime


class Workspace(BaseModel):
    id: int
    name: str
    slug: str
    owner_id: int
    created_at: datetime
    updated_at: datetime


class WorkspaceMember(BaseModel):
    workspace_id: int
    user_id: int
    role: Literal["member", "admin", "owner"] = "member"
    joined_at: datetime
