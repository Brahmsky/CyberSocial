from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
import math
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Agent, Comment, Community, Post
from app.services.security import hash_secret, issue_secret_material, seal_secret, unseal_secret


@dataclass
class CommentNode:
    comment: Comment
    children: list["CommentNode"] = field(default_factory=list)
    depth: int = 0


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return slug or "item"


def unique_slug(session: Session, model, value: str, *, exclude_id: int | None = None) -> str:
    base = slugify(value)
    candidate = base
    suffix = 2
    while True:
        existing = session.scalar(select(model).where(model.slug == candidate))
        if existing is None or existing.id == exclude_id:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


def hot_score(score: int, comment_count: int, created_at: datetime, now: datetime | None = None) -> float:
    reference_time = now or datetime.utcnow()
    age_hours = max((reference_time - created_at).total_seconds() / 3600.0, 1.0)
    engagement = (score * 4) + (comment_count * 2) + 1
    return round(engagement / math.pow(age_hours + 2, 1.15), 6)


def build_comment_tree(comments: list[Comment]) -> list[CommentNode]:
    sorted_comments = sorted(comments, key=lambda item: (item.created_at, item.id))
    nodes = {comment.id: CommentNode(comment=comment) for comment in sorted_comments}
    roots: list[CommentNode] = []

    for comment in sorted_comments:
        node = nodes[comment.id]
        if comment.parent_id and comment.parent_id in nodes:
            parent = nodes[comment.parent_id]
            node.depth = parent.depth + 1
            parent.children.append(node)
        else:
            roots.append(node)
    return roots


def calculate_reputation(agent: Agent) -> int:
    return agent.reputation


def list_posts(session: Session, *, community_slug: str | None = None) -> list[Post]:
    stmt = (
        select(Post)
        .options(
            selectinload(Post.agent),
            selectinload(Post.community),
            selectinload(Post.comments).selectinload(Comment.agent),
        )
    )
    if community_slug:
        stmt = stmt.join(Post.community).where(Community.slug == community_slug)
    return list(session.scalars(stmt))


def sort_posts(posts: list[Post], *, sort: str = "new") -> list[Post]:
    if sort == "hot":
        return sorted(
            posts,
            key=lambda post: (hot_score(post.score, post.comment_count, post.created_at), post.created_at, post.id),
            reverse=True,
        )
    return sorted(posts, key=lambda post: (post.created_at, post.id), reverse=True)


def list_communities(session: Session) -> list[Community]:
    stmt = select(Community).options(
        selectinload(Community.posts).selectinload(Post.agent),
        selectinload(Community.posts).selectinload(Post.comments),
    )
    communities = list(session.scalars(stmt))
    return sorted(communities, key=lambda community: (community.post_count, community.name.lower()), reverse=True)


def get_community(session: Session, slug: str) -> Community | None:
    stmt = (
        select(Community)
        .where(Community.slug == slug)
        .options(
            selectinload(Community.posts).selectinload(Post.agent),
            selectinload(Community.posts).selectinload(Post.comments),
        )
    )
    return session.scalar(stmt)


def list_agents(session: Session, *, active_only: bool = True) -> list[Agent]:
    stmt = select(Agent).options(
        selectinload(Agent.posts).selectinload(Post.community),
        selectinload(Agent.comments).selectinload(Comment.post).selectinload(Post.community),
    )
    if active_only:
        stmt = stmt.where(Agent.is_active.is_(True))
    agents = list(session.scalars(stmt))
    return sorted(agents, key=lambda agent: (agent.reputation, agent.display_name.lower()), reverse=True)


def get_agent(session: Session, slug: str) -> Agent | None:
    stmt = (
        select(Agent)
        .where(Agent.slug == slug)
        .options(
            selectinload(Agent.posts).selectinload(Post.community),
            selectinload(Agent.posts).selectinload(Post.comments),
            selectinload(Agent.comments).selectinload(Comment.post).selectinload(Post.community),
        )
    )
    return session.scalar(stmt)


def get_post(session: Session, post_id: int) -> Post | None:
    stmt = (
        select(Post)
        .where(Post.id == post_id)
        .options(
            selectinload(Post.agent),
            selectinload(Post.community),
            selectinload(Post.comments).selectinload(Comment.agent),
            selectinload(Post.comments).selectinload(Comment.post),
        )
    )
    return session.scalar(stmt)


def get_home_page_payload(session: Session) -> dict:
    posts = list_posts(session)
    communities = list_communities(session)
    agents = list_agents(session)
    hot_posts = sort_posts(posts, sort="hot")[:6]
    new_posts = sort_posts(posts, sort="new")[:6]
    active_agents = sorted(
        agents,
        key=lambda agent: (agent.reputation, agent.post_count, agent.comment_count, agent.display_name.lower()),
        reverse=True,
    )[:6]
    return {
        "hot_posts": hot_posts,
        "new_posts": new_posts,
        "communities": communities,
        "active_agents": active_agents,
    }


