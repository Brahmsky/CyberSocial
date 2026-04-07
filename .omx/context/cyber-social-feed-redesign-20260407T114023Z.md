# Context Snapshot: cyber_social Feed IA + Visual Redesign

## Task Statement
Refactor the public frontend information architecture and visual layout so cyber_social feels closer to a Weibo-style information feed while preserving the existing routes, data model, forum-first identity, single FastAPI + Jinja2 + HTMX architecture, and current functionality.

## Desired Outcome
- Compact top navigation
- Desktop three-column public layout with natural collapse on smaller screens
- Home becomes a feed-first community homepage rather than a concept landing page
- Posts render as denser, lighter feed units instead of oversized dark cards
- Community pages, agent directory, agent profile, post detail, and new post composer all adopt a more content-first Chinese-friendly reading rhythm
- No backend logic changes beyond small context helpers if layout needs them

## Known Facts / Evidence
- Current site already has locale helpers and localized public/admin templates, so the redesign must preserve that layer.
- Existing macro structure (`macros.html`) already owns post cards, score badges, and nested comment blocks, making it a good consolidation point for feed components.
- Routes already provide enough forum data for most pages; only lightweight sidebar/shell context may need to be added.
- Current test suite is green and primarily asserts route status plus selected content markers, so visual template restructuring can proceed safely as long as key content remains rendered.

## Constraints
- Do not enter team orchestration
- Do not change database models, forum service main logic, or runtime main logic
- Do not convert to SPA or add JS frameworks
- Do not add Weibo business features; only borrow layout and information hierarchy ideas
- Keep public/admin/runtime pages functional

## Unknowns / Open Questions
- None blocking. The user explicitly constrained the scope to front-end IA/visual restructuring.

## Likely Codebase Touchpoints
- `app/routes/web.py`
- `app/templates/base.html`
- `app/templates/home.html`
- `app/templates/communities.html`
- `app/templates/community_detail.html`
- `app/templates/agents.html`
- `app/templates/agent_detail.html`
- `app/templates/post_detail.html`
- `app/templates/new_post.html`
- `app/templates/macros.html`
- `app/templates/partials/score_badge.html`
