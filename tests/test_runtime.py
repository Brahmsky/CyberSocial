from __future__ import annotations

import json

from app.config import build_settings
from app.services import forum, llm, runtime


def configure_behavior(
    session,
    slug: str,
    *,
    behavior_mode: str = "mixed",
    default_run_mode: str = "dry_run",
    require_approval: bool = False,
    topic_focus: str = "runtime topic",
    tone: str = "measured",
):
    agent = forum.get_agent(session, slug)
    return runtime.update_behavior_config(
        session,
        agent,
        is_enabled=True,
        allow_auto_schedule=False,
        require_approval=require_approval,
        behavior_mode=behavior_mode,
        default_run_mode=default_run_mode,
        persona_prompt=f"{agent.display_name} participates in a deterministic forum workflow around {topic_focus}.",
        tone=tone,
        topic_focus=topic_focus,
        preferred_community_slug="signal-lab",
        cooldown_minutes=0,
        max_actions_per_hour=5,
    )


def build_context(agent_slug: str, *, tone: str = "measured", topic_focus: str = "signal review"):
    return llm.RuntimeContext(
        agent_slug=agent_slug,
        display_name=agent_slug.title(),
        avatar="*",
        behavior_mode="reply",
        persona_prompt=f"{agent_slug} focuses on {topic_focus}.",
        tone=tone,
        topic_focus=topic_focus,
        preferred_community_slug="signal-lab",
        preferred_community_name="Signal Lab",
        attention_report={
            "best_comment_post": {
                "score": 12,
                "target_id": 1,
                "community_slug": "signal-lab",
                "community_name": "Signal Lab",
                "title": "A simple hot-score formula",
            },
            "best_like_post": None,
            "best_like_comment": None,
            "should_create_post": False,
        },
        memory_summary={"recent_action_summaries": [], "recent_guardrail_reasons": [], "recent_reply_post_ids": [], "recent_like_targets": []},
    )


def build_real_llm_settings(client, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "demo-key")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4.1-mini")
    return build_settings(root_dir=client.app.state.settings.root_dir, database_url=client.app.state.settings.database_url)


def test_runtime_bootstrap_defaults_to_safe_local_state(client):
    with client.app.state.db.session() as session:
        state = runtime.get_runtime_state(session, client.app.state.settings)
        configs = runtime.list_behavior_configs(session)

        assert state.scheduler_enabled is False
        assert state.emergency_stop is False
        assert state.llm_backend == "mock"
        assert len(configs) >= 5
        assert all(config.default_run_mode == "dry_run" for config in configs)


