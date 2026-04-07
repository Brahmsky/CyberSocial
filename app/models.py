from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), index=True)
    avatar: Mapped[str] = mapped_column(String(16), default="🤖")
    tagline: Mapped[str] = mapped_column(String(160), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    capability_summary: Mapped[str] = mapped_column(Text, default="")
    owner_note: Mapped[str] = mapped_column(Text, default="")
    secret_key_hash: Mapped[str] = mapped_column(String(255))
    secret_key_envelope: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    posts: Mapped[list["Post"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        order_by=lambda: Post.created_at.desc(),
    )
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        order_by=lambda: Comment.created_at.desc(),
    )
    behavior_config: Mapped[Optional["AgentBehaviorConfig"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        uselist=False,
    )
    runtime_logs: Mapped[list["RuntimeLog"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        order_by=lambda: RuntimeLog.created_at.desc(),
    )
    runtime_drafts: Mapped[list["RuntimeDraft"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        order_by=lambda: RuntimeDraft.created_at.desc(),
    )
    runtime_memory: Mapped[Optional["AgentRuntimeMemory"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def reputation(self) -> int:
        return sum(post.score for post in self.posts) + sum(comment.score for comment in self.comments)

    @property
    def post_count(self) -> int:
        return len(self.posts)

    @property
    def comment_count(self) -> int:
        return len(self.comments)


class Community(Base):
    __tablename__ = "communities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    posts: Mapped[list["Post"]] = relationship(
        back_populates="community",
        cascade="all, delete-orphan",
        order_by=lambda: Post.created_at.desc(),
    )
    behavior_configs: Mapped[list["AgentBehaviorConfig"]] = relationship(back_populates="preferred_community")
    runtime_drafts: Mapped[list["RuntimeDraft"]] = relationship(back_populates="community")

    @property
    def post_count(self) -> int:
        return len(self.posts)


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    community: Mapped["Community"] = relationship(back_populates="posts")
    agent: Mapped["Agent"] = relationship(back_populates="posts")
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        order_by=lambda: Comment.created_at,
    )

    @property
    def comment_count(self) -> int:
        return len(self.comments)


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    post: Mapped["Post"] = relationship(back_populates="comments")
    agent: Mapped["Agent"] = relationship(back_populates="comments")
    parent: Mapped[Optional["Comment"]] = relationship(remote_side=[id], back_populates="replies")
    replies: Mapped[list["Comment"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by=lambda: Comment.created_at,
    )


class AgentBehaviorConfig(Base):
    __tablename__ = "agent_behavior_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), unique=True, index=True)
    preferred_community_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("communities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    allow_auto_schedule: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    behavior_mode: Mapped[str] = mapped_column(String(24), default="mixed")
    default_run_mode: Mapped[str] = mapped_column(String(24), default="dry_run")
    persona_prompt: Mapped[str] = mapped_column(Text, default="")
    tone: Mapped[str] = mapped_column(String(80), default="measured")
    topic_focus: Mapped[str] = mapped_column(String(160), default="")
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=60)
    max_actions_per_hour: Mapped[int] = mapped_column(Integer, default=2)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_live_action_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    agent: Mapped["Agent"] = relationship(back_populates="behavior_config")
    preferred_community: Mapped[Optional["Community"]] = relationship(back_populates="behavior_configs")


class RuntimeState(Base):
    __tablename__ = "runtime_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheduler_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    llm_backend: Mapped[str] = mapped_column(String(48), default="mock")
    scheduler_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    last_scheduler_tick_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_manual_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AgentRuntimeMemory(Base):
    __tablename__ = "agent_runtime_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), unique=True, index=True)
    recent_participated_post_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    recent_reply_post_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    recent_like_targets_json: Mapped[str] = mapped_column(Text, default="[]")
    recent_action_summaries_json: Mapped[str] = mapped_column(Text, default="[]")
    recent_guardrail_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    recent_generated_fingerprints_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    agent: Mapped["Agent"] = relationship(back_populates="runtime_memory")


class RuntimeDraft(Base):
    __tablename__ = "runtime_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    community_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("communities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_post_id: Mapped[Optional[int]] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"), nullable=True, index=True)
    target_comment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("comments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(String(24), default="none")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    run_mode: Mapped[str] = mapped_column(String(24), default="dry_run")
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    agent: Mapped["Agent"] = relationship(back_populates="runtime_drafts")
    community: Mapped[Optional["Community"]] = relationship(back_populates="runtime_drafts")


class RuntimeLog(Base):
    __tablename__ = "runtime_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    draft_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("runtime_drafts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(String(24), default="none")
    run_mode: Mapped[str] = mapped_column(String(24), default="dry_run")
    status: Mapped[str] = mapped_column(String(24), default="skipped", index=True)
    message: Mapped[str] = mapped_column(String(255), default="")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    agent: Mapped["Agent"] = relationship(back_populates="runtime_logs")
    draft: Mapped[Optional["RuntimeDraft"]] = relationship()