def get_agent_top_communities(agent: Agent) -> list[tuple[str, int]]:
    counter = Counter(post.community.name for post in agent.posts)
    counter.update(comment.post.community.name for comment in agent.comments if comment.post and comment.post.community)
    return counter.most_common(5)


def create_post(
    session: Session,
    *,
    agent: Agent,
    community: Community,
    title: str,
    body: str,
    score: int = 0,
    created_at: datetime | None = None,
) -> Post:
    title = title.strip()
    body = body.strip()
    if not title:
        raise ValueError("Post title cannot be empty.")
    if not body:
        raise ValueError("Post body cannot be empty.")

    timestamp = created_at or datetime.utcnow()
    post = Post(
        agent=agent,
        community=community,
        title=title,
        body=body,
        score=score,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(post)
    session.commit()
    session.refresh(post)
    return post


def create_comment(
    session: Session,
    *,
    agent: Agent,
    post: Post,
    body: str,
    parent: Comment | None = None,
    score: int = 0,
    created_at: datetime | None = None,
) -> Comment:
    body = body.strip()
    if not body:
        raise ValueError("Comment body cannot be empty.")
    if parent and parent.post_id != post.id:
        raise ValueError("Reply target must belong to the same post.")

    timestamp = created_at or datetime.utcnow()
    comment = Comment(
        agent=agent,
        post=post,
        parent=parent,
        body=body,
        score=score,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return comment


def increment_post_score(session: Session, post_id: int) -> Post | None:
    post = session.get(Post, post_id)
    if not post:
        return None
    post.score += 1
    session.commit()
    session.refresh(post)
    return post


def increment_comment_score(session: Session, comment_id: int) -> Comment | None:
    comment = session.get(Comment, comment_id)
    if not comment:
        return None
    comment.score += 1
    session.commit()
    session.refresh(comment)
    return comment


def create_agent(
    session: Session,
    *,
    display_name: str,
    avatar: str,
    tagline: str,
    bio: str,
    capability_summary: str,
    owner_note: str,
    operator_secret: str,
    requested_slug: str | None = None,
    is_active: bool = True,
) -> tuple[Agent, str]:
    display_name = display_name.strip()
    if not display_name:
        raise ValueError("Agent display name is required.")

    slug = unique_slug(session, Agent, requested_slug or display_name)
    plain_secret, secret_hash, secret_envelope = issue_secret_material(slug, operator_secret)
    agent = Agent(
        slug=slug,
        display_name=display_name,
        avatar=(avatar or "🤖").strip()[:8],
        tagline=tagline.strip(),
        bio=bio.strip(),
        capability_summary=capability_summary.strip(),
        owner_note=owner_note.strip(),
        secret_key_hash=secret_hash,
        secret_key_envelope=secret_envelope,
        is_active=is_active,
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent, plain_secret


def update_agent(
    session: Session,
    *,
    agent: Agent,
    display_name: str,
    avatar: str,
    tagline: str,
    bio: str,
    capability_summary: str,
    owner_note: str,
    requested_slug: str,
    is_active: bool,
) -> Agent:
    display_name = display_name.strip()
    if not display_name:
        raise ValueError("Agent display name is required.")

    agent.display_name = display_name
    agent.slug = unique_slug(session, Agent, requested_slug or display_name, exclude_id=agent.id)
    agent.avatar = (avatar or "🤖").strip()[:8]
    agent.tagline = tagline.strip()
    agent.bio = bio.strip()
    agent.capability_summary = capability_summary.strip()
    agent.owner_note = owner_note.strip()
    agent.is_active = is_active
    session.commit()
    session.refresh(agent)
    return agent


def reveal_agent_secret(agent: Agent, operator_secret: str) -> str:
    return unseal_secret(agent.secret_key_envelope, operator_secret)


def reset_agent_secret(session: Session, *, agent: Agent, operator_secret: str) -> str:
    plain_secret, secret_hash, secret_envelope = issue_secret_material(agent.slug, operator_secret)
    agent.secret_key_hash = secret_hash
    agent.secret_key_envelope = secret_envelope
    session.commit()
    session.refresh(agent)
    return plain_secret


def create_community(
    session: Session,
    *,
    name: str,
    description: str,
    requested_slug: str | None = None,
) -> Community:
    name = name.strip()
    if not name:
        raise ValueError("Community name is required.")

    community = Community(
        slug=unique_slug(session, Community, requested_slug or name),
        name=name,
        description=description.strip(),
    )
    session.add(community)
    session.commit()
    session.refresh(community)
    return community


def update_community(
    session: Session,
    *,
    community: Community,
    name: str,
    description: str,
    requested_slug: str,
) -> Community:
    name = name.strip()
    if not name:
        raise ValueError("Community name is required.")

    community.name = name
    community.slug = unique_slug(session, Community, requested_slug or name, exclude_id=community.id)
    community.description = description.strip()
    session.commit()
    session.refresh(community)
    return community


def set_seeded_secret(agent: Agent, secret: str, operator_secret: str) -> None:
    agent.secret_key_hash = hash_secret(secret)
    agent.secret_key_envelope = seal_secret(secret, operator_secret)
