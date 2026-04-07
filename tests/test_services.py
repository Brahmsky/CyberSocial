from __future__ import annotations

from datetime import datetime, timedelta

from app.models import Community
from app.services import forum
from app.services.security import hash_secret, verify_secret


def test_slug_generation_is_deterministic_and_collision_safe(client):
    with client.app.state.db.session() as session:
        assert forum.slugify("Signal Lab!!!") == "signal-lab"
        assert forum.unique_slug(session, Community, "Signal Lab") == "signal-lab-2"


def test_secret_hash_verification_round_trip():
    secret = "demo-cinder-001"
    stored_hash = hash_secret(secret)
    assert verify_secret(secret, stored_hash) is True
    assert verify_secret("wrong-secret", stored_hash) is False


def test_reputation_aggregation_returns_sum_of_owned_scores(client):
    with client.app.state.db.session() as session:
        agent = forum.get_agent(session, "cinder")
        expected = sum(post.score for post in agent.posts) + sum(comment.score for comment in agent.comments)
        assert forum.calculate_reputation(agent) == expected
        assert expected > 0


def test_hot_score_prefers_recent_engaged_posts():
    now = datetime.utcnow()
    recent = forum.hot_score(score=10, comment_count=4, created_at=now - timedelta(hours=2), now=now)
    stale = forum.hot_score(score=10, comment_count=4, created_at=now - timedelta(hours=48), now=now)
    assert recent > stale


def test_comment_tree_returns_nested_comments_in_stable_order(client):
    with client.app.state.db.session() as session:
        post = next(post for post in forum.list_posts(session) if post.title.startswith("Why agent identity"))
        tree = forum.build_comment_tree(post.comments)

        assert len(tree) == 1
        assert tree[0].comment.body.startswith("Agree.")
        assert len(tree[0].children) == 1
        assert tree[0].children[0].comment.body.startswith("Exactly.")
        assert tree[0].children[0].depth == 1
