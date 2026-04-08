from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import tempfile
from threading import Event, Lock, Thread
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, build_settings
from app.db import Database, build_database
from app.models import (
    Agent,
    AgentBehaviorConfig,
    AgentRuntimeMemory,
    Comment,
    Community,
    Post,
    RuntimeDraft,
    RuntimeLog,
    RuntimeState,
)
from app.services import forum, llm


BEHAVIOR_MODES = {"observe", "reply", "post", "mixed", "reply_first", "reply_only", "post_and_reply_limited"}
RUN_MODES = {"dry_run", "live"}
ACTION_TYPES = {"skip", "post", "comment", "like_post", "like_comment"}
LOG_STATUSES = {"approved", "drafted", "executed", "failed", "rejected", "skipped"}
LLM_BACKENDS = llm.SUPPORTED_BACKENDS
TIMELINE_LIMIT = 36

_SMOKE_RUN_LOCK = Lock()
_SMOKE_RUN_STATE: dict[str, Any] = {
    "running": False,
    "abort_requested": False,
    "current_round": 0,
    "current_agent_slug": None,
    "run_mode": None,
    "community_scope_slug": None,
    "last_report": None,
    "last_started_at": None,
    "last_finished_at": None,
}


@dataclass(frozen=True)
class RuntimeOutcome:
    agent: Agent
    config: AgentBehaviorConfig
    memory: AgentRuntimeMemory
    log: RuntimeLog
    draft: RuntimeDraft | None
    created_post: Post | None
    created_comment: Comment | None
    run_mode: str

    @property
    def status_message(self) -> str:
        if self.log.status == "executed":
            if self.log.action_type == "like_post":
                return f"{self.agent.display_name} liked a post."
            if self.log.action_type == "like_comment":
                return f"{self.agent.display_name} liked a comment."
            return f"{self.agent.display_name} executed a live {self.log.action_type} action."
        if self.log.status == "approved":
            return f"Approved runtime draft for {self.agent.display_name}."
        if self.log.status == "rejected":
            return f"Rejected runtime draft for {self.agent.display_name}."
        if self.log.status == "drafted":
            label = "dry-run draft" if self.run_mode == "dry_run" else "approval draft"
            return f"{self.agent.display_name} produced a {label}."
        if self.log.status == "failed":
            return f"{self.agent.display_name} runtime run failed."
        return self.log.message or f"{self.agent.display_name} runtime run skipped."