def test_llm_settings_accept_new_env_aliases(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODE", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "demo-key")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "33")
    monkeypatch.setenv("LLM_MAX_TOKENS", "512")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.7")

    settings = build_settings(root_dir=tmp_path, database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}")

    assert settings.default_llm_backend == "openai_compatible"
    assert settings.openai_compatible_base_url == "https://example.test/v1"
    assert settings.openai_compatible_api_key == "demo-key"
    assert settings.openai_compatible_model == "openai/gpt-4.1-mini"
    assert settings.llm_request_timeout_seconds == 33
    assert settings.llm_max_tokens == 512
    assert settings.llm_temperature == 0.7


def test_output_shaping_removes_ai_and_customer_service_language():
    context = build_context("cinder", tone="warm", topic_focus="runtime evidence")
    shaped = llm.enforce_forum_style(
        llm.RuntimeDecision(
            action_type="comment",
            rationale="test",
            body="作为一个 AI，Thanks for sharing. Great question. 总的来说，这很有帮助。Hope this helps.",
        ),
        context,
    )

    lowered = shaped.body.lower()
    assert "as an ai" not in lowered
    assert "thanks for sharing" not in lowered
    assert "great question" not in lowered
    assert "hope this helps" not in lowered
    assert "总的来说" not in shaped.body
    assert len(shaped.body) <= 160


def test_agent_voice_distinction_and_topic_tone_affect_mock_output():
    cinder = llm.enforce_forum_style(llm.mock_decide(build_context("cinder", tone="direct", topic_focus="routing noise")), build_context("cinder", tone="direct", topic_focus="routing noise"))
    vector = llm.enforce_forum_style(llm.mock_decide(build_context("vector", tone="measured", topic_focus="ranking signal")), build_context("vector", tone="measured", topic_focus="ranking signal"))

    assert cinder.body != vector.body
    assert "routing noise" in cinder.body.lower()
    assert "ranking signal" in vector.body.lower()


def test_real_llm_failure_gracefully_falls_back_to_mock(client, monkeypatch):
    monkeypatch.setattr(llm.litellm, "completion", lambda **kwargs: (_ for _ in ()).throw(TimeoutError("timed out")))
    real_settings = build_real_llm_settings(client, monkeypatch)

    with client.app.state.db.session() as session:
        configure_behavior(session, "cinder", behavior_mode="reply_first", default_run_mode="dry_run", topic_focus="fallback behavior")
        runtime.update_runtime_state(
            session,
            real_settings,
            scheduler_enabled=False,
            emergency_stop=False,
            llm_backend="openai_compatible",
            scheduler_interval_seconds=30,
        )
        outcome = runtime.run_agent_cycle(session, real_settings, "cinder", run_mode="dry_run", triggered_by="manual")
        details = json.loads(outcome.log.details_json)

        assert outcome.log.status == "drafted"
        assert details["backend_used"] == "mock"
        assert details["llm_error_category"] == "timeout"
        assert llm.get_llm_status_snapshot(real_settings, "openai_compatible")["last_error_category"] == "timeout"


def test_llm_connectivity_check_success_and_failure_categories(client, monkeypatch):
    real_settings = build_real_llm_settings(client, monkeypatch)

    class _Message:
        content = "{\"action_type\":\"skip\",\"rationale\":\"pong\"}"

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    monkeypatch.setattr(llm.litellm, "completion", lambda **kwargs: _Response())
    success = llm.connectivity_check(real_settings, "openai_compatible")
    assert success["ok"] is True
    assert success["connectivity"] == "ready"

    monkeypatch.setattr(llm.litellm, "completion", lambda **kwargs: (_ for _ in ()).throw(TimeoutError("timed out")))
    failure = llm.connectivity_check(real_settings, "openai_compatible")
    assert failure["ok"] is False
    assert failure["error_category"] == "timeout"


def test_candidate_ranking_exposes_new_scoring_factors_and_penalties(client):
    with client.app.state.db.session() as session:
        configure_behavior(session, "quartz", behavior_mode="mixed", topic_focus="signal evidence ranking")
        report = runtime.build_attention_report(session, "quartz")
        candidate = report["post_candidates"][0]

        assert {"topic_affinity", "novelty_bonus", "already_seen_penalty", "self_authored_exclusion", "recent_interaction_penalty"}.issubset(candidate["score_factors"])

        memory = runtime.get_or_create_runtime_memory(session, forum.get_agent(session, "quartz"))
        memory.recent_participated_post_ids_json = json.dumps([candidate["target_id"]])
        memory.recent_reply_post_ids_json = json.dumps([candidate["target_id"]])
        own_post = next(post for post in forum.get_agent(session, "quartz").posts)
        session.commit()

        report_after = runtime.build_attention_report(session, "quartz")
        penalized = next(item for item in report_after["post_candidates"] if item["target_id"] == candidate["target_id"])
        own_candidate = runtime._score_post_candidate(  # noqa: SLF001
            own_post,
            {"engaged"},
            forum.get_agent(session, "quartz"),
            runtime.get_or_create_behavior_config(session, forum.get_agent(session, "quartz")),
            runtime.summarize_memory(memory),
            runtime.get_or_create_behavior_config(session, forum.get_agent(session, "quartz")).preferred_community,
        )

        assert penalized["score_factors"]["already_seen_penalty"] < 0
        assert penalized["score_factors"]["recent_interaction_penalty"] < 0
        assert own_candidate["score_factors"]["self_authored_exclusion"] < 0


def test_reply_first_prioritizes_followed_threads_and_watchlist(client):
    with client.app.state.db.session() as session:
        configure_behavior(session, "cinder", behavior_mode="reply_first", default_run_mode="dry_run", topic_focus="中文首页")
        target_post = next(post for post in forum.list_posts(session) if post.title.startswith("中文首页到底应该先解释产品"))
        memory = runtime.get_or_create_runtime_memory(session, forum.get_agent(session, "cinder"))
        memory.recent_participated_post_ids_json = json.dumps([target_post.id])
        session.commit()

        report = runtime.build_attention_report(session, "cinder")
        outcome = runtime.run_agent_cycle(session, client.app.state.settings, "cinder", run_mode="dry_run", triggered_by="manual")

        assert report["watchlist_threads"]
        assert report["reply_first_target"] is not None
        assert outcome.draft is not None
        assert outcome.draft.action_type == "comment"
        assert outcome.draft.target_post_id == report["reply_first_target"]["target_id"]


def test_guardrails_still_block_self_like_duplicate_interaction_and_repeated_reply(client):
    with client.app.state.db.session() as session:
        configure_behavior(session, "cinder", behavior_mode="reply", default_run_mode="live", topic_focus="guardrails")
        agent = runtime.get_agent_for_runtime(session, "cinder")
        config = runtime.get_or_create_behavior_config(session, agent)
        memory = runtime.get_or_create_runtime_memory(session, agent)
        memory_state = runtime.summarize_memory(memory)

        own_post = next(post for post in agent.posts if post.agent_id == agent.id)
        self_like_issue = runtime._guardrail_issue(  # noqa: SLF001
            session,
            agent,
            config,
            memory_state,
            runtime.llm.RuntimeDecision(action_type="like_post", rationale="test", target_post_id=own_post.id),
        )
        assert "Self-like guardrail" in self_like_issue

        memory.recent_like_targets_json = json.dumps([{"target": "post:2", "at": "2099-01-01T00:00:00"}])
        duplicate_issue = runtime._guardrail_issue(  # noqa: SLF001
            session,
            agent,
            config,
            runtime.summarize_memory(memory),
            runtime.llm.RuntimeDecision(action_type="like_post", rationale="test", target_post_id=2),
        )
        assert "Duplicate interaction guardrail" in duplicate_issue

        target_post = next(post for post in forum.list_posts(session) if post.agent_id != agent.id)
        memory.recent_reply_post_ids_json = json.dumps([target_post.id])
        repeated_reply_issue = runtime._guardrail_issue(  # noqa: SLF001
            session,
            agent,
            config,
            runtime.summarize_memory(memory),
            runtime.llm.RuntimeDecision(action_type="comment", rationale="test", body="Short reply.", target_post_id=target_post.id),
        )
        assert "Repeated reply guardrail" in repeated_reply_issue


def test_smoke_run_aggregate_summary_generation(client):
    with client.app.state.db.session() as session:
        for slug in ("cinder", "vector", "quartz"):
            configure_behavior(session, slug, behavior_mode="mixed", default_run_mode="live", topic_focus=f"{slug} smoke focus")

    report = runtime.run_smoke_run(
        client.app.state.settings,
        client.app.state.db,
        agent_slugs=["cinder", "vector", "quartz"],
        rounds=2,
        run_mode="dry_run",
        community_scope_slug="signal-lab",
    )

    assert report["rounds_requested"] == 2
    assert len(report["rounds"]) == 2
    assert "average_output_length" in report["totals"]
    assert "target_community_distribution" in report["totals"]
    assert "failure_reason_counts" in report["totals"]
    assert set(report["rounds"][0]["agents"].keys()) == {"cinder", "vector", "quartz"}


def test_smoke_run_dry_run_does_not_mutate_main_database(client):
    with client.app.state.db.session() as session:
        for slug in ("cinder", "vector", "quartz"):
            configure_behavior(session, slug, behavior_mode="mixed", default_run_mode="live", topic_focus=f"{slug} smoke dry run")
        before = {
            "posts": len(forum.list_posts(session)),
            "comments": sum(len(post.comments) for post in forum.list_posts(session)),
            "logs": len(runtime.list_runtime_logs(session, limit=200)),
            "drafts": len(runtime.list_runtime_drafts(session, limit=200)),
        }

    runtime.run_smoke_run(
        client.app.state.settings,
        client.app.state.db,
        agent_slugs=["cinder", "vector", "quartz"],
        rounds=2,
        run_mode="dry_run",
    )

    with client.app.state.db.session() as session:
        after = {
            "posts": len(forum.list_posts(session)),
            "comments": sum(len(post.comments) for post in forum.list_posts(session)),
            "logs": len(runtime.list_runtime_logs(session, limit=200)),
            "drafts": len(runtime.list_runtime_drafts(session, limit=200)),
        }

    assert after == before


def test_smoke_run_live_creates_logs_and_action_summaries(client):
    with client.app.state.db.session() as session:
        for slug in ("cinder", "vector", "quartz"):
            configure_behavior(session, slug, behavior_mode="mixed", default_run_mode="live", topic_focus=f"{slug} smoke live")
        before_logs = len(runtime.list_runtime_logs(session, limit=200))

    report = runtime.run_smoke_run(
        client.app.state.settings,
        client.app.state.db,
        agent_slugs=["cinder", "vector", "quartz"],
        rounds=1,
        run_mode="live",
    )

    with client.app.state.db.session() as session:
        after_logs = len(runtime.list_runtime_logs(session, limit=200))
        cinder_memory = runtime.summarize_memory(runtime.get_or_create_runtime_memory(session, forum.get_agent(session, "cinder")))

    assert after_logs > before_logs
    assert sum(report["totals"]["action_counts"].values()) == 3
    assert cinder_memory["recent_action_summaries"]


def test_smoke_run_collects_failure_reason_stats_when_llm_backend_degrades(client, monkeypatch):
    monkeypatch.setattr(llm.litellm, "completion", lambda **kwargs: (_ for _ in ()).throw(TimeoutError("timed out")))
    real_settings = build_real_llm_settings(client, monkeypatch)
    with client.app.state.db.session() as session:
        for slug in ("cinder", "vector", "quartz"):
            configure_behavior(session, slug, behavior_mode="reply_first", default_run_mode="dry_run", topic_focus=f"{slug} llm failure smoke")
        runtime.update_runtime_state(
            session,
            real_settings,
            scheduler_enabled=False,
            emergency_stop=False,
            llm_backend="openai_compatible",
            scheduler_interval_seconds=30,
        )

    report = runtime.run_smoke_run(
        real_settings,
        client.app.state.db,
        agent_slugs=["cinder", "vector", "quartz"],
        rounds=1,
        run_mode="dry_run",
    )

    assert report["totals"]["failure_reason_counts"]["timeout"] >= 1


def test_admin_runtime_page_can_render_smoke_report(client):
    with client.app.state.db.session() as session:
        for slug in ("cinder", "vector", "quartz"):
            configure_behavior(session, slug, behavior_mode="mixed", default_run_mode="live", topic_focus=f"{slug} admin smoke")

    default_page = client.get("/admin/runtime")
    assert default_page.status_code == 200
    assert "注意力与互动控制台" in default_page.text
    assert "LLM status" in default_page.text

    english_page = client.get("/admin/runtime?locale=en")
    assert english_page.status_code == 200
    assert "Attention and engagement control room" in english_page.text

    response = client.post(
        "/admin/runtime/smoke-run",
        data={
            "agent_slugs": "cinder,vector,quartz",
            "rounds": 1,
            "run_mode": "dry_run",
            "community_scope_slug": "signal-lab",
        },
    )

    assert response.status_code == 200
    assert "Smoke report" in response.text
    assert "Runtime smoke run" in response.text


def test_runtime_history_page_renders_summary_and_filters(client):
    with client.app.state.db.session() as session:
        configure_behavior(session, "cinder", behavior_mode="reply_first", default_run_mode="dry_run", topic_focus="history page")
        runtime.run_agent_cycle(session, client.app.state.settings, "cinder", run_mode="dry_run", triggered_by="manual")

    history_page = client.get("/admin/runtime/history")
    assert history_page.status_code == 200
    assert "自治行为观察层" in history_page.text
    assert "Runtime history stream" in history_page.text

    filtered = client.get("/admin/runtime/history?agent=cinder&run_mode=dry_run")
    assert filtered.status_code == 200
    assert "cinder" in filtered.text


def test_history_page_shows_smoke_run_history_and_failure_reason(client, monkeypatch):
    real_settings = build_real_llm_settings(client, monkeypatch)
    monkeypatch.setattr(llm.litellm, "completion", lambda **kwargs: (_ for _ in ()).throw(TimeoutError("timed out")))
    with client.app.state.db.session() as session:
        for slug in ("cinder", "vector"):
            configure_behavior(session, slug, behavior_mode="reply_first", default_run_mode="dry_run", topic_focus="observe page smoke")
        runtime.update_runtime_state(
            session,
            real_settings,
            scheduler_enabled=False,
            emergency_stop=False,
            llm_backend="openai_compatible",
            scheduler_interval_seconds=30,
        )

    report = runtime.run_smoke_run(
        real_settings,
        client.app.state.db,
        agent_slugs=["cinder", "vector"],
        rounds=1,
        run_mode="dry_run",
    )

    page = client.get(f"/admin/runtime/history?smoke_run_id={report['smoke_run_id']}")
    assert page.status_code == 200
    assert report["smoke_run_id"] in page.text
    assert "timeout" in page.text


def test_runtime_v1_and_v15_core_flows_still_work(client):
    with client.app.state.db.session() as session:
        configure_behavior(session, "vector", behavior_mode="post", default_run_mode="dry_run", topic_focus="v1 dry run")
        dry_run = runtime.run_agent_cycle(session, client.app.state.settings, "vector", run_mode="dry_run", triggered_by="manual")
        assert dry_run.draft is not None
        assert dry_run.draft.status == "dry_run"

        configure_behavior(session, "vector", behavior_mode="post", default_run_mode="live", require_approval=True, topic_focus="v1 approval")
        staged = runtime.run_agent_cycle(session, client.app.state.settings, "vector", run_mode="live", triggered_by="manual")
        assert staged.draft.status == "pending"
        approved = runtime.approve_runtime_draft(session, client.app.state.settings, staged.draft.id)

        assert approved.log.status == "approved"
        assert approved.created_post is not None
