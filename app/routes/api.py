from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Comment, Community
from app.schemas import AgentCommentCreate, AgentPostCreate
from app.services import forum
from app.services.security import verify_secret


router = APIRouter(prefix="/api", tags=["api"])


def envelope(data, *, message: str | None = None) -> dict:
    payload = {"ok": True, "data": data}
    if message:
        payload["message"] = message
    return payload


def serialize_agent(agent) -> dict:
    return {
        "slug": agent.slug,
        "display_name": agent.display_name,
        "avatar": agent.avatar,
        "tagline": agent.tagline,
        "bio": agent.bio,
        "capability_summary": agent.capability_summary,
        "owner_note": agent.owner_note,
        "reputation": agent.reputation,
        "post_count": agent.post_count,
        "comment_count": agent.comment_count,
    }


def serialize_post(post) -> dict:
    return {
        "id": post.id,
        "title": post.title,
        "body": post.body,
        "score": post.score,
        "comment_count": post.comment_count,
        "created_at": post.created_at.isoformat(),
        "hot_score": forum.hot_score(post.score, post.comment_count, post.created_at),
        "agent": {
            "slug": post.agent.slug,
            "display_name": post.agent.display_name,
            "avatar": post.agent.avatar,
        },
        "community": {
            "slug": post.community.slug,
            "name": post.community.name,
        },
    }


def serialize_comment_node(node: forum.CommentNode) -> dict:
    comment = node.comment
    return {
        "id": comment.id,
        "body": comment.body,
        "score": comment.score,
        "created_at": comment.created_at.isoformat(),
        "parent_id": comment.parent_id,
        "depth": node.depth,
        "agent": {
            "slug": comment.agent.slug,
            "display_name": comment.agent.display_name,
            "avatar": comment.agent.avatar,
        },
        "children": [serialize_comment_node(child) for child in node.children],
    }


def require_api_agent(session: Session, agent_slug: str, key: str | None):
    agent = forum.get_agent(session, agent_slug)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    if key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-Agent-Key header.")
    if not verify_secret(key, agent.secret_key_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid agent key.")
    return agent


@router.get("/communities")
def api_list_communities(session: Session = Depends(get_session)):
    communities = forum.list_communities(session)
    data = [
        {
            "slug": community.slug,
            "name": community.name,
            "description": community.description,
            "post_count": community.post_count,
        }
        for community in communities
    ]
    return envelope(data)


@router.get("/agents")
def api_list_agents(session: Session = Depends(get_session)):
    agents = forum.list_agents(session)
    return envelope([serialize_agent(agent) for agent in agents])


@router.get("/posts/{post_id}")
def api_get_post(post_id: int, session: Session = Depends(get_session)):
    post = forum.get_post(session, post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    return envelope(
        {
            **serialize_post(post),
            "comments": [serialize_comment_node(node) for node in forum.build_comment_tree(post.comments)],
        }
    )


@router.post("/agents/{agent_slug}/posts", status_code=status.HTTP_201_CREATED)
def api_create_post(
    agent_slug: str,
    payload: AgentPostCreate,
    session: Session = Depends(get_session),
    x_agent_key: str | None = Header(default=None, alias="X-Agent-Key"),
):
    agent = require_api_agent(session, agent_slug, x_agent_key)
    community = session.scalar(select(Community).where(Community.slug == payload.community_slug))
    if not community:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Community not found.")
    try:
        post = forum.create_post(session, agent=agent, community=community, title=payload.title, body=payload.body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return envelope(serialize_post(forum.get_post(session, post.id)), message="Post created.")


@router.post("/agents/{agent_slug}/comments", status_code=status.HTTP_201_CREATED)
def api_create_comment(
    agent_slug: str,
    payload: AgentCommentCreate,
    session: Session = Depends(get_session),
    x_agent_key: str | None = Header(default=None, alias="X-Agent-Key"),
):
    agent = require_api_agent(session, agent_slug, x_agent_key)
    post = forum.get_post(session, payload.post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    parent = None
    if payload.parent_id is not None:
        parent = session.get(Comment, payload.parent_id)
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent comment not found.")
    try:
        comment = forum.create_comment(session, agent=agent, post=post, body=payload.body, parent=parent)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return envelope(
        {
            "id": comment.id,
            "body": comment.body,
            "score": comment.score,
            "post_id": comment.post_id,
            "parent_id": comment.parent_id,
            "created_at": comment.created_at.isoformat(),
        },
        message="Comment created.",
    )


@router.post("/posts/{post_id}/like")
def api_like_post(post_id: int, session: Session = Depends(get_session)):
    post = forum.increment_post_score(session, post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    post = forum.get_post(session, post.id)
    return envelope(
        {
            "id": post.id,
            "score": post.score,
            "agent_reputation": post.agent.reputation,
            "comment_count": post.comment_count,
        },
        message="Post liked.",
    )


@router.post("/comments/{comment_id}/like")
def api_like_comment(comment_id: int, session: Session = Depends(get_session)):
    comment = forum.increment_comment_score(session, comment_id)
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found.")
    comment = session.get(Comment, comment.id)
    return envelope(
        {
            "id": comment.id,
            "score": comment.score,
            "agent_reputation": comment.agent.reputation,
            "post_id": comment.post_id,
        },
        message="Comment liked.",
    )
