# Execution Plan: cyber_social MVP

## Requirements Summary
- Build a local-first agent-native forum using FastAPI, SQLite, SQLAlchemy, Jinja2, HTMX, Tailwind CDN, and minimal JavaScript.
- Ship public pages: `/`, `/communities`, `/communities/{slug}`, `/posts/{id}`, `/agents`, `/agents/{slug}`, `/posts/new`, `/admin`.
- Ship JSON API for agents, communities, posts, key-authenticated posting/commenting, and likes.
- Seed the database so first launch is populated and demonstrable.
- Keep the product forum-shaped, dark/cyber, and centered on agent identity.

## RALPLAN-DR Summary
### Principles
- Preserve forum-first information architecture over chat metaphors.
- Keep the stack local, inspectable, and easy to run.
- Make agent identity visible on every content surface.
- Favor simple, testable business rules over opaque heuristics.

### Decision Drivers
- Fast local setup with minimal tooling
- Product completeness over architectural sophistication
- Clear split between public agent surfaces and backstage admin controls

### Viable Options
#### Option A: Server-rendered FastAPI + Jinja2 + HTMX
Pros:
- Direct fit for the required stack
- Low operational complexity
- Easy to seed and verify end-to-end locally
Cons:
- More template code
- Interactivity remains intentionally modest

#### Option B: API-first backend plus SPA frontend
Pros:
- Richer client interactions
- Clear API/UI separation
Cons:
- Violates the requested low-complexity local stack
- Adds unnecessary build and state-management overhead

Decision:
- Choose Option A. Option B is rejected because it increases implementation complexity without improving the MVP goals.

## ADR
### Decision
Implement the MVP as a monolithic FastAPI app with SQLAlchemy models, server-rendered Jinja2 templates, HTMX-enhanced form interactions, and a SQLite database initialized on startup.

### Drivers
- Requested stack matches server rendering
- Empty workspace favors a cohesive monolith
- MVP requires complete product delivery, not API-only scaffolding

### Alternatives Considered
- SPA frontend with separate API backend
- CLI-only prototype with no public UI
- Flat single-file FastAPI app

### Why Chosen
- Monolith reduces integration overhead and keeps the codebase understandable.
- Server-rendered pages satisfy public UI and admin UI quickly.
- Separate routers/services/models preserve enough structure without over-engineering.

### Consequences
- Template logic must stay disciplined.
- Some repeated composition helpers are acceptable to keep routes readable.
- SQLite limits concurrency, but that is acceptable for local-first MVP scope.

### Follow-ups
- Optional future Alembic migration path
- Optional richer moderation and analytics
- Optional agent automation hooks for scheduled posting

## Acceptance Criteria
- App boots with `uvicorn app.main:app --reload`.
- First boot creates tables and seeds data automatically if the DB is empty.
- Homepage is non-empty and visually communicates an agent-native forum.
- All required public/admin pages return `200`.
- Agent profile shows reputation, posts, comments, and communities.
- Post detail shows markdown-rendered body and nested comments.
- UI and API both support agent-authored posts/comments.
- Invalid keys are rejected with `401`/`403`.
- Likes update post/comment scores and affect reputation/hot sorting.
- Smoke tests pass via `pytest`.

## Implementation Steps
1. Create project skeleton, app factory, configuration, DB session management, SQLAlchemy models, and seed pipeline.
2. Implement forum services for querying home/community/post/agent views, hot ranking, comment tree assembly, and reputation aggregation.
3. Implement HTML routes and Jinja templates for the required public pages plus local admin CRUD/reset actions.
4. Implement JSON API routes for listing entities, posting/commenting via `X-Agent-Key`, and liking posts/comments.
5. Add styling, HTMX behaviors, smoke tests, and README operational docs.

## Risks and Mitigations
- Risk: Template-heavy UI becomes inconsistent.
Mitigation: Use shared base/partials and unified card/profile styling tokens.

- Risk: Secret key handling leaks plain keys.
Mitigation: Hash stored keys, show/reset plain key only at creation/reset time, document seeded demo keys separately.

- Risk: Seed data duplicates on repeated startup.
Mitigation: Guard seeding on empty database and provide explicit reseed admin action.

- Risk: Nested comments become awkward to query.
Mitigation: Keep tree building in service layer and support practical MVP nesting depth.

## Verification Steps
- Run `pytest`.
- Run a local import/startup smoke check with FastAPI test client.
- Confirm seeded counts for agents, communities, posts, comments.
- Validate API key-auth post creation in tests.

## Available-Agent-Types Roster
- `executor` (`gpt-5.4`, high): implementation lanes
- `test-engineer` (`gpt-5.4`, medium): test authoring and verification evidence
- `architect` (`gpt-5.4`, high): final design/quality review
- `writer` (`gpt-5.4-mini`, high): README and operational docs

## Follow-up Staffing Guidance
### Ralph path
- 1 `executor` lane for core backend/routes/models
- 1 `test-engineer` lane for tests and API verification
- 1 `architect` review lane after green verification

### Team path
- 2 implementation workers and 1 verification/docs worker
- Worker split:
  - Lane 1: backend/domain logic
  - Lane 2: templates/static/admin
  - Lane 3: tests/README/verification evidence

## Launch Hints
- Team runtime hint: `omx team 3:executor "Build cyber_social MVP from approved plan in D:\\Personal\\Desktop\\个人开发\\CyberSocial with lane ownership: backend, ui-admin, tests-docs"`
- Ralph follow-up hint: `$ralph implement .omx/plans/plan-cyber-social.md with full verification`

## Team Verification Path
- Team proves that owned files are implemented, local tests are authored/run, and README/admin/API flows are covered before shutdown.
- Ralph or leader verifies final integrated app, reruns tests, checks diagnostics, and closes state.

## Changelog
- Initial direct plan authored from fully specified user requirements.
