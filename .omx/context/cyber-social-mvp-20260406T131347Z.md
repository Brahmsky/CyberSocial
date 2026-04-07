# Context Snapshot: cyber_social MVP

## Task Statement
Build a complete local-first "agent-native forum" MVP named `cyber_social` from an empty workspace using FastAPI, SQLite, SQLAlchemy, Jinja2, HTMX, native JavaScript, and Tailwind CDN.

## Desired Outcome
- A runnable local web app served by `uvicorn`
- Seeded SQLite database with agents, communities, posts, comments, likes
- Public forum UI plus local admin UI
- JSON API authenticated by per-agent secret keys
- Tests, README, and startup instructions included

## Known Facts / Evidence
- Workspace root `D:\Personal\Desktop\个人开发\CyberSocial` is currently empty.
- `python --version` returns `Python 3.13.7`.
- `pip --version` returns `pip 25.2`.
- `git status` reports this is not a git repository.
- Shell preflight does not expose `tmux` or `omx` commands, so `$team` must use OMX MCP runtime tools instead of shell CLI entrypoints.
- User explicitly requires `$plan`, `$team`, and `$ralph` semantics, plus direct end-to-end implementation without stopping for confirmation.

## Constraints
- No login system, OAuth, external identity provider, X integration, SaaS billing, websocket, or chatbot-style UI.
- Keep the product forum-first with agent identity, public threads, reputation, and communities.
- Use no heavy frontend build system; Tailwind via CDN is acceptable.
- Keep code structured but not over-engineered.
- Provide seed data large enough that the home page is non-empty on first run.

## Unknowns / Open Questions
- None blocking. Scope and stack are fully specified by the user.

## Likely Codebase Touchpoints
- `app/main.py`
- `app/db.py`
- `app/models.py`
- `app/services/*`
- `app/routes/*`
- `app/templates/*`
- `app/static/*`
- `app/seed.py`
- `tests/*`
- `requirements.txt`
- `README.md`

## Execution Notes
- Ralph planning gate requires `prd-*` and `test-spec-*` artifacts before implementation.
- Team runtime should be used for bounded parallel assistance only after the planning artifacts exist.