class RuntimeScheduler:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings
        self._stop_event = Event()
        self._lock = Lock()
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(target=self._loop, name="cyber-social-runtime", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            thread = self._thread
            self._thread = None
        if thread:
            thread.join(timeout=2)

    def _loop(self) -> None:
        sleep_seconds = max(self.settings.runtime_scheduler_poll_seconds, 5)
        while not self._stop_event.is_set():
            try:
                with self.database.session() as session:
                    state = get_runtime_state(session, self.settings)
                    sleep_seconds = max(state.scheduler_interval_seconds, 5)
                    if state.scheduler_enabled and not state.emergency_stop:
                        run_enabled_agents_once(session, self.settings, triggered_by="scheduler")
            except Exception:
                sleep_seconds = max(self.settings.runtime_scheduler_poll_seconds, 5)
            self._stop_event.wait(timeout=sleep_seconds)


def ensure_runtime_bootstrap(session: Session, settings: Settings) -> RuntimeState:
    state = get_runtime_state(session, settings)
    for agent in list_agents_for_runtime(session):
        get_or_create_behavior_config(session, agent)
        get_or_create_runtime_memory(session, agent)
    session.commit()
    session.refresh(state)
    return state


def get_runtime_state(session: Session, settings: Settings) -> RuntimeState:
    state = session.scalar(select(RuntimeState).limit(1))
    if state is None:
        state = RuntimeState(
            scheduler_enabled=False,
            emergency_stop=False,
            llm_backend=settings.default_llm_backend if settings.default_llm_backend in LLM_BACKENDS else "mock",
            scheduler_interval_seconds=settings.runtime_scheduler_poll_seconds,
        )
        session.add(state)
        session.flush()
    return state


def update_runtime_state(
    session: Session,
    settings: Settings,
    *,
    scheduler_enabled: bool,
    emergency_stop: bool,
    llm_backend: str,
    scheduler_interval_seconds: int | None = None,
) -> RuntimeState:
    state = get_runtime_state(session, settings)
    if llm_backend not in LLM_BACKENDS:
        raise ValueError("Unsupported LLM backend.")
    state.scheduler_enabled = scheduler_enabled
    state.emergency_stop = emergency_stop
    state.llm_backend = llm_backend
    if scheduler_interval_seconds is not None:
        state.scheduler_interval_seconds = max(5, scheduler_interval_seconds)
    session.commit()
    session.refresh(state)
    return state


def list_agents_for_runtime(session: Session) -> list[Agent]:
    stmt = (
        select(Agent)
        .options(
            selectinload(Agent.posts).selectinload(Post.community),
            selectinload(Agent.posts).selectinload(Post.comments),
            selectinload(Agent.comments).selectinload(Comment.post).selectinload(Post.community),
            selectinload(Agent.behavior_config).selectinload(AgentBehaviorConfig.preferred_community),
            selectinload(Agent.runtime_memory),
        )
        .order_by(Agent.display_name.asc())
    )
    return list(session.scalars(stmt))


def get_agent_for_runtime(session: Session, slug: str) -> Agent | None:
    stmt = (
        select(Agent)
        .where(Agent.slug == slug)
        .options(
            selectinload(Agent.posts).selectinload(Post.community),
            selectinload(Agent.posts).selectinload(Post.comments),
            selectinload(Agent.comments).selectinload(Comment.post).selectinload(Post.community),
            selectinload(Agent.behavior_config).selectinload(AgentBehaviorConfig.preferred_community),
            selectinload(Agent.runtime_memory),
        )
    )
    return session.scalar(stmt)


def get_or_create_behavior_config(session: Session, agent: Agent) -> AgentBehaviorConfig:
    if agent.behavior_config is not None:
        return agent.behavior_config

    preferred_community = next((post.community for post in agent.posts if post.community is not None), None)
    if preferred_community is None:
        preferred_community = session.scalar(select(Community).order_by(Community.name.asc()).limit(1))

    config = AgentBehaviorConfig(
        agent=agent,
        preferred_community=preferred_community,
        is_enabled=False,
        allow_auto_schedule=False,
        require_approval=False,
        behavior_mode="reply_first",
        default_run_mode="dry_run",
        persona_prompt=agent.capability_summary or agent.bio,
        tone="measured",
        topic_focus=agent.tagline,
        cooldown_minutes=60,
        max_actions_per_hour=2,
    )
    session.add(config)
    session.flush()
    return config


def get_or_create_runtime_memory(session: Session, agent: Agent) -> AgentRuntimeMemory:
    if agent.runtime_memory is not None:
        return agent.runtime_memory
    memory = AgentRuntimeMemory(agent=agent)
    session.add(memory)
    session.flush()
    return memory


def summarize_memory(memory: AgentRuntimeMemory) -> dict[str, Any]:
    return {
        "recent_participated_post_ids": _load_json_list(memory.recent_participated_post_ids_json),
        "recent_reply_post_ids": _load_json_list(memory.recent_reply_post_ids_json),
        "recent_like_targets": _load_json_list(memory.recent_like_targets_json),
        "recent_action_summaries": _load_json_list(memory.recent_action_summaries_json),
        "recent_guardrail_reasons": _load_json_list(memory.recent_guardrail_reasons_json),
        "recent_generated_fingerprints": _load_json_list(memory.recent_generated_fingerprints_json),
    }


def list_behavior_configs(session: Session) -> list[AgentBehaviorConfig]:
    stmt = (
        select(AgentBehaviorConfig)
        .options(
            selectinload(AgentBehaviorConfig.agent).selectinload(Agent.runtime_memory),
            selectinload(AgentBehaviorConfig.preferred_community),
        )
        .join(AgentBehaviorConfig.agent)
        .order_by(Agent.display_name.asc())
    )
    return list(session.scalars(stmt))


def list_runtime_logs(
    session: Session,
    *,
    agent_slug: str | None = None,
    action_type: str | None = None,
    status: str | None = None,
    limit: int = TIMELINE_LIMIT,
) -> list[RuntimeLog]:
    stmt = (
        select(RuntimeLog)
        .options(selectinload(RuntimeLog.agent), selectinload(RuntimeLog.draft))
        .order_by(RuntimeLog.created_at.desc(), RuntimeLog.id.desc())
        .limit(limit)
    )
    if agent_slug:
        stmt = stmt.join(RuntimeLog.agent).where(Agent.slug == agent_slug)
    if action_type and action_type != "all":
        stmt = stmt.where(RuntimeLog.action_type == action_type)
    if status and status != "all":
        stmt = stmt.where(RuntimeLog.status == status)
    return list(session.scalars(stmt))


def list_runtime_drafts(session: Session, *, status: str | None = None, limit: int = 20) -> list[RuntimeDraft]:
    stmt = (
        select(RuntimeDraft)
        .options(selectinload(RuntimeDraft.agent), selectinload(RuntimeDraft.community))
        .order_by(RuntimeDraft.created_at.desc(), RuntimeDraft.id.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(RuntimeDraft.status == status)
    return list(session.scalars(stmt))


def get_runtime_draft(session: Session, draft_id: int) -> RuntimeDraft | None:
    stmt = (
        select(RuntimeDraft)
        .where(RuntimeDraft.id == draft_id)
        .options(selectinload(RuntimeDraft.agent), selectinload(RuntimeDraft.community))
    )
    return session.scalar(stmt)


def update_behavior_config(
    session: Session,
    agent: Agent,
    *,
    is_enabled: bool,
    allow_auto_schedule: bool,
    require_approval: bool,
    behavior_mode: str,
    default_run_mode: str,
    persona_prompt: str,
    tone: str,
    topic_focus: str,
    preferred_community_slug: str | None,
    cooldown_minutes: int,
    max_actions_per_hour: int,
) -> AgentBehaviorConfig:
    config = get_or_create_behavior_config(session, agent)
    if behavior_mode not in BEHAVIOR_MODES:
        raise ValueError("Unsupported behavior mode.")
    if default_run_mode not in RUN_MODES:
        raise ValueError("Unsupported default run mode.")

    preferred_community = None
    if preferred_community_slug:
        preferred_community = forum.get_community(session, preferred_community_slug)
        if preferred_community is None:
            raise ValueError("Preferred community not found.")

    config.is_enabled = is_enabled
    config.allow_auto_schedule = allow_auto_schedule
    config.require_approval = require_approval
    config.behavior_mode = behavior_mode
    config.default_run_mode = default_run_mode
    config.persona_prompt = persona_prompt.strip()
    config.tone = (tone.strip() or "measured")[:80]
    config.topic_focus = topic_focus.strip()[:160]
    config.preferred_community = preferred_community
    config.cooldown_minutes = max(0, cooldown_minutes)
    config.max_actions_per_hour = max(1, max_actions_per_hour)
    session.commit()
    session.refresh(config)
    return config


def build_attention_report(session: Session, agent_slug: str, community_scope_slug: str | None = None) -> dict[str, Any]:
    agent = get_agent_for_runtime(session, agent_slug)
    if agent is None:
        raise ValueError("Agent not found.")
    config = get_or_create_behavior_config(session, agent)
    memory = get_or_create_runtime_memory(session, agent)
    return _build_attention_report(session, agent, config, summarize_memory(memory), community_scope_slug=community_scope_slug)


def build_runtime_timeline(logs: list[RuntimeLog]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for log in logs:
        details = _load_json_object(log.details_json)
        attention = details.get("attention", {})
        decision_summary = details.get("decision_summary", {})
        entries.append(
            {
                "log": log,
                "details": details,
                "decision_summary": decision_summary,
                "top_post_candidates": attention.get("post_candidates", [])[:3],
                "best_comment": attention.get("best_comment_post"),
                "best_like_post": attention.get("best_like_post"),
                "best_like_comment": attention.get("best_like_comment"),
                "should_create_post": attention.get("should_create_post"),
                "guardrail_reason": details.get("guardrail_reason"),
                "output_length": len((details.get("decision", {}).get("title") or "").strip()) + len((details.get("decision", {}).get("body") or "").strip()),
                "voice": details.get("decision", {}).get("raw", {}).get("voice"),
                "style": details.get("decision", {}).get("raw", {}).get("style"),
            }
        )
    return entries


def build_guardrail_stats(logs: list[RuntimeLog]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for log in logs:
        details = _load_json_object(log.details_json)
        reason = str(details.get("guardrail_reason", "")).strip()
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def build_failure_stats(logs: list[RuntimeLog]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for log in logs:
        details = _load_json_object(log.details_json)
        category = str(details.get("llm_error_category") or details.get("failure_category") or "").strip()
        if category:
            counts[category] = counts.get(category, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def build_agent_autonomy_summaries(session: Session) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for config in list_behavior_configs(session):
        memory = get_or_create_runtime_memory(session, config.agent)
        memory_state = summarize_memory(memory)
        summaries.append(
            {
                "agent": config.agent,
                "config": config,
                "recent_action": memory_state["recent_action_summaries"][0] if memory_state["recent_action_summaries"] else None,
                "watch_count": len(memory_state["recent_participated_post_ids"]),
                "followed_agents": _recent_followed_agent_slugs(memory_state),
                "recent_guardrail": memory_state["recent_guardrail_reasons"][0] if memory_state["recent_guardrail_reasons"] else None,
            }
        )
    return summaries


def build_followed_threads_snapshot(session: Session, *, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for agent in list_agents_for_runtime(session):
        config = get_or_create_behavior_config(session, agent)
        memory_state = summarize_memory(get_or_create_runtime_memory(session, agent))
        for entry in _build_watchlist_entries(session, agent, config, memory_state)[:3]:
            rows.append(
                {
                    "agent": agent,
                    "post": forum.get_post(session, entry["post_id"]),
                    "reason": entry["reason"],
                    "score": entry["score"],
                }
            )
    rows = [row for row in rows if row["post"] is not None]
    rows.sort(key=lambda row: (row["score"], row["post"].created_at), reverse=True)
    return rows[:limit]


def get_smoke_run_status() -> dict[str, Any]:
    with _SMOKE_RUN_LOCK:
        return dict(_SMOKE_RUN_STATE)


def request_smoke_run_abort() -> dict[str, Any]:
    with _SMOKE_RUN_LOCK:
        if _SMOKE_RUN_STATE["running"]:
            _SMOKE_RUN_STATE["abort_requested"] = True
        return dict(_SMOKE_RUN_STATE)


def build_draft_entries(session: Session, drafts: list[RuntimeDraft]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for draft in drafts:
        payload = _load_json_object(draft.payload_json)
        entries.append(
            {
                "draft": draft,
                "target_label": _target_label(session, draft.action_type, draft.target_post_id, draft.target_comment_id),
                "decision_summary": payload.get("rationale") or draft.rationale,
            }
        )
    return entries


def run_smoke_run(
    settings: Settings,
    database: Database,
    *,
    agent_slugs: list[str],
    rounds: int,
    run_mode: str,
    community_scope_slug: str | None = None,
) -> dict[str, Any]:
    unique_agents = [slug for slug in dict.fromkeys(agent_slugs) if slug]
    if not unique_agents:
        raise ValueError("Smoke run requires at least one agent.")
    if run_mode not in RUN_MODES:
        raise ValueError("Smoke run mode must be dry_run or live.")
    if rounds < 1:
        raise ValueError("Smoke run rounds must be at least 1.")
    if community_scope_slug:
        with database.session() as session:
            if forum.get_community(session, community_scope_slug) is None:
                raise ValueError("Smoke run community scope was not found.")
    _start_smoke_run(agent_slugs=unique_agents, run_mode=run_mode, community_scope_slug=community_scope_slug)
    if run_mode == "dry_run":
        try:
            report = _run_smoke_run_on_cloned_database(
                settings,
                database,
                agent_slugs=unique_agents,
                rounds=rounds,
                run_mode=run_mode,
                community_scope_slug=community_scope_slug,
            )
        finally:
            _finish_smoke_run()
        return report
    try:
        report = _run_smoke_run_on_database(
            settings,
            database,
            agent_slugs=unique_agents,
            rounds=rounds,
            run_mode=run_mode,
            community_scope_slug=community_scope_slug,
        )
    finally:
        _finish_smoke_run()
    return report


def _run_smoke_run_on_database(
    settings: Settings,
    database: Database,
    *,
    agent_slugs: list[str],
    rounds: int,
    run_mode: str,
    community_scope_slug: str | None,
) -> dict[str, Any]:
    report = {
        "agent_slugs": agent_slugs,
        "rounds_requested": rounds,
        "run_mode": run_mode,
        "community_scope_slug": community_scope_slug,
        "rounds": [],
        "totals": {
            "action_counts": {action: 0 for action in ACTION_TYPES},
            "guardrail_counts": {},
            "failure_reason_counts": {},
            "average_output_length": 0.0,
            "repetitive_content_hits": 0,
            "target_community_distribution": {},
        },
        "aborted": False,
    }
    all_output_lengths: list[int] = []

    for round_index in range(1, rounds + 1):
        round_summary = {
            "round": round_index,
            "agents": {},
            "guardrail_counts": {},
            "failure_reason_counts": {},
            "average_output_length": 0.0,
            "repetitive_content_hits": 0,
            "target_community_distribution": {},
        }
        round_lengths: list[int] = []
        with database.session() as session:
            ensure_runtime_bootstrap(session, settings)
            if _smoke_run_should_abort():
                report["aborted"] = True
                break
            for slug in agent_slugs:
                _mark_smoke_run_progress(round_index, slug)
                if _smoke_run_should_abort():
                    report["aborted"] = True
                    break
                outcome = run_agent_cycle(
                    session,
                    settings,
                    slug,
                    run_mode=run_mode,
                    triggered_by="smoke_run",
                    community_scope_slug=community_scope_slug,
                )
                agent_summary = _build_smoke_agent_summary(session, outcome)
                round_summary["agents"][slug] = agent_summary
                report["totals"]["action_counts"][agent_summary["action_type"]] += 1
                round_lengths.append(agent_summary["output_length"])
                all_output_lengths.append(agent_summary["output_length"])
                if agent_summary["guardrail_reason"]:
                    _increment_counter(round_summary["guardrail_counts"], agent_summary["guardrail_reason"])
                    _increment_counter(report["totals"]["guardrail_counts"], agent_summary["guardrail_reason"])
                if agent_summary["failure_reason"]:
                    _increment_counter(round_summary["failure_reason_counts"], agent_summary["failure_reason"])
                    _increment_counter(report["totals"]["failure_reason_counts"], agent_summary["failure_reason"])
                if agent_summary["repetitive_content_hit"]:
                    round_summary["repetitive_content_hits"] += 1
                    report["totals"]["repetitive_content_hits"] += 1
                if agent_summary["community_slug"]:
                    _increment_counter(round_summary["target_community_distribution"], agent_summary["community_slug"])
                    _increment_counter(report["totals"]["target_community_distribution"], agent_summary["community_slug"])
        round_summary["average_output_length"] = round(sum(round_lengths) / len(round_lengths), 2) if round_lengths else 0.0
        report["rounds"].append(round_summary)
        if report["aborted"]:
            break

    report["totals"]["average_output_length"] = round(sum(all_output_lengths) / len(all_output_lengths), 2) if all_output_lengths else 0.0
    _store_smoke_run_report(report)
    return report


def _run_smoke_run_on_cloned_database(
    settings: Settings,
    database: Database,
    *,
    agent_slugs: list[str],
    rounds: int,
    run_mode: str,
    community_scope_slug: str | None,
) -> dict[str, Any]:
    if not settings.database_url.startswith("sqlite:///"):
        raise ValueError("Smoke run dry_run isolation currently requires sqlite.")
    source_path = Path(settings.database_url.removeprefix("sqlite:///"))
    with tempfile.TemporaryDirectory(prefix="cyber-social-smoke-") as temp_dir:
        temp_path = Path(temp_dir) / source_path.name
        shutil.copy2(source_path, temp_path)
        cloned_settings = build_settings(root_dir=settings.root_dir, database_url=f"sqlite:///{temp_path.as_posix()}")
        cloned_db = build_database(cloned_settings)
        try:
            return _run_smoke_run_on_database(
                cloned_settings,
                cloned_db,
                agent_slugs=agent_slugs,
                rounds=rounds,
                run_mode=run_mode,
                community_scope_slug=community_scope_slug,
            )
        finally:
            cloned_db.dispose()


def run_enabled_agents_once(session: Session, settings: Settings, *, triggered_by: str) -> list[RuntimeOutcome]:
    outcomes: list[RuntimeOutcome] = []
    for agent in list_agents_for_runtime(session):
        config = get_or_create_behavior_config(session, agent)
        if not config.is_enabled or not config.allow_auto_schedule:
            continue
        outcomes.append(run_agent_cycle(session, settings, agent.slug, run_mode="default", triggered_by=triggered_by))
    state = get_runtime_state(session, settings)
    state.last_scheduler_tick_at = datetime.utcnow()
    session.commit()
    return outcomes


def run_agent_cycle(
    session: Session,
    settings: Settings,
    agent_slug: str,
    *,
    run_mode: str = "default",
    triggered_by: str = "manual",
    community_scope_slug: str | None = None,
) -> RuntimeOutcome:
    state = get_runtime_state(session, settings)
    agent = get_agent_for_runtime(session, agent_slug)
    if agent is None:
        raise ValueError("Agent not found.")
    config = get_or_create_behavior_config(session, agent)
    memory = get_or_create_runtime_memory(session, agent)
    memory_state = summarize_memory(memory)
    effective_run_mode = config.default_run_mode if run_mode == "default" else run_mode
    if effective_run_mode not in RUN_MODES:
        raise ValueError("Unsupported run mode.")

    now = datetime.utcnow()
    config.last_run_at = now
    if triggered_by == "manual":
        state.last_manual_run_at = now

    skip_reason = _preflight_issue(session, state, agent, config, effective_run_mode, triggered_by, now)
    if skip_reason:
        _remember_guardrail(memory, skip_reason)
        _remember_action(memory, action_type="skip", status="skipped", summary=skip_reason)
        return _finalize_skipped_outcome(
            session,
            agent=agent,
            config=config,
            memory=memory,
            run_mode=effective_run_mode,
            message=skip_reason,
            details={"triggered_by": triggered_by, "guardrail_reason": skip_reason, "memory_summary": summarize_memory(memory)},
        )

    attention_report = _build_attention_report(session, agent, config, memory_state, community_scope_slug=community_scope_slug)
    context = llm.RuntimeContext(
        agent_slug=agent.slug,
        display_name=agent.display_name,
        avatar=agent.avatar,
        behavior_mode=config.behavior_mode,
        persona_prompt=config.persona_prompt,
        tone=config.tone,
        topic_focus=config.topic_focus,
        preferred_community_slug=config.preferred_community.slug if config.preferred_community else None,
        preferred_community_name=config.preferred_community.name if config.preferred_community else None,
        attention_report=attention_report,
        memory_summary=_memory_prompt_summary(memory_state),
        community_scope_slug=community_scope_slug,
    )

    backend_used = state.llm_backend
    adapter_warning: str | None = None
    try:
        decision = llm.decide_action(settings, state.llm_backend, context)
    except llm.RuntimeLLMError as exc:
        if state.llm_backend == "mock":
            return _finalize_failed_outcome(
                session,
                agent=agent,
                config=config,
                memory=memory,
                run_mode=effective_run_mode,
                message=str(exc),
                failure_category=exc.category,
            )
        backend_used = "mock"
        adapter_warning = str(exc)
        adapter_warning_category = exc.category
        decision = llm.decide_action(settings, "mock", context)
    else:
        adapter_warning_category = None

    decision = _hydrate_decision_targets(decision, attention_report, config)
    guardrail_issue = _guardrail_issue(session, agent, config, memory_state, decision)
    details = {
        "triggered_by": triggered_by,
        "backend_used": backend_used,
        "attention": attention_report,
        "decision": decision.as_payload(),
        "decision_summary": _build_decision_summary(session, decision),
        "memory_summary": summarize_memory(memory),
        "community_scope_slug": community_scope_slug,
        "llm_mode": state.llm_backend,
    }
    if adapter_warning:
        details["adapter_warning"] = adapter_warning
    if adapter_warning_category:
        details["llm_error_category"] = adapter_warning_category

    if guardrail_issue:
        _remember_guardrail(memory, guardrail_issue)
        _remember_action(
            memory,
            action_type="skip",
            status="skipped",
            summary=guardrail_issue,
            target_post_id=decision.target_post_id,
            target_comment_id=decision.target_comment_id,
            target_agent_slug=_decision_target_agent_slug(session, decision),
        )
        _remember_candidate_state(memory, decision, disposition="ignored")
        details["guardrail_reason"] = guardrail_issue
        return _finalize_skipped_outcome(
            session,
            agent=agent,
            config=config,
            memory=memory,
            run_mode=effective_run_mode,
            message=guardrail_issue,
            details=details,
        )

    if decision.action_type == "skip":
        _remember_action(
            memory,
            action_type="skip",
            status="skipped",
            summary=decision.rationale,
            target_post_id=decision.target_post_id,
            target_comment_id=decision.target_comment_id,
            target_agent_slug=_decision_target_agent_slug(session, decision),
        )
        _remember_candidate_state(memory, decision, disposition="ignored")
        return _finalize_skipped_outcome(
            session,
            agent=agent,
            config=config,
            memory=memory,
            run_mode=effective_run_mode,
            message=decision.rationale,
            details=details,
        )

    if effective_run_mode == "dry_run":
        draft = _create_runtime_draft(
            session,
            agent=agent,
            config=config,
            decision=decision,
            run_mode=effective_run_mode,
            status="dry_run",
        )
        _remember_action(memory, action_type=decision.action_type, status="drafted", summary=decision.rationale)
        _remember_candidate_state(memory, decision, disposition="seen")
        log = _create_runtime_log(
            session,
            agent=agent,
            draft=draft,
            action_type=decision.action_type,
            run_mode=effective_run_mode,
            status="drafted",
            message="Dry-run recorded without mutating forum content.",
            details=details,
        )
        session.commit()
        return RuntimeOutcome(agent=agent, config=config, memory=memory, log=log, draft=draft, created_post=None, created_comment=None, run_mode=effective_run_mode)

    if config.require_approval:
        draft = _create_runtime_draft(
            session,
            agent=agent,
            config=config,
            decision=decision,
            run_mode=effective_run_mode,
            status="pending",
        )
        _remember_action(memory, action_type=decision.action_type, status="drafted", summary=decision.rationale)
        _remember_candidate_state(memory, decision, disposition="seen")
        log = _create_runtime_log(
            session,
            agent=agent,
            draft=draft,
            action_type=decision.action_type,
            run_mode=effective_run_mode,
            status="drafted",
            message="Runtime action drafted and is waiting for admin approval.",
            details=details,
        )
        session.commit()
        return RuntimeOutcome(agent=agent, config=config, memory=memory, log=log, draft=draft, created_post=None, created_comment=None, run_mode=effective_run_mode)

    created_post, created_comment = _execute_decision(session, agent, config, decision)
    config.last_live_action_at = now
    _remember_success(memory, decision, created_post, created_comment)
    log = _create_runtime_log(
        session,
        agent=agent,
        draft=None,
        action_type=decision.action_type,
        run_mode=effective_run_mode,
        status="executed",
        message="Runtime action executed through forum core helpers.",
        details={**details, "memory_summary": summarize_memory(memory)},
    )
    session.commit()
    return RuntimeOutcome(
        agent=agent,
        config=config,
        memory=memory,
        log=log,
        draft=None,
        created_post=created_post,
        created_comment=created_comment,
        run_mode=effective_run_mode,
    )


def approve_runtime_draft(session: Session, settings: Settings, draft_id: int) -> RuntimeOutcome:
    state = get_runtime_state(session, settings)
    draft = get_runtime_draft(session, draft_id)
    if draft is None:
        raise ValueError("Runtime draft not found.")
    if draft.status != "pending":
        raise ValueError("Only pending drafts can be approved.")
    if state.emergency_stop:
        raise ValueError("Emergency stop is enabled; approval is blocked.")

    agent = get_agent_for_runtime(session, draft.agent.slug)
    if agent is None:
        raise ValueError("Agent not found for draft.")
    config = get_or_create_behavior_config(session, agent)
    memory = get_or_create_runtime_memory(session, agent)
    memory_state = summarize_memory(memory)
    if not config.is_enabled or not agent.is_active:
        raise ValueError("Agent runtime must be enabled before approving drafts.")

    decision = _decision_from_draft(draft)
    guardrail_issue = _guardrail_issue(session, agent, config, memory_state, decision)
    if guardrail_issue:
        _remember_guardrail(memory, guardrail_issue)
        session.commit()
        raise ValueError(guardrail_issue)

    created_post, created_comment = _execute_decision(session, agent, config, decision)
    now = datetime.utcnow()
    config.last_live_action_at = now
    config.last_run_at = now
    draft.status = "applied"
    draft.decided_at = now
    draft.applied_at = now
    _remember_success(memory, decision, created_post, created_comment)
    log = _create_runtime_log(
        session,
        agent=agent,
        draft=draft,
        action_type=decision.action_type,
        run_mode=draft.run_mode,
        status="approved",
        message="Pending runtime draft approved and applied.",
        details={
            "decision": decision.as_payload(),
            "decision_summary": _build_decision_summary(session, decision),
            "memory_summary": summarize_memory(memory),
        },
    )
    session.commit()
    return RuntimeOutcome(
        agent=agent,
        config=config,
        memory=memory,
        log=log,
        draft=draft,
        created_post=created_post,
        created_comment=created_comment,
        run_mode=draft.run_mode,
    )


def reject_runtime_draft(session: Session, draft_id: int, *, reason: str = "Rejected from admin panel.") -> RuntimeOutcome:
    draft = get_runtime_draft(session, draft_id)
    if draft is None:
        raise ValueError("Runtime draft not found.")
    if draft.status not in {"pending", "dry_run"}:
        raise ValueError("Draft cannot be rejected from its current state.")

    now = datetime.utcnow()
    draft.status = "rejected"
    draft.decided_at = now
    draft.applied_at = None
    memory = get_or_create_runtime_memory(session, draft.agent)
    _remember_action(memory, action_type=draft.action_type, status="rejected", summary=reason.strip() or "Rejected from admin panel.")
    log = _create_runtime_log(
        session,
        agent=draft.agent,
        draft=draft,
        action_type=draft.action_type,
        run_mode=draft.run_mode,
        status="rejected",
        message=reason.strip() or "Rejected from admin panel.",
        details={"payload": _load_json_object(draft.payload_json), "memory_summary": summarize_memory(memory)},
    )
    session.commit()
    config = get_or_create_behavior_config(session, draft.agent)
    return RuntimeOutcome(
        agent=draft.agent,
        config=config,
        memory=memory,
        log=log,
        draft=draft,
        created_post=None,
        created_comment=None,
        run_mode=draft.run_mode,
    )


def _build_attention_report(
    session: Session,
    agent: Agent,
    config: AgentBehaviorConfig,
    memory_state: dict[str, Any],
    community_scope_slug: str | None = None,
) -> dict[str, Any]:
    scoped_community = forum.get_community(session, community_scope_slug) if community_scope_slug else None
    preferred_community = scoped_community or config.preferred_community
    all_posts = forum.list_posts(session, community_slug=scoped_community.slug) if scoped_community else forum.list_posts(session)
    watchlist_entries = _build_watchlist_entries(session, agent, config, memory_state, scoped_community=preferred_community)
    recent_posts = forum.sort_posts(list(all_posts), sort="new")[:8]
    hot_posts = forum.sort_posts(list(all_posts), sort="hot")[:8]
    preferred_posts = (
        forum.sort_posts(forum.list_posts(session, community_slug=preferred_community.slug), sort="hot")[:8]
        if preferred_community
        else []
    )

    engaged_ids = set(memory_state["recent_participated_post_ids"])
    engaged_ids.update(post.id for post in agent.posts[:6])
    engaged_ids.update(comment.post_id for comment in agent.comments[:8] if comment.post_id)
    engaged_posts = [post for post in all_posts if post.id in engaged_ids]

    source_map: dict[int, set[str]] = {}
    for label, posts in (
        ("recent", recent_posts),
        ("hot", hot_posts),
        ("preferred", preferred_posts),
        ("engaged", engaged_posts),
    ):
        for post in posts:
            source_map.setdefault(post.id, set()).add(label)
    for entry in watchlist_entries:
        source_map.setdefault(entry["post_id"], set()).add("watchlist")

    post_lookup = {post.id: post for post in all_posts}
    post_candidates = [
        _score_post_candidate(
            post_lookup[post_id],
            source_tags,
            agent,
            config,
            memory_state,
            preferred_community,
            watchlist_entry=_watch_entry_for_post(watchlist_entries, post_id),
        )
        for post_id, source_tags in source_map.items()
        if post_id in post_lookup
    ]
    post_candidates.sort(key=lambda item: (item["score"], item["target_id"]), reverse=True)

    comment_candidates = _build_comment_candidates(post_candidates, post_lookup, agent, memory_state)
    comment_candidates.sort(key=lambda item: (item["score"], item["target_id"]), reverse=True)

    best_comment_post = next((candidate for candidate in post_candidates if _candidate_can_receive_comment(candidate)), None)
    best_like_post = next((candidate for candidate in post_candidates if _candidate_can_receive_like(candidate)), None)
    best_like_comment = next((candidate for candidate in comment_candidates if _candidate_can_receive_like(candidate)), None)
    should_create_post = _should_create_post(config, memory_state, best_comment_post, best_like_post)
    watched_post_ids = {entry["post_id"] for entry in watchlist_entries}
    reply_first_target = (
        next(
            (
                candidate
                for candidate in post_candidates
                if candidate["post_id"] in watched_post_ids and _candidate_can_receive_comment(candidate)
            ),
            best_comment_post,
        )
        if config.behavior_mode in {"reply_first", "reply_only"}
        else None
    )
    recently_replied_by = _recent_replied_by(agent, config.last_run_at)
    recently_replied_to = _recent_followed_agent_slugs(memory_state)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "post_candidates": post_candidates[:8],
        "comment_candidates": comment_candidates[:8],
        "best_comment_post": best_comment_post,
        "best_like_post": best_like_post,
        "best_like_comment": best_like_comment,
        "reply_first_target": reply_first_target,
        "should_create_post": should_create_post,
        "preferred_community_slug": preferred_community.slug if preferred_community else None,
        "community_scope_slug": scoped_community.slug if scoped_community else None,
        "watchlist_threads": watchlist_entries[:8],
        "recently_replied_by": recently_replied_by,
        "recently_replied_to": recently_replied_to,
        "memory_summary": _memory_prompt_summary(memory_state),
    }


def _score_post_candidate(
    post: Post,
    source_tags: set[str],
    agent: Agent,
    config: AgentBehaviorConfig,
    memory_state: dict[str, Any],
    preferred_community: Community | None,
    watchlist_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    score_factors: dict[str, int] = {}
    source_weights = {"recent": 4, "hot": 3, "engaged": 4, "preferred": 2, "watchlist": 5}
    score_factors["source_signal"] = sum(source_weights[label] for label in sorted(source_tags))
    score_factors["external_author"] = 2 if post.agent_id != agent.id else 0
    score_factors["self_authored_exclusion"] = -100 if post.agent_id == agent.id else 0
    score_factors["engagement_score"] = min(post.comment_count, 6) + (min(max(post.score, 0), 20) // 4)

    age_hours = max((datetime.utcnow() - post.created_at).total_seconds() / 3600.0, 1.0)
    if age_hours <= 6:
        score_factors["recency"] = 3
    elif age_hours <= 24:
        score_factors["recency"] = 2
    elif age_hours <= 72:
        score_factors["recency"] = 1
    else:
        score_factors["recency"] = 0

    if preferred_community and post.community_id == preferred_community.id:
        score_factors["preferred_community_match"] = 2
    else:
        score_factors["preferred_community_match"] = 0

    score_factors["topic_affinity"] = _topic_affinity_score(post, config, preferred_community)
    score_factors["watchlist_bonus"] = watchlist_entry["score"] if watchlist_entry else 0
    score_factors["mention_bonus"] = 3 if watchlist_entry and watchlist_entry["reason"] == "mentioned" else 0

    if post.id in memory_state["recent_reply_post_ids"]:
        score_factors["recent_interaction_penalty"] = -6
    elif _was_recently_liked(memory_state, f"post:{post.id}"):
        score_factors["recent_interaction_penalty"] = -5
    else:
        score_factors["recent_interaction_penalty"] = 0

    if post.id in memory_state["recent_participated_post_ids"]:
        score_factors["already_seen_penalty"] = -3
        score_factors["continuity_bonus"] = 1
        score_factors["novelty_bonus"] = 0
    else:
        score_factors["already_seen_penalty"] = 0
        score_factors["continuity_bonus"] = 0
        score_factors["novelty_bonus"] = 2

    score = sum(score_factors.values())
    reasons = [name for name, value in score_factors.items() if value]

    return {
        "target_type": "post",
        "target_id": post.id,
        "post_id": post.id,
        "score": score,
        "title": post.title,
        "community_slug": post.community.slug,
        "community_name": post.community.name,
        "author_slug": post.agent.slug,
        "author_name": post.agent.display_name,
        "source_tags": sorted(source_tags),
        "reasons": reasons,
        "score_factors": score_factors,
        "excerpt": _excerpt(post.body),
        "self_authored": post.agent_id == agent.id,
        "recently_replied": post.id in memory_state["recent_reply_post_ids"],
        "recently_liked": _was_recently_liked(memory_state, f"post:{post.id}"),
        "seen_recently": post.id in memory_state["recent_participated_post_ids"],
        "watch_reason": watchlist_entry["reason"] if watchlist_entry else None,
    }


def _build_comment_candidates(
    post_candidates: list[dict[str, Any]],
    post_lookup: dict[int, Post],
    agent: Agent,
    memory_state: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for post_candidate in post_candidates[:6]:
        post = post_lookup[post_candidate["post_id"]]
        for comment in post.comments[:6]:
            score = max(post_candidate["score"] - 2, 0)
            reasons = list(post_candidate["source_tags"])
            if comment.agent_id != agent.id:
                score += 2
                reasons.append("external_author")
            else:
                score -= 8
                reasons.append("self_authored")
            score += min(max(comment.score, 0), 10) // 2
            age_hours = max((datetime.utcnow() - comment.created_at).total_seconds() / 3600.0, 1.0)
            if age_hours <= 12:
                score += 2
                reasons.append("fresh_comment")
            if _was_recently_liked(memory_state, f"comment:{comment.id}"):
                score -= 6
                reasons.append("recently_liked")
            candidates.append(
                {
                    "target_type": "comment",
                    "target_id": comment.id,
                    "post_id": post.id,
                    "post_title": post.title,
                    "community_slug": post.community.slug,
                    "community_name": post.community.name,
                    "author_slug": comment.agent.slug,
                    "author_name": comment.agent.display_name,
                    "score": score,
                    "reasons": reasons,
                    "excerpt": _excerpt(comment.body),
                    "self_authored": comment.agent_id == agent.id,
                    "recently_liked": _was_recently_liked(memory_state, f"comment:{comment.id}"),
                }
            )
    return candidates


def _build_watchlist_entries(
    session: Session,
    agent: Agent,
    config: AgentBehaviorConfig,
    memory_state: dict[str, Any],
    *,
    scoped_community: Community | None = None,
) -> list[dict[str, Any]]:
    posts = forum.list_posts(session, community_slug=scoped_community.slug) if scoped_community else forum.list_posts(session)
    post_lookup = {post.id: post for post in posts}
    watched_ids = set(memory_state["recent_participated_post_ids"])
    watched_ids.update(memory_state["recent_reply_post_ids"])
    watched_ids.update(post.id for post in agent.posts[:6])
    watched_ids.update(comment.post_id for comment in agent.comments[:8] if comment.post_id)
    entries: list[dict[str, Any]] = []
    for post_id in watched_ids:
        post = post_lookup.get(post_id)
        if not post:
            continue
        reason = "watchlist"
        score = 2
        if _post_has_recent_external_reply(post, agent.id, config.last_run_at):
            reason = "recent_reply"
            score = 5
        if _post_mentions_agent(post, agent):
            reason = "mentioned"
            score = 6
        if scoped_community and post.community_id != scoped_community.id:
            continue
        if _was_recently_ignored(memory_state, f"post:{post.id}"):
            score -= 3
        entries.append({"post_id": post.id, "reason": reason, "score": score})
    entries.sort(key=lambda entry: (entry["score"], entry["post_id"]), reverse=True)
    return entries


def _watch_entry_for_post(entries: list[dict[str, Any]], post_id: int) -> dict[str, Any] | None:
    return next((entry for entry in entries if entry["post_id"] == post_id), None)


def _post_has_recent_external_reply(post: Post, agent_id: int, last_run_at: datetime | None) -> bool:
    threshold = last_run_at or (datetime.utcnow() - timedelta(hours=12))
    return any(comment.agent_id != agent_id and comment.created_at >= threshold for comment in post.comments)


def _post_mentions_agent(post: Post, agent: Agent) -> bool:
    tokens = {f"@{agent.slug.lower()}", agent.slug.lower(), agent.display_name.lower()}
    comment_text = " ".join(comment.body.lower() for comment in post.comments[:12])
    haystack = " ".join((post.title.lower(), post.body.lower(), comment_text))
    return any(token in haystack for token in tokens)


def _topic_affinity_score(post: Post, config: AgentBehaviorConfig, preferred_community: Community | None) -> int:
    focus_text = " ".join(
        fragment
        for fragment in (
            config.topic_focus,
            config.persona_prompt[:120],
            preferred_community.name if preferred_community else "",
        )
        if fragment
    )
    focus_tokens = _extract_tokens(focus_text)
    if not focus_tokens:
        return 0
    post_tokens = _extract_tokens(" ".join((post.title, post.body[:180], post.community.name, post.community.description)))
    overlap = len(focus_tokens & post_tokens)
    return min(overlap * 2, 6)


def _candidate_can_receive_comment(candidate: dict[str, Any]) -> bool:
    return not candidate["self_authored"] and not candidate["recently_replied"]


def _candidate_can_receive_like(candidate: dict[str, Any]) -> bool:
    return not candidate["self_authored"] and not candidate["recently_liked"]


def _should_create_post(
    config: AgentBehaviorConfig,
    memory_state: dict[str, Any],
    best_comment_post: dict[str, Any] | None,
    best_like_post: dict[str, Any] | None,
) -> bool:
    if config.behavior_mode not in {"post", "mixed", "reply_first", "post_and_reply_limited"}:
        return False
    if config.behavior_mode == "reply_first" and best_comment_post is not None:
        return False
    if any(entry.get("action_type") == "post" for entry in memory_state["recent_action_summaries"][:2]):
        return False
    if best_comment_post and best_comment_post["score"] >= 10:
        return False
    if best_like_post and best_like_post["score"] >= 9:
        return False
    return True


def _recent_replied_by(agent: Agent, last_run_at: datetime | None) -> list[str]:
    threshold = last_run_at or (datetime.utcnow() - timedelta(hours=12))
    seen: list[str] = []
    for post in agent.posts[:8]:
        for comment in post.comments:
            if comment.agent_id != agent.id and comment.created_at >= threshold and comment.agent.slug not in seen:
                seen.append(comment.agent.slug)
    return seen[:6]


def _recent_followed_agent_slugs(memory_state: dict[str, Any]) -> list[str]:
    seen: list[str] = []
    for entry in memory_state["recent_action_summaries"]:
        target_agent = entry.get("target_agent_slug") if isinstance(entry, dict) else None
        if target_agent and target_agent not in seen:
            seen.append(target_agent)
    return seen[:6]


def _hydrate_decision_targets(
    decision: llm.RuntimeDecision,
    attention_report: dict[str, Any],
    config: AgentBehaviorConfig,
) -> llm.RuntimeDecision:
    if decision.action_type == "comment" and decision.target_post_id is None and attention_report.get("best_comment_post"):
        candidate = attention_report["best_comment_post"]
        return llm.RuntimeDecision(
            action_type=decision.action_type,
            rationale=decision.rationale,
            title=decision.title,
            body=decision.body,
            community_slug=decision.community_slug or candidate.get("community_slug"),
            target_post_id=candidate.get("target_id"),
            target_comment_id=None,
            raw=decision.raw,
        )
    if decision.action_type == "like_post" and decision.target_post_id is None and attention_report.get("best_like_post"):
        candidate = attention_report["best_like_post"]
        return llm.RuntimeDecision(
            action_type=decision.action_type,
            rationale=decision.rationale,
            title="",
            body="",
            community_slug=decision.community_slug or candidate.get("community_slug"),
            target_post_id=candidate.get("target_id"),
            target_comment_id=None,
            raw=decision.raw,
        )
    if decision.action_type == "like_comment" and decision.target_comment_id is None and attention_report.get("best_like_comment"):
        candidate = attention_report["best_like_comment"]
        return llm.RuntimeDecision(
            action_type=decision.action_type,
            rationale=decision.rationale,
            title="",
            body="",
            community_slug=decision.community_slug or candidate.get("community_slug"),
            target_post_id=candidate.get("post_id"),
            target_comment_id=candidate.get("target_id"),
            raw=decision.raw,
        )
    if decision.action_type == "post" and not decision.community_slug:
        return llm.RuntimeDecision(
            action_type=decision.action_type,
            rationale=decision.rationale,
            title=decision.title,
            body=decision.body,
            community_slug=config.preferred_community.slug if config.preferred_community else None,
            target_post_id=None,
            target_comment_id=None,
            raw=decision.raw,
        )
    return decision


def _guardrail_issue(
    session: Session,
    agent: Agent,
    config: AgentBehaviorConfig,
    memory_state: dict[str, Any],
    decision: llm.RuntimeDecision,
) -> str | None:
    if decision.action_type not in ACTION_TYPES:
        return "Runtime action type is unsupported."
    if decision.action_type == "skip":
        return None
    if decision.action_type == "post":
        community = _resolve_community_for_decision(session, config, decision)
        if community is None:
            return "No community available for runtime post."
        if not decision.title.strip():
            return "Runtime post title cannot be empty."
        if not decision.body.strip():
            return "Runtime post body cannot be empty."
        if _is_duplicate_post(agent, decision.title, decision.body):
            return "Duplicate post guardrail blocked a repeated draft."
        if _is_repetitive_content(memory_state, f"{decision.title} {decision.body}"):
            return "Repetitive content guardrail blocked a highly similar post."
        return None
    if decision.action_type == "comment":
        if decision.target_post_id is None:
            return "Runtime comment is missing a target post."
        target_post = forum.get_post(session, decision.target_post_id)
        if target_post is None:
            return "Runtime comment target post no longer exists."
        if target_post.agent_id == agent.id:
            return "Self-conversation guardrail blocked a reply to the agent's own post."
        if decision.target_post_id in memory_state["recent_reply_post_ids"]:
            return "Repeated reply guardrail blocked another comment on the same post."
        if not decision.body.strip():
            return "Runtime comment body cannot be empty."
        if _is_duplicate_comment(agent, decision.body):
            return "Duplicate comment guardrail blocked a repeated reply."
        if _is_repetitive_content(memory_state, decision.body):
            return "Repetitive content guardrail blocked a highly similar comment."
        return None
    if decision.action_type == "like_post":
        if decision.target_post_id is None:
            return "Runtime post-like is missing a target post."
        post = forum.get_post(session, decision.target_post_id)
        if post is None:
            return "Runtime post-like target no longer exists."
        if post.agent_id == agent.id:
            return "Self-like guardrail blocked a post like."
        if _was_recently_liked(memory_state, f"post:{post.id}"):
            return "Duplicate interaction guardrail blocked a repeated post like."
        return None
    if decision.action_type == "like_comment":
        if decision.target_comment_id is None:
            return "Runtime comment-like is missing a target comment."
        comment = session.get(Comment, decision.target_comment_id)
        if comment is None:
            return "Runtime comment-like target no longer exists."
        if comment.agent_id == agent.id:
            return "Self-like guardrail blocked a comment like."
        if _was_recently_liked(memory_state, f"comment:{comment.id}"):
            return "Duplicate interaction guardrail blocked a repeated comment like."
        return None
    return None


def _execute_decision(
    session: Session,
    agent: Agent,
    config: AgentBehaviorConfig,
    decision: llm.RuntimeDecision,
) -> tuple[Post | None, Comment | None]:
    if decision.action_type == "post":
        community = _resolve_community_for_decision(session, config, decision)
        if community is None:
            raise ValueError("Community not found for runtime post.")
        post = forum.create_post(session, agent=agent, community=community, title=decision.title, body=decision.body)
        return post, None
    if decision.action_type == "comment":
        post = forum.get_post(session, decision.target_post_id or 0)
        if post is None:
            raise ValueError("Comment target post not found.")
        comment = forum.create_comment(session, agent=agent, post=post, body=decision.body, parent=None)
        return None, comment
    if decision.action_type == "like_post":
        post = forum.increment_post_score(session, decision.target_post_id or 0)
        if post is None:
            raise ValueError("Post-like target not found.")
        return post, None
    if decision.action_type == "like_comment":
        comment = forum.increment_comment_score(session, decision.target_comment_id or 0)
        if comment is None:
            raise ValueError("Comment-like target not found.")
        return None, comment
    return None, None


def _resolve_community_for_decision(
    session: Session,
    config: AgentBehaviorConfig,
    decision: llm.RuntimeDecision,
) -> Community | None:
    if decision.community_slug:
        community = forum.get_community(session, decision.community_slug)
        if community is not None:
            return community
    if config.preferred_community is not None:
        return config.preferred_community
    return session.scalar(select(Community).order_by(Community.name.asc()).limit(1))


def _create_runtime_draft(
    session: Session,
    *,
    agent: Agent,
    config: AgentBehaviorConfig,
    decision: llm.RuntimeDecision,
    run_mode: str,
    status: str,
) -> RuntimeDraft:
    community = _resolve_community_for_decision(session, config, decision)
    draft = RuntimeDraft(
        agent=agent,
        community=community,
        target_post_id=decision.target_post_id,
        target_comment_id=decision.target_comment_id,
        action_type=decision.action_type,
        status=status,
        run_mode=run_mode,
        title=decision.title,
        body=decision.body,
        rationale=decision.rationale,
        payload_json=_dump_json(decision.as_payload()),
        decided_at=datetime.utcnow() if status == "dry_run" else None,
    )
    session.add(draft)
    session.flush()
    return draft


def _create_runtime_log(
    session: Session,
    *,
    agent: Agent,
    draft: RuntimeDraft | None,
    action_type: str,
    run_mode: str,
    status: str,
    message: str,
    details: dict[str, Any],
) -> RuntimeLog:
    log = RuntimeLog(
        agent=agent,
        draft=draft,
        action_type=action_type,
        run_mode=run_mode,
        status=status,
        message=message[:255],
        details_json=_dump_json(details),
    )
    session.add(log)
    session.flush()
    return log


def _decision_from_draft(draft: RuntimeDraft) -> llm.RuntimeDecision:
    payload = _load_json_object(draft.payload_json)
    return llm.RuntimeDecision(
        action_type=payload.get("action_type", draft.action_type),
        rationale=payload.get("rationale", draft.rationale),
        title=payload.get("title", draft.title),
        body=payload.get("body", draft.body),
        community_slug=payload.get("community_slug"),
        target_post_id=payload.get("target_post_id", draft.target_post_id),
        target_comment_id=payload.get("target_comment_id", draft.target_comment_id),
        raw=payload.get("raw"),
    )


def _preflight_issue(
    session: Session,
    state: RuntimeState,
    agent: Agent,
    config: AgentBehaviorConfig,
    run_mode: str,
    triggered_by: str,
    now: datetime,
) -> str | None:
    if not agent.is_active:
        return "Agent is inactive."
    if not config.is_enabled:
        return "Runtime behavior is disabled for this agent."
    if triggered_by == "scheduler" and not state.scheduler_enabled:
        return "Scheduler is disabled."
    if triggered_by == "scheduler" and not config.allow_auto_schedule:
        return "Agent is not allowed to run from the scheduler."
    if run_mode == "live" and state.emergency_stop:
        return "Emergency stop is enabled; live runtime actions are blocked."
    if run_mode == "live":
        if config.last_live_action_at and now < config.last_live_action_at + timedelta(minutes=config.cooldown_minutes):
            return "Cooldown window is still active for live actions."
        if _recent_live_action_count(session, agent.id, now) >= config.max_actions_per_hour:
            return "Per-hour action cap reached for live actions."
    return None


def _remember_success(
    memory: AgentRuntimeMemory,
    decision: llm.RuntimeDecision,
    created_post: Post | None,
    created_comment: Comment | None,
) -> None:
    summary = decision.rationale or f"{decision.action_type} executed."
    target_agent_slug = None
    if decision.action_type == "post" and created_post is not None:
        target_agent_slug = created_post.agent.slug
        _remember_participated_post(memory, created_post.id)
        _remember_fingerprint(memory, f"{created_post.title} {created_post.body}")
    elif decision.action_type == "comment" and created_comment is not None:
        target_agent_slug = created_comment.post.agent.slug if created_comment.post else None
        _remember_participated_post(memory, created_comment.post_id)
        _remember_reply_post(memory, created_comment.post_id)
        _remember_fingerprint(memory, created_comment.body)
    elif decision.action_type == "like_post" and created_post is not None:
        target_agent_slug = created_post.agent.slug
        _remember_participated_post(memory, created_post.id)
        _remember_like_target(memory, f"post:{created_post.id}", disposition="liked")
    elif decision.action_type == "like_comment" and created_comment is not None:
        target_agent_slug = created_comment.agent.slug
        _remember_participated_post(memory, created_comment.post_id)
        _remember_like_target(memory, f"comment:{created_comment.id}", disposition="liked")
    _remember_action(
        memory,
        action_type=decision.action_type,
        status="executed",
        summary=summary,
        target_post_id=decision.target_post_id,
        target_comment_id=decision.target_comment_id,
        target_agent_slug=target_agent_slug,
    )


def _remember_action(
    memory: AgentRuntimeMemory,
    *,
    action_type: str,
    status: str,
    summary: str,
    target_post_id: int | None = None,
    target_comment_id: int | None = None,
    target_agent_slug: str | None = None,
) -> None:
    entries = _load_json_list(memory.recent_action_summaries_json)
    entries.insert(
        0,
        {
            "at": datetime.utcnow().isoformat(),
            "action_type": action_type,
            "status": status,
            "summary": summary[:180],
            "target_post_id": target_post_id,
            "target_comment_id": target_comment_id,
            "target_agent_slug": target_agent_slug,
        },
    )
    memory.recent_action_summaries_json = _dump_json(entries[:8])


def _remember_guardrail(memory: AgentRuntimeMemory, reason: str) -> None:
    entries = _load_json_list(memory.recent_guardrail_reasons_json)
    entries.insert(0, {"at": datetime.utcnow().isoformat(), "reason": reason[:180]})
    memory.recent_guardrail_reasons_json = _dump_json(entries[:8])


def _remember_participated_post(memory: AgentRuntimeMemory, post_id: int) -> None:
    post_ids = [value for value in _load_json_list(memory.recent_participated_post_ids_json) if isinstance(value, int)]
    memory.recent_participated_post_ids_json = _dump_json(_prepend_unique(post_ids, post_id, limit=10))


def _remember_reply_post(memory: AgentRuntimeMemory, post_id: int) -> None:
    post_ids = [value for value in _load_json_list(memory.recent_reply_post_ids_json) if isinstance(value, int)]
    memory.recent_reply_post_ids_json = _dump_json(_prepend_unique(post_ids, post_id, limit=8))


def _remember_like_target(memory: AgentRuntimeMemory, target_key: str, *, disposition: str) -> None:
    entries = [value for value in _load_json_list(memory.recent_like_targets_json) if isinstance(value, dict)]
    entries = [entry for entry in entries if not (entry.get("target") == target_key and entry.get("disposition") == disposition)]
    entries.insert(0, {"target": target_key, "disposition": disposition, "at": datetime.utcnow().isoformat()})
    memory.recent_like_targets_json = _dump_json(entries[:10])


def _remember_candidate_state(memory: AgentRuntimeMemory, decision: llm.RuntimeDecision, *, disposition: str) -> None:
    target_key = None
    if decision.target_comment_id:
        target_key = f"comment:{decision.target_comment_id}"
    elif decision.target_post_id:
        target_key = f"post:{decision.target_post_id}"
    if target_key:
        _remember_like_target(memory, target_key, disposition=disposition)


def _remember_fingerprint(memory: AgentRuntimeMemory, content: str) -> None:
    fingerprint = _fingerprint(content)
    entries = [value for value in _load_json_list(memory.recent_generated_fingerprints_json) if isinstance(value, str)]
    memory.recent_generated_fingerprints_json = _dump_json(_prepend_unique(entries, fingerprint, limit=10))


def _was_recently_liked(memory_state: dict[str, Any], target_key: str) -> bool:
    now = datetime.utcnow()
    for entry in memory_state["recent_like_targets"]:
        if isinstance(entry, dict) and entry.get("target") == target_key and entry.get("disposition", "liked") == "liked":
            liked_at = _safe_datetime(entry.get("at"))
            if liked_at and now - liked_at <= timedelta(hours=12):
                return True
    return False


def _was_recently_ignored(memory_state: dict[str, Any], target_key: str) -> bool:
    now = datetime.utcnow()
    for entry in memory_state["recent_like_targets"]:
        if isinstance(entry, dict) and entry.get("target") == target_key and entry.get("disposition") == "ignored":
            ignored_at = _safe_datetime(entry.get("at"))
            if ignored_at and now - ignored_at <= timedelta(hours=12):
                return True
    return False


def _is_duplicate_post(agent: Agent, title: str, body: str) -> bool:
    candidate = _normalize_text(title) + "::" + _normalize_text(body)
    return any(candidate == (_normalize_text(post.title) + "::" + _normalize_text(post.body)) for post in agent.posts[:10])


def _is_duplicate_comment(agent: Agent, body: str) -> bool:
    candidate = _normalize_text(body)
    return any(candidate == _normalize_text(comment.body) for comment in agent.comments[:10])


def _is_repetitive_content(memory_state: dict[str, Any], content: str) -> bool:
    candidate = _fingerprint(content)
    if candidate in memory_state["recent_generated_fingerprints"]:
        return True
    candidate_tokens = set(candidate.split())
    for existing in memory_state["recent_generated_fingerprints"]:
        if not isinstance(existing, str):
            continue
        existing_tokens = set(existing.split())
        if not candidate_tokens or not existing_tokens:
            continue
        overlap = len(candidate_tokens & existing_tokens) / max(len(candidate_tokens), len(existing_tokens))
        if overlap >= 0.6:
            return True
    return False


def _recent_live_action_count(session: Session, agent_id: int, now: datetime) -> int:
    stmt = select(RuntimeLog).where(
        RuntimeLog.agent_id == agent_id,
        RuntimeLog.status.in_(("executed", "approved")),
        RuntimeLog.created_at >= now - timedelta(hours=1),
    )
    return len(list(session.scalars(stmt)))


def _build_decision_summary(session: Session, decision: llm.RuntimeDecision) -> dict[str, Any]:
    return {
        "action_type": decision.action_type,
        "target_label": _target_label(session, decision.action_type, decision.target_post_id, decision.target_comment_id),
        "rationale": decision.rationale,
    }


def _target_label(session: Session, action_type: str, post_id: int | None, comment_id: int | None) -> str:
    if action_type in {"comment", "like_post"} and post_id:
        post = forum.get_post(session, post_id)
        if post:
            return f"Post #{post.id}: {post.title}"
    if action_type == "like_comment" and comment_id:
        comment = session.get(Comment, comment_id)
        if comment:
            return f"Comment #{comment.id} on post #{comment.post_id}: {_excerpt(comment.body)}"
    if action_type == "post":
        return "New post"
    return "No target"


def _decision_target_agent_slug(session: Session, decision: llm.RuntimeDecision) -> str | None:
    if decision.target_comment_id:
        comment = session.get(Comment, decision.target_comment_id)
        return comment.agent.slug if comment else None
    if decision.target_post_id:
        post = forum.get_post(session, decision.target_post_id)
        return post.agent.slug if post else None
    return None


def _memory_prompt_summary(memory_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "recent_action_summaries": memory_state["recent_action_summaries"][:4],
        "recent_guardrail_reasons": memory_state["recent_guardrail_reasons"][:4],
        "recent_reply_post_ids": memory_state["recent_reply_post_ids"][:6],
        "recent_like_targets": memory_state["recent_like_targets"][:6],
        "recent_followed_agents": _recent_followed_agent_slugs(memory_state),
    }


def _build_smoke_agent_summary(session: Session, outcome: RuntimeOutcome) -> dict[str, Any]:
    details = _load_json_object(outcome.log.details_json)
    decision = details.get("decision", {})
    output_length = len((decision.get("title") or "").strip()) + len((decision.get("body") or "").strip())
    guardrail_reason = details.get("guardrail_reason")
    failure_reason = details.get("llm_error_category") or details.get("failure_category")
    community_slug = _decision_community_slug(session, decision)
    return {
        "agent_slug": outcome.agent.slug,
        "action_type": outcome.log.action_type,
        "status": outcome.log.status,
        "counts": {action: 1 if outcome.log.action_type == action else 0 for action in ACTION_TYPES},
        "guardrail_reason": guardrail_reason,
        "failure_reason": failure_reason,
        "output_length": output_length,
        "repetitive_content_hit": isinstance(guardrail_reason, str) and "Repetitive content guardrail" in guardrail_reason,
        "community_slug": community_slug,
        "decision_summary": details.get("decision_summary", {}),
    }


def _decision_community_slug(session: Session, decision: dict[str, Any]) -> str | None:
    if decision.get("community_slug"):
        return str(decision["community_slug"])
    target_post_id = decision.get("target_post_id")
    target_comment_id = decision.get("target_comment_id")
    if target_post_id:
        post = forum.get_post(session, int(target_post_id))
        if post:
            return post.community.slug
    if target_comment_id:
        comment = session.get(Comment, int(target_comment_id))
        if comment and comment.post and comment.post.community:
            return comment.post.community.slug
    return None


def _increment_counter(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _start_smoke_run(*, agent_slugs: list[str], run_mode: str, community_scope_slug: str | None) -> None:
    with _SMOKE_RUN_LOCK:
        _SMOKE_RUN_STATE.update(
            {
                "running": True,
                "abort_requested": False,
                "current_round": 0,
                "current_agent_slug": None,
                "agent_slugs": list(agent_slugs),
                "run_mode": run_mode,
                "community_scope_slug": community_scope_slug,
                "last_started_at": datetime.utcnow().isoformat(),
            }
        )


def _mark_smoke_run_progress(round_index: int, agent_slug: str) -> None:
    with _SMOKE_RUN_LOCK:
        _SMOKE_RUN_STATE["current_round"] = round_index
        _SMOKE_RUN_STATE["current_agent_slug"] = agent_slug


def _smoke_run_should_abort() -> bool:
    with _SMOKE_RUN_LOCK:
        return bool(_SMOKE_RUN_STATE["abort_requested"])


def _store_smoke_run_report(report: dict[str, Any]) -> None:
    with _SMOKE_RUN_LOCK:
        _SMOKE_RUN_STATE["last_report"] = report


def _finish_smoke_run() -> None:
    with _SMOKE_RUN_LOCK:
        _SMOKE_RUN_STATE["running"] = False
        _SMOKE_RUN_STATE["current_round"] = 0
        _SMOKE_RUN_STATE["current_agent_slug"] = None
        _SMOKE_RUN_STATE["abort_requested"] = False
        _SMOKE_RUN_STATE["last_finished_at"] = datetime.utcnow().isoformat()


def _finalize_skipped_outcome(
    session: Session,
    *,
    agent: Agent,
    config: AgentBehaviorConfig,
    memory: AgentRuntimeMemory,
    run_mode: str,
    message: str,
    details: dict[str, Any],
) -> RuntimeOutcome:
    log = _create_runtime_log(
        session,
        agent=agent,
        draft=None,
        action_type="skip",
        run_mode=run_mode,
        status="skipped",
        message=message,
        details=details,
    )
    session.commit()
    return RuntimeOutcome(agent=agent, config=config, memory=memory, log=log, draft=None, created_post=None, created_comment=None, run_mode=run_mode)


def _finalize_failed_outcome(
    session: Session,
    *,
    agent: Agent,
    config: AgentBehaviorConfig,
    memory: AgentRuntimeMemory,
    run_mode: str,
    message: str,
    failure_category: str | None = None,
) -> RuntimeOutcome:
    _remember_action(memory, action_type="skip", status="failed", summary=message)
    log = _create_runtime_log(
        session,
        agent=agent,
        draft=None,
        action_type="skip",
        run_mode=run_mode,
        status="failed",
        message=message,
        details={"memory_summary": summarize_memory(memory), "failure_category": failure_category, "llm_error_category": failure_category},
    )
    session.commit()
    return RuntimeOutcome(agent=agent, config=config, memory=memory, log=log, draft=None, created_post=None, created_comment=None, run_mode=run_mode)


def _prepend_unique(values: list[Any], new_value: Any, *, limit: int) -> list[Any]:
    filtered = [value for value in values if value != new_value]
    filtered.insert(0, new_value)
    return filtered[:limit]


def _excerpt(value: str, *, limit: int = 110) -> str:
    compact = " ".join(value.split())
    return compact[:limit] + ("..." if len(compact) > limit else "")


def _extract_tokens(value: str) -> set[str]:
    return {token for token in _normalize_text(value).split() if len(token) >= 4}


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _fingerprint(value: str) -> str:
    return _normalize_text(value)[:220]


def _safe_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _load_json_object(payload: str) -> dict[str, Any]:
    try:
        data = json.loads(payload or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _load_json_list(payload: str) -> list[Any]:
    try:
        data = json.loads(payload or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []
