from __future__ import annotations

from app.services import forum


def test_startup_seed_counts_meet_contract(client):
    with client.app.state.db.session() as session:
        agents = forum.list_agents(session, active_only=False)
        communities = forum.list_communities(session)
        posts = forum.list_posts(session)
        assert len(agents) >= 5
        assert len(communities) >= 3
        assert len(posts) >= 10


def test_public_pages_render_seeded_content(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "cyber_social" in home.text
    assert "Signal Lab" in home.text

    communities = client.get("/communities")
    assert communities.status_code == 200

    community = client.get("/communities/signal-lab")
    assert community.status_code == 200

    agents = client.get("/agents")
    assert agents.status_code == 200

    agent = client.get("/agents/cinder")
    assert agent.status_code == 200
    assert "Rep" in agent.text

    with client.app.state.db.session() as session:
        post = forum.list_posts(session)[0]
    post_detail = client.get(f"/posts/{post.id}")
    assert post_detail.status_code == 200
    assert post.title in post_detail.text


def test_browser_post_creation_flow(client):
    with client.app.state.db.session() as session:
        agent = forum.get_agent(session, "cinder")
        community = forum.get_community(session, "signal-lab")

    response = client.post(
        "/posts/new",
        data={
            "agent_id": agent.id,
            "community_id": community.id,
            "title": "Browser-created MVP checkpoint",
            "body": "The UI flow can create a forum thread without leaving the browser.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    redirected = client.get(response.headers["location"])
    assert redirected.status_code == 200
    assert "Browser-created MVP checkpoint" in redirected.text


def test_empty_comment_submission_is_rejected(client):
    with client.app.state.db.session() as session:
        agent = forum.get_agent(session, "cinder")
        post = next(post for post in forum.list_posts(session) if post.title.startswith("Why agent identity"))

    response = client.post(
        f"/posts/{post.id}/comments",
        data={"agent_id": agent.id, "body": "   "},
    )
    assert response.status_code == 400
    assert "Comment body cannot be empty." in response.text


def test_api_post_creation_accepts_valid_agent_key(client):
    response = client.post(
        "/api/agents/cinder/posts",
        headers={"X-Agent-Key": "demo-cinder-001"},
        json={
            "community_slug": "signal-lab",
            "title": "API-authored thread",
            "body": "The API can publish as an authenticated agent.",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["title"] == "API-authored thread"


def test_api_post_creation_rejects_invalid_agent_key(client):
    response = client.post(
        "/api/agents/cinder/posts",
        headers={"X-Agent-Key": "wrong-key"},
        json={
            "community_slug": "signal-lab",
            "title": "Should fail",
            "body": "This request should be rejected.",
        },
    )
    assert response.status_code == 403


def test_api_post_creation_rejects_missing_agent_key(client):
    response = client.post(
        "/api/agents/cinder/posts",
        json={
            "community_slug": "signal-lab",
            "title": "Should fail",
            "body": "This request should be rejected.",
        },
    )
    assert response.status_code == 401


def test_api_comment_creation_and_like_endpoints(client):
    with client.app.state.db.session() as session:
        post = next(post for post in forum.list_posts(session) if post.title.startswith("Why agent identity"))
        seeded_comment = post.comments[0]

    comment_response = client.post(
        "/api/agents/cinder/comments",
        headers={"X-Agent-Key": "demo-cinder-001"},
        json={"post_id": post.id, "body": "API comment from the demo agent.", "parent_id": seeded_comment.id},
    )
    assert comment_response.status_code == 201
    comment_payload = comment_response.json()
    assert comment_payload["ok"] is True
    assert comment_payload["data"]["parent_id"] == seeded_comment.id

    like_post = client.post(f"/api/posts/{post.id}/like")
    assert like_post.status_code == 200
    assert like_post.json()["data"]["score"] >= post.score + 1

    like_comment = client.post(f"/api/comments/{seeded_comment.id}/like")
    assert like_comment.status_code == 200
    assert like_comment.json()["data"]["score"] >= seeded_comment.score + 1


def test_admin_routes_support_management_flows(client):
    admin_page = client.get("/admin")
    assert admin_page.status_code == 200

    create_agent = client.post(
        "/admin/agents",
        data={
            "display_name": "Signal Finch",
            "avatar": "🛰️",
            "tagline": "Lightweight scout",
            "bio": "Watches for interesting anomalies.",
            "capability_summary": "Scanning, tagging",
            "owner_note": "Created in test.",
            "requested_slug": "signal-finch",
        },
    )
    assert create_agent.status_code == 201
    assert "Signal Finch" in create_agent.text

    reveal_key = client.get("/admin/agents/signal-finch/key")
    assert reveal_key.status_code == 200
    assert "Save now" in reveal_key.text

    rotate_key = client.post("/admin/agents/signal-finch/reset-key")
    assert rotate_key.status_code == 200
    assert "Save now" in rotate_key.text

    reseed = client.post("/admin/reseed")
    assert reseed.status_code == 200
    assert "Database reseeded" in reseed.text


def test_json_envelope_routes_return_expected_shape(client):
    communities = client.get("/api/communities")
    agents = client.get("/api/agents")
    with client.app.state.db.session() as session:
        post = forum.list_posts(session)[0]
    post_detail = client.get(f"/api/posts/{post.id}")

    for response in (communities, agents, post_detail):
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert "data" in payload
