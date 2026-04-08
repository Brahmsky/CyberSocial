# Context Snapshot: cyber_social Runtime v2 Real LLM + Limited Autonomy

## Task Statement
Upgrade the existing runtime stack to Runtime v2 by improving real LLM integration, adding reply-first limited autonomy, strengthening continuity and observation, and keeping all existing safety controls and monolithic architecture intact.

## Desired Outcome
- Real `openai_compatible` mode becomes a usable, configurable runtime backend
- Runtime remains safe under failure and can gracefully fall back to mock or stop without crashing
- Agents prioritize reply-follow-up over autonomous new posts via reply-first modes
- Existing dry-run, approval, logs, scheduler-off-by-default, global stop, and smoke-run ideas all remain intact and become more observable
- Admin runtime page shows LLM health/configuration, ongoing thread-follow state, smoke-run summaries, failure reasons, and agent autonomy status

## Known Facts / Evidence
- Current runtime already has mock/openai-compatible branching, dry-run/live/approval, candidate attention scoring, lightweight continuity memory, guardrails, smoke-run summary, and admin timeline.
- Config still uses `CYBER_SOCIAL_*` names for LLM env values and lacks the requested `LLM_*` aliases plus structured LLM operational settings.
- Existing runtime tests cover shaping, ranking factors, smoke-run summaries, guardrails, and admin runtime rendering, but not real LLM error classes or reply-first thread-follow behavior.
- Fresh baseline before this iteration: `pytest` 27 passed, `compileall` passed, diagnostics clean.

## Constraints
- No team orchestration
- No SPA or architecture rewrite
- Do not rewrite forum core, API contract, or database main model
- Keep runtime main framework and safety mechanisms; extend in-place
- No heavy autonomy, distributed queues, Redis/Celery/Kafka, or vector-memory infrastructure

## Unknowns / Open Questions
- None blocking. The user defined clear behavioral and safety boundaries.

## Likely Codebase Touchpoints
- `app/config.py`
- `app/services/llm.py`
- `app/services/runtime.py`
- `app/routes/admin.py`
- `app/templates/admin_runtime.html`
- `tests/test_runtime.py`
- `README.md`
