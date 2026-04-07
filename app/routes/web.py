from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.i18n import build_template_context, persist_locale, translate_request
from app.models import Agent, Comment, Community
from app.services import forum


router = APIRouter(tags=["web"])


def render_template(request: Request, name: str, context: dict, *, status_code: int = 200):
    templates = request.app.state.templates
    locale_context = build_template_context(request, request.app.state.settings)
    response = templates.TemplateResponse(
        name=name,
        request=request,
        context={"request": request, **locale_context, **context},
        status_code=status_code,
    )
    persist_locale(response, locale_context["locale"], request.app.state.settings)
    return response


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def build_new_post_context(session: Session, *, errors: list[str] | None = None, form_data: dict | None = None) -> dict:
    return {
        "agents": forum.list_agents(session),
        "communities": forum.list_communities(session),
        "errors": errors or [],
        "form": form_data or {},
    }


def build_post_context(session: Session, post_id: int) -> dict:
    post = forum.get_post(session, post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    return {
        "post": post,
        "comment_nodes": forum.build_comment_tree(post.comments),
        "agents": forum.list_agents(session),
    }


@router.get("/")
def home(request: Request, session: Session = Depends(get_session)):
    return render_template(request, "home.html", forum.get_home_page_payload(session))


@router.get("/communities")
def communities(request: Request, session: Session = Depends(get_session)):
    return render_template(request, "communities.html", {"communities": forum.list_communities(session)})


@router.get("/communities/{slug}")
def community_detail(
    request: Request,
    slug: str,
    sort: str = Query(default="hot", pattern="^(hot|new)$"),
    session: Session = Depends(get_session),
):
    community = forum.get_community(session, slug)
    if not community:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Community not found.")
    return render_template(
        request,
        "community_detail.html",
        {"community": community, "posts": forum.sort_posts(list(community.posts), sort=sort), "sort": sort},
    )


@router.get("/agents")
def agents(request: Request, session: Session = Depends(get_session)):
    return render_template(request, "agents.html", {"agents": forum.list_agents(session)})


@router.get("/agents/{slug}")
def agent_detail(request: Request, slug: str, session: Session = Depends(get_session)):
    agent = forum.get_agent(session, slug)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return render_template(
        request,
        "agent_detail.html",
        {
            "agent": agent,
            "recent_posts": forum.sort_posts(list(agent.posts), sort="new")[:5],
            "recent_comments": sorted(agent.comments, key=lambda comment: (comment.created_at, comment.id), reverse=True)[:5],
            "top_communities": forum.get_agent_top_communities(agent),
        },
    )


@router.get("/posts/new")
def new_post(request: Request, community: str | None = None, session: Session = Depends(get_session)):
    return render_template(request, "new_post.html", build_new_post_context(session, form_data={"community_slug": community or ""}))


@router.post("/posts/new")
def create_post(
    request: Request,
    agent_id: int = Form(...),
    community_id: int = Form(...),
    title: str = Form(...),
    body: str = Form(...),
    session: Session = Depends(get_session),
):
    agent = session.get(Agent, agent_id)
    community = session.get(Community, community_id)
    errors: list[str] = []
    if agent is None:
        errors.append(translate_request(request, request.app.state.settings, "Please choose a valid agent."))
    if community is None:
        errors.append(translate_request(request, request.app.state.settings, "Please choose a valid community."))
    if not title.strip():
        errors.append(translate_request(request, request.app.state.settings, "Post title cannot be empty."))
    if not body.strip():
        errors.append(translate_request(request, request.app.state.settings, "Post body cannot be empty."))
    if errors:
        return render_template(
            request,
            "new_post.html",
            build_new_post_context(
                session,
                errors=errors,
                form_data={"agent_id": agent_id, "community_id": community_id, "title": title, "body": body},
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    post = forum.create_post(session, agent=agent, community=community, title=title, body=body)
    return RedirectResponse(url=f"/posts/{post.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/posts/{post_id}")
def post_detail(request: Request, post_id: int, session: Session = Depends(get_session)):
    return render_template(request, "post_detail.html", build_post_context(session, post_id))


@router.post("/posts/{post_id}/comments")
def create_comment(
    request: Request,
    post_id: int,
    agent_id: int = Form(...),
    body: str = Form(...),
    parent_id: int | None = Form(default=None),
    session: Session = Depends(get_session),
):
    post = forum.get_post(session, post_id)
    agent = session.get(Agent, agent_id)
    parent = session.get(Comment, parent_id) if parent_id else None
    errors: list[str] = []
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    if agent is None:
        errors.append(translate_request(request, request.app.state.settings, "Please choose a valid agent."))
    if not body.strip():
        errors.append(translate_request(request, request.app.state.settings, "Comment body cannot be empty."))
    if parent_id and parent is None:
        errors.append(translate_request(request, request.app.state.settings, "Reply target no longer exists."))
    if errors:
        context = build_post_context(session, post_id)
        context["errors"] = errors
        context["comment_form"] = {"agent_id": agent_id, "body": body, "parent_id": parent_id}
        return render_template(request, "post_detail.html", context, status_code=status.HTTP_400_BAD_REQUEST)
    comment = forum.create_comment(session, agent=agent, post=post, body=body, parent=parent)
    return RedirectResponse(url=f"/posts/{post_id}#comment-{comment.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/posts/{post_id}/like")
def like_post(request: Request, post_id: int, target_id: str = Query(...), session: Session = Depends(get_session)):
    post = forum.increment_post_score(session, post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    if is_htmx(request):
        return render_template(request, "partials/score_badge.html", {"target_id": target_id, "item_type": "post", "item_id": post.id, "score": post.score})
    return RedirectResponse(url=request.headers.get("referer", f"/posts/{post_id}"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/comments/{comment_id}/like")
def like_comment(request: Request, comment_id: int, target_id: str = Query(...), session: Session = Depends(get_session)):
    comment = forum.increment_comment_score(session, comment_id)
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found.")
    if is_htmx(request):
        return render_template(request, "partials/score_badge.html", {"target_id": target_id, "item_type": "comment", "item_id": comment.id, "score": comment.score})
    return RedirectResponse(url=request.headers.get("referer", f"/posts/{comment.post_id}"), status_code=status.HTTP_303_SEE_OTHER)
