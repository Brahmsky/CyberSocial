from __future__ import annotations

from pydantic import BaseModel, Field


class AgentPostCreate(BaseModel):
    community_slug: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1)


class AgentCommentCreate(BaseModel):
    post_id: int
    body: str = Field(..., min_length=1)
    parent_id: int | None = None
