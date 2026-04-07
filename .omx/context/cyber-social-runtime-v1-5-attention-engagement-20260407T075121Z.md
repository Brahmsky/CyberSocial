# Context Snapshot: cyber_social Runtime v1.5 Attention & Engagement Upgrade

## Task Statement
Upgrade the existing Runtime v1 implementation so agents behave more like lightweight forum participants: score multiple candidate targets, support likes/reacts plus skip, keep minimal continuity memory, shape outputs toward forum-native content, and expose richer runtime inspection in admin.

## Desired Outcome
- Preserve forum core, admin, API, seed data, tests, Runtime v1 behavior config/drafts/logs/approval/scheduler, and the current monolithic FastAPI + SQLite + Jinja2 + HTMX architecture.
- Each runtime round evaluates a candidate set covering recent posts, hot posts, preferred-community posts, and previously engaged posts.
- Runtime supports `like_post`, `like_comment`, and `skip` alongside post/comment actions.
- Runtime stores lightweight per-agent continuity state so repeated replies, duplicate interactions, and repetitive content are suppressed.
- Admin runtime UI shows a recent action timeline, filters by agent/action/status, guardrail statistics, and decision/candidate summaries.

## Known Facts / Evidence
- Runtime v1 already has: per-agent behavior config, dry-run/live/manual runs, runtime drafts, logs, approval flow, mock + OpenAI-compatible adapter switch, and scheduler state that defaults off.
- Existing runtime uses forum-core helpers (`create_post`, `create_comment`) for live writes and must continue reusing forum service paths instead of parallel write logic.
- Current admin runtime panel already lists controls, drafts, and logs; it is the right place to add timeline/filter/summary visibility.
- Current tests pass (`pytest` 21 passed) and compile/import checks are green before this v1.5 upgrade.

## Constraints
- Do not enter team orchestration.
- Do not re-architect into SPA, frontend/backend split, or add login/auth systems.
- Keep behavior config, drafts, logs, approval, scheduler semantics intact; extend them instead of replacing them.
- Continue local-first operation with mock backend as a valid mode.

## Unknowns / Open Questions
- None blocking. The latest user updates define the required v1.5 scope precisely enough to proceed.

## Likely Codebase Touchpoints
- `app/models.py`
- `app/services/runtime.py`
- `app/services/llm.py`
- `app/routes/admin.py`
- `app/templates/admin_runtime.html`
- `tests/test_runtime.py`
- `README.md`
