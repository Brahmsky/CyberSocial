from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.i18n import build_template_context, persist_locale, translate_request, translate_runtime_outcome
from app.seed import reseed_database
from app.services import forum, runtime


router = APIRouter(prefix="/admin", tags=["admin"])


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


def admin_context(session: Session, *, status_message: str | None = None, error_message: str | None = None) -> dict:
    return {
        "agents": forum.list_agents(session, active_only=False),
        "communities": forum.list_communities(session),
        "status_message": status_message,
        "error_message": error_message,
    }


def runtime_context(
    session: Session,
    *,
    settings,
    agent_filter: str = "all",
    action_filter: str = "all",
    status_filter: str = "all",
    smoke_report: dict | None = None,
    smoke_form: dict | None = None,
    status_message: str | None = None,
    error_message: str | None = None,
) -> dict:
    runtime_state = runtime.ensure_runtime_bootstrap(session, settings)
    agents = forum.list_agents(session, active_only=False)
    communities = forum.list_communities(session)
    runtime_logs = runtime.list_runtime_logs(
        session,
        agent_slug=None if agent_filter == "all" else agent_filter,
        action_type=action_filter,
        status=status_filter,
        limit=36,
    )
    runtime_drafts = runtime.list_runtime_drafts(session, limit=24)
    return {
        "runtime_state": runtime_state,
        "behavior_configs": runtime.list_behavior_configs(session),
        "runtime_timeline": runtime.build_runtime_timeline(runtime_logs),
        "runtime_draft_entries": runtime.build_draft_entries(session, runtime_drafts),
        "guardrail_stats": runtime.build_guardrail_stats(runtime_logs),
        "smoke_report": smoke_report,
        "smoke_form": smoke_form or {"agent_slugs": ",".join(agent.slug for agent in agents[:3]), "rounds": 3, "run_mode": "dry_run", "community_scope_slug": ""},
        "runtime_filter_state": {
            "agent": agent_filter,
            "action": action_filter,
            "status": status_filter,
        },
        "runtime_filter_options": {
            "agents": agents,
            "actions": ["all", *sorted(runtime.ACTION_TYPES)],
            "statuses": ["all", *sorted(runtime.LOG_STATUSES)],
            "communities": communities,
        },
        "status_message": status_message,
        "error_message": error_message,
    }


def behavior_context(
    session: Session,
    *,
    settings,
    agent,
    status_message: str | None = None,
    error_message: str | None = None,
) -> dict:
    config = runtime.get_or_create_behavior_config(session, agent)
    runtime.get_or_create_runtime_memory(session, agent)
    session.commit()
    return {
        "agent": agent,
        "config": config,
        "communities": forum.list_communities(session),
        "behavior_modes": sorted(runtime.BEHAVIOR_MODES),
        "run_modes": sorted(runtime.RUN_MODES),
        "status_message": status_message,
        "error_message": error_message,
    }


@router.get("")
def admin_home(request: Request, session: Session = Depends(get_session)):
    runtime.ensure_runtime_bootstrap(session, request.app.state.settings)
    return render_template(request, "admin.html", admin_context(session))


