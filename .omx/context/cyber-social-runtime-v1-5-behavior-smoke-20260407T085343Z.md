# Context Snapshot: cyber_social Runtime v1.5 Behavior Quality + Smoke Observation

## Task Statement
Continue from the current Runtime v1.5 implementation and improve behavior quality plus real observation tooling without changing the forum architecture, auth model, or monolith structure.

## Desired Outcome
- Runtime outputs feel more like forum members and less like chatbots or customer-support summaries.
- Agent distinction is clearer across the same target thread, with tone/topic/preferred community actually influencing output.
- Candidate ranking adds explainable topic-affinity, novelty/already-seen, self-authored exclusion, and recent-interaction penalties.
- Add a lightweight smoke-run tool for 3-5 agents over multiple rounds with aggregated summaries and optional community scope.
- Surface smoke-run results in the admin runtime page.
- README gains Ralph-vs-Team guidance and cleanup guidance for stale OMX team state.

## Known Facts / Evidence
- Current repo already has forum core, admin, API, seed data, Runtime v1, and Runtime v1.5 attention/likes/lightweight memory.
- `app/services/llm.py` already has forum-style shaping hooks but still leaves room for shorter, less templated, more differentiated output.
- `app/services/runtime.py` already has candidate attention, guardrails, memory summaries, and admin timeline support.
- Fresh baseline before this iteration: `pytest` 24 passed, `compileall` passed, architect sign-off for Runtime v1.5 was approved.

## Constraints
- No team orchestration.
- No SPA, no frontend/backend split, no login/OAuth/notifications/DMs.
- Preserve existing guardrails and existing Runtime v1 / v1.5 capabilities.
- Keep local-safe defaults and reuse existing forum-core helpers for live actions.

## Unknowns / Open Questions
- None blocking after the user’s follow-up messages completed the scope.

## Likely Codebase Touchpoints
- `app/services/llm.py`
- `app/services/runtime.py`
- `app/routes/admin.py`
- `app/templates/admin_runtime.html`
- `tests/test_runtime.py`
- `README.md`
