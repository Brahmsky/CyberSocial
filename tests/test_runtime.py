from __future__ import annotations

import json

from app.services import forum, runtime


def configure_behavior(
    session,
    slug: str,
    *,
    behavior_mode: str = "mixed",
    default_run_mode: str = "dry_run",
    require_approval: bool = False,
    topic_focus: str = "runtime topic",
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
        persona_prompt=f"{agent.display_name} participates in a deterministic forum workflow.",
        tone="measured",
        topic_focus=topic_focus,
        preferred_community_slug="signal-lab",
        cooldown_minutes=0,
        max_actions_per_hour=5,
    )


def test_runtime_bootstrap_defaults_to_safe_local_state(client):
    with client.app.state.db.session() as session:
        state = runtime.get_runtime_state(session, client.app.state.settings)
        configs = runtime.list_behavior_configs(session)

        assert state.scheduler_enabled is False
        assert state.emergency_stop is False
        assert state.llm_backend == "mock"
        assert len(configs) >= 5
        assert all(config.default_run_mode == "dry_run" for config in configs)


def test_attention_candidate_ranking_includes_recent_hot_engaged_and_preferred_sources(client):
    with client.app.state.db.session() as session:
        configure_behavior(session, "cinder", behavior_mode="mixed", topic_focus="attention ranking")
        report = runtime.build_attention_report(session, "cinder")

        source_tags = {tag for candidate in report["post_candidates"] for tag in candidate["source_tags"]}

        assert {"recent", "hot", "engaged", "preferred"}.issubset(source_tags)
        assert report["best_comment_post"] is not None
        assert report["best_like_post"] is not None


def test_runtime_like_comment_action_executes_live_when_reply_targets_are_recently_used(client):
    with client.app.state.db.session() as session:
        configure_behavior(session, "vector", behavior_mode="reply", default_run_mode="live", topic_focus="light engagement")
        memory = runtime.get_or_create_runtime_memory(session, forum.get_agent(session, "vector"))
        report = runtime.build_attention_report(session, "vector")
        memory.recent_reply_post_ids_json = json.dumps([candidate["target_id"] for candidate in report["post_candidates"][:6]])
        session.commit()

        outcome = runtime.run_agent_cycle(session, client.app.state.settings, "vector", run_mode="live", triggered_by="manual")

        assert outcome.log.action_type == "like_comment"
        assert outcome.created_comment is not None
        assert outcome.log.status == "executed"


def test_runtime_like_post_action_executes_when_comment_like_is_also_recently_used(client):
    with client.app.state.db.session() as session:
        configure_behavior(session, "mirror", behavior_mode="reply", default_run_mode="live", topic_focus="reaction pass")
        agent = runtime.get_agent_for_runtime(session, "mirror")
        config = runtime.get_or_create_behavior_config(session, agent)
        target_post = next(post for post in forum.list_posts(session) if post.agent_id != agent.id)

        issue = runtime._guardrail_issue(  # noqa: SLF001
            session,
            agent,
            config,
            runtime.summarize_memory(runtime.get_or_create_runtime_memory(session, agent)),
            runtime.llm.RuntimeDecision(action_type="like_post", rationale="test", target_post_id=target_post.id),
        )
        assert issue is None

        liked_post, _ = runtime._execute_decision(  # noqa: SLF001
            session,
            agent,
            config,
            runtime.llm.RuntimeDecision(action_type="like_post", rationale="test", target_post_id=target_post.id),
        )

        assert liked_post is not None
        assert liked_post.id == target_post.id


def test_self_like_and_duplicate_interaction_guardrails_block_invalid_reactions(client):
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


def test_repeated_reply_guardrail_blocks_same_post_and_repetitive_content(client):
    with client.app.state.db.session() as session:
        configure_behavior(session, "quartz", behavior_mode="reply", default_run_mode="live", topic_focus="reply guardrail")
        agent = runtime.get_agent_for_runtime(session, "quartz")
        config = runtime.get_or_create_behavior_config(session, agent)
        memory = runtime.get_or_create_runtime_memory(session, agent)
        target_post = next(post for post in forum.list_posts(session) if post.agent_id != agent.id)
        memory.recent_reply_post_ids_json = json.dumps([target_post.id])
        memory.recent_generated_fingerprints_json = json.dumps(
            [runtime._fingerprint("Runtime reply guardrail Small implementation note: runtime reply guardrail stays visible in logs.")]  # noqa: SLF001
        )
        session.commit()

        repeated_reply_issue = runtime._guardrail_issue(  # noqa: SLF001
            session,
            agent,
            config,
            runtime.summarize_memory(memory),
            runtime.llm.RuntimeDecision(
                action_type="comment",
                rationale="test",
                body="Small implementation note: runtime reply guardrail stays visible in logs.",
                target_post_id=target_post.id,
            ),
        )
        assert "Repeated reply guardrail" in repeated_reply_issue

        repetitive_post_issue = runtime._guardrail_issue(  # noqa: SLF001
            session,
            agent,
            config,
            runtime.summarize_memory(memory),
            runtime.llm.RuntimeDecision(
                action_type="post",
                rationale="test",
                title="Runtime reply guardrail",
                body="Small implementation note: runtime reply guardrail stays visible in logs.",
                community_slug="signal-lab",
            ),
        )
        assert "Repetitive content guardrail" in repetitive_post_issue


def test_runtime_logs_include_decision_summary_and_attention_snapshot(client):
    with client.app.state.db.session() as session:
        configure_behavior(session, "cinder", behavior_mode="mixed", default_run_mode="dry_run", topic_focus="decision summary")

        outcome = runtime.run_agent_cycle(session, client.app.state.settings, "cinder", run_mode="dry_run", triggered_by="manual")
        details = json.loads(outcome.log.details_json)

        assert "decision_summary" in details
        assert "attention" in details
        assert details["attention"]["post_candidates"]
        assert details["decision_summary"]["action_type"] in runtime.ACTION_TYPES


def test_admin_runtime_page_shows_timeline_filters_and_guardrail_state(client):
    with client.app.state.db.session() as session:
        configure_behavior(session, "cinder", behavior_mode="reply", default_run_mode="live", topic_focus="admin runtime state")
        memory = runtime.get_or_create_runtime_memory(session, forum.get_agent(session, "cinder"))
        report = runtime.build_attention_report(session, "cinder")
        memory.recent_reply_post_ids_json = json.dumps([post.id for post in forum.list_posts(session)])
        memory.recent_like_targets_json = json.dumps(
            [
                {"target": f"comment:{candidate['target_id']}", "at": report["generated_at"]}
                for candidate in report["comment_candidates"]
            ]
            + [
                {"target": f"post:{candidate['target_id']}", "at": report["generated_at"]}
                for candidate in report["post_candidates"]
            ]
        )
        session.commit()
        outcome = runtime.run_agent_cycle(session, client.app.state.settings, "cinder", run_mode="live", triggered_by="manual")

        assert outcome.log.status == "skipped"
        assert "guardrail" in outcome.log.details_json.lower()

    runtime_page = client.get("/admin/runtime?agent=cinder&action=skip&status=skipped")
    assert runtime_page.status_code == 200
    assert "Recent action timeline" in runtime_page.text
    assert "Timeline filters" in runtime_page.text
    assert "Guardrail reasons" in runtime_page.text
    assert outcome.log.message in runtime_page.text
    assert "should_create_post" in runtime_page.text


def test_runtime_v1_dry_run_and_approval_flows_still_work(client):
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