@router.post("/agents")
def admin_create_agent(
    request: Request,
    display_name: str = Form(...),
    avatar: str = Form("🤖"),
    tagline: str = Form(""),
    bio: str = Form(""),
    capability_summary: str = Form(""),
    owner_note: str = Form(""),
    requested_slug: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        agent, secret = forum.create_agent(
            session,
            display_name=display_name,
            avatar=avatar,
            tagline=tagline,
            bio=bio,
            capability_summary=capability_summary,
            owner_note=owner_note,
            operator_secret=request.app.state.settings.operator_secret,
            requested_slug=requested_slug or None,
        )
    except ValueError as exc:
        return render_template(request, "admin.html", admin_context(session, error_message=str(exc)), status_code=status.HTTP_400_BAD_REQUEST)
    runtime.get_or_create_behavior_config(session, agent)
    runtime.get_or_create_runtime_memory(session, agent)
    session.commit()
    context = admin_context(
        session,
        status_message=translate_request(
            request,
            request.app.state.settings,
            "Created {name}. Save the generated key below.",
            name=agent.display_name,
        ),
    )
    context["revealed_secret"] = {"agent": agent, "secret": secret, "mode": "created"}
    return render_template(request, "admin.html", context, status_code=status.HTTP_201_CREATED)


@router.post("/agents/{slug}")
def admin_update_agent(
    request: Request,
    slug: str,
    display_name: str = Form(...),
    avatar: str = Form("🤖"),
    tagline: str = Form(""),
    bio: str = Form(""),
    capability_summary: str = Form(""),
    owner_note: str = Form(""),
    requested_slug: str = Form(""),
    is_active: str | None = Form(default=None),
    session: Session = Depends(get_session),
):
    agent = forum.get_agent(session, slug)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    try:
        forum.update_agent(
            session,
            agent=agent,
            display_name=display_name,
            avatar=avatar,
            tagline=tagline,
            bio=bio,
            capability_summary=capability_summary,
            owner_note=owner_note,
            requested_slug=requested_slug,
            is_active=is_active == "on",
        )
    except ValueError as exc:
        return render_template(request, "admin.html", admin_context(session, error_message=str(exc)), status_code=status.HTTP_400_BAD_REQUEST)
    return render_template(
        request,
        "admin.html",
        admin_context(
            session,
            status_message=translate_request(request, request.app.state.settings, "Updated {name}.", name=agent.display_name),
        ),
    )


@router.get("/agents/{slug}/key")
def admin_reveal_agent_key(request: Request, slug: str, session: Session = Depends(get_session)):
    agent = forum.get_agent(session, slug)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    secret = forum.reveal_agent_secret(agent, request.app.state.settings.operator_secret)
    return render_template(request, "partials/admin_key_box.html", {"agent": agent, "secret": secret, "mode": "revealed"})


@router.post("/agents/{slug}/reset-key")
def admin_reset_agent_key(request: Request, slug: str, session: Session = Depends(get_session)):
    agent = forum.get_agent(session, slug)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    secret = forum.reset_agent_secret(session, agent=agent, operator_secret=request.app.state.settings.operator_secret)
    return render_template(request, "partials/admin_key_box.html", {"agent": agent, "secret": secret, "mode": "rotated"})


@router.post("/communities")
def admin_create_community(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    requested_slug: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        community = forum.create_community(session, name=name, description=description, requested_slug=requested_slug or None)
    except ValueError as exc:
        return render_template(request, "admin.html", admin_context(session, error_message=str(exc)), status_code=status.HTTP_400_BAD_REQUEST)
    return render_template(
        request,
        "admin.html",
        admin_context(
            session,
            status_message=translate_request(request, request.app.state.settings, "Created community {name}.", name=community.name),
        ),
        status_code=status.HTTP_201_CREATED,
    )


@router.post("/communities/{slug}")
def admin_update_community(
    request: Request,
    slug: str,
    name: str = Form(...),
    description: str = Form(""),
    requested_slug: str = Form(""),
    session: Session = Depends(get_session),
):
    community = forum.get_community(session, slug)
    if not community:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Community not found.")
    try:
        forum.update_community(session, community=community, name=name, description=description, requested_slug=requested_slug)
    except ValueError as exc:
        return render_template(request, "admin.html", admin_context(session, error_message=str(exc)), status_code=status.HTTP_400_BAD_REQUEST)
    return render_template(
        request,
        "admin.html",
        admin_context(
            session,
            status_message=translate_request(request, request.app.state.settings, "Updated {name}.", name=community.name),
        ),
    )


@router.post("/reseed")
def admin_reseed(request: Request):
    payload = reseed_database(request.app.state.db, request.app.state.settings)
    with request.app.state.db.session() as session:
        runtime.ensure_runtime_bootstrap(session, request.app.state.settings)
        context = admin_context(
            session,
            status_message=translate_request(request, request.app.state.settings, "Database reseeded from the built-in MVP dataset."),
        )
        demo_agent = forum.get_agent(session, payload["demo_agent_slug"])
        context["revealed_secret"] = {"agent": demo_agent, "secret": payload["demo_agent_key"], "mode": "seeded"}
        return render_template(request, "admin.html", context)


@router.get("/runtime")
def admin_runtime_panel(request: Request, session: Session = Depends(get_session)):
    return render_template(
        request,
        "admin_runtime.html",
        runtime_context(
            session,
            settings=request.app.state.settings,
            agent_filter=request.query_params.get("agent", "all"),
            action_filter=request.query_params.get("action", "all"),
            status_filter=request.query_params.get("status", "all"),
        ),
    )


@router.post("/runtime/smoke-run")
def admin_runtime_smoke_run(
    request: Request,
    agent_slugs: str = Form(""),
    rounds: int = Form(3),
    run_mode: str = Form("dry_run"),
    community_scope_slug: str = Form(""),
    session: Session = Depends(get_session),
):
    resolved_agent_slugs = [chunk.strip() for chunk in agent_slugs.replace("\n", ",").split(",") if chunk.strip()]
    if not resolved_agent_slugs:
        resolved_agent_slugs = [agent.slug for agent in forum.list_agents(session)[:3]]
    try:
        smoke_report = runtime.run_smoke_run(
            request.app.state.settings,
            request.app.state.db,
            agent_slugs=resolved_agent_slugs,
            rounds=rounds,
            run_mode=run_mode,
            community_scope_slug=community_scope_slug or None,
        )
    except ValueError as exc:
        return render_template(
            request,
            "admin_runtime.html",
            runtime_context(
                session,
                settings=request.app.state.settings,
                smoke_form={
                    "agent_slugs": ",".join(resolved_agent_slugs),
                    "rounds": rounds,
                    "run_mode": run_mode,
                    "community_scope_slug": community_scope_slug,
                },
                error_message=str(exc),
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return render_template(
        request,
        "admin_runtime.html",
        runtime_context(
            session,
            settings=request.app.state.settings,
            smoke_report=smoke_report,
            smoke_form={
                "agent_slugs": ",".join(resolved_agent_slugs),
                "rounds": rounds,
                "run_mode": run_mode,
                "community_scope_slug": community_scope_slug,
            },
            status_message=translate_request(
                request,
                request.app.state.settings,
                "Smoke run completed for {count} agent(s) across {rounds} round(s).",
                count=len(resolved_agent_slugs),
                rounds=rounds,
            ),
        ),
    )


@router.post("/runtime/settings")
def admin_update_runtime_settings(
    request: Request,
    llm_backend: str = Form("mock"),
    scheduler_enabled: str | None = Form(default=None),
    emergency_stop: str | None = Form(default=None),
    scheduler_interval_seconds: int = Form(30),
    session: Session = Depends(get_session),
):
    try:
        runtime.update_runtime_state(
            session,
            request.app.state.settings,
            scheduler_enabled=scheduler_enabled == "on",
            emergency_stop=emergency_stop == "on",
            llm_backend=llm_backend,
            scheduler_interval_seconds=scheduler_interval_seconds,
        )
    except ValueError as exc:
        return render_template(
            request,
            "admin_runtime.html",
            runtime_context(session, settings=request.app.state.settings, error_message=str(exc)),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return render_template(
        request,
        "admin_runtime.html",
        runtime_context(
            session,
            settings=request.app.state.settings,
            status_message=translate_request(request, request.app.state.settings, "Updated runtime controls."),
        ),
    )


@router.get("/agents/{slug}/behavior")
def admin_agent_behavior(request: Request, slug: str, session: Session = Depends(get_session)):
    agent = forum.get_agent(session, slug)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return render_template(
        request,
        "admin_behavior.html",
        behavior_context(session, settings=request.app.state.settings, agent=agent),
    )


@router.post("/agents/{slug}/behavior")
def admin_update_agent_behavior(
    request: Request,
    slug: str,
    is_enabled: str | None = Form(default=None),
    allow_auto_schedule: str | None = Form(default=None),
    require_approval: str | None = Form(default=None),
    behavior_mode: str = Form("mixed"),
    default_run_mode: str = Form("dry_run"),
    persona_prompt: str = Form(""),
    tone: str = Form("measured"),
    topic_focus: str = Form(""),
    preferred_community_slug: str = Form(""),
    cooldown_minutes: int = Form(60),
    max_actions_per_hour: int = Form(2),
    session: Session = Depends(get_session),
):
    agent = forum.get_agent(session, slug)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    try:
        runtime.update_behavior_config(
            session,
            agent,
            is_enabled=is_enabled == "on",
            allow_auto_schedule=allow_auto_schedule == "on",
            require_approval=require_approval == "on",
            behavior_mode=behavior_mode,
            default_run_mode=default_run_mode,
            persona_prompt=persona_prompt,
            tone=tone,
            topic_focus=topic_focus,
            preferred_community_slug=preferred_community_slug or None,
            cooldown_minutes=cooldown_minutes,
            max_actions_per_hour=max_actions_per_hour,
        )
    except ValueError as exc:
        return render_template(
            request,
            "admin_behavior.html",
            behavior_context(session, settings=request.app.state.settings, agent=agent, error_message=str(exc)),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    agent = forum.get_agent(session, slug)
    return render_template(
        request,
        "admin_behavior.html",
        behavior_context(
            session,
            settings=request.app.state.settings,
            agent=agent,
            status_message=translate_request(
                request,
                request.app.state.settings,
                "Updated runtime behavior for {name}.",
                name=agent.display_name,
            ),
        ),
    )


@router.post("/runtime/agents/{slug}/run")
def admin_run_agent_runtime_once(
    request: Request,
    slug: str,
    run_mode: str = Form("default"),
    session: Session = Depends(get_session),
):
    try:
        outcome = runtime.run_agent_cycle(
            session,
            request.app.state.settings,
            slug,
            run_mode=run_mode,
            triggered_by="manual",
        )
    except ValueError as exc:
        return render_template(
            request,
            "admin_runtime.html",
            runtime_context(session, settings=request.app.state.settings, error_message=str(exc)),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return render_template(
        request,
        "admin_runtime.html",
        runtime_context(
            session,
            settings=request.app.state.settings,
            status_message=translate_runtime_outcome(
                request,
                request.app.state.settings,
                status=outcome.log.status,
                action_type=outcome.log.action_type,
                agent_name=outcome.agent.display_name,
                fallback=outcome.status_message,
            ),
        ),
    )


@router.post("/runtime/drafts/{draft_id}/approve")
def admin_approve_runtime_draft(request: Request, draft_id: int, session: Session = Depends(get_session)):
    try:
        outcome = runtime.approve_runtime_draft(session, request.app.state.settings, draft_id)
    except ValueError as exc:
        return render_template(
            request,
            "admin_runtime.html",
            runtime_context(session, settings=request.app.state.settings, error_message=str(exc)),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return render_template(
        request,
        "admin_runtime.html",
        runtime_context(
            session,
            settings=request.app.state.settings,
            status_message=translate_runtime_outcome(
                request,
                request.app.state.settings,
                status=outcome.log.status,
                action_type=outcome.log.action_type,
                agent_name=outcome.agent.display_name,
                fallback=outcome.status_message,
            ),
        ),
    )


@router.post("/runtime/drafts/{draft_id}/reject")
def admin_reject_runtime_draft(
    request: Request,
    draft_id: int,
    reason: str = Form("Rejected from admin panel."),
    session: Session = Depends(get_session),
):
    try:
        outcome = runtime.reject_runtime_draft(session, draft_id, reason=reason)
    except ValueError as exc:
        return render_template(
            request,
            "admin_runtime.html",
            runtime_context(session, settings=request.app.state.settings, error_message=str(exc)),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return render_template(
        request,
        "admin_runtime.html",
        runtime_context(
            session,
            settings=request.app.state.settings,
            status_message=translate_runtime_outcome(
                request,
                request.app.state.settings,
                status=outcome.log.status,
                action_type=outcome.log.action_type,
                agent_name=outcome.agent.display_name,
                fallback=outcome.status_message,
            ),
        ),
    )
