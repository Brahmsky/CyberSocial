# Context Snapshot: cyber_social Agent Runtime v1

## Task Statement
Add an Agent Runtime v1 to the existing cyber_social forum so enabled agents can read forum state, decide under persona + safety controls, and perform semi-automated post/comment/like actions with dry-run, approval, logs, and scheduler controls.

## Desired Outcome
- Existing forum UX and forum-core model stay intact
- Runtime behavior config is manageable from admin
- Admin can dry-run agents, approve drafts, run agents manually, and start/stop a lightweight scheduler
- Runtime uses a replaceable LLM adapter with mock mode as the safe default
- All automated behavior is rate-limited, observable, and globally stoppable

## Known Facts / Evidence
- Existing project already ships the forum MVP on FastAPI + SQLite + SQLAlchemy + Jinja2 + HTMX + Tailwind CDN.
- Current code has central forum service helpers (`create_post`, `create_comment`, `increment_post_score`) that can be reused for runtime actions.
- Admin already manages agents/communities and can reseed the database.
- Existing tests cover forum pages, API posting/commenting, likes, and admin basics.
- Current environment now has `tmux`, `omx`, and a live `$TMUX` session available; team runtime may be attempted if repo/runtime prerequisites hold.

## Constraints
- Do not rewrite the forum as SPA or split frontend/backend.
- Do not replace the forum information architecture.
- Keep dependencies light; no Redis/Celery/Kafka.
- Runtime must default to safe/local behavior: scheduler off at startup, dry-run supported, approval supported, emergency stop supported.
- Forum actions must reuse forum-core logic instead of duplicating a separate write path.

## Unknowns / Open Questions
- None blocking; the request is detailed enough to proceed directly.

## Likely Codebase Touchpoints
- `app/models.py`
- `app/config.py`
- `app/main.py`
- `app/services/forum.py`
- `app/services/llm.py`
- `app/services/runtime.py`
- `app/routes/admin.py` and/or `app/routes/runtime_admin.py`
- `app/templates/admin*.html`, new runtime templates/partials
- `app/seed.py`
- `tests/test_runtime*.py`, `tests/test_app.py`
- `README.md`, `requirements.txt`
