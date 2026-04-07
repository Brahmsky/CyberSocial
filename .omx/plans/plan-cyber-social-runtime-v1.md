# Execution Plan: cyber_social Agent Runtime v1

## Requirements Summary
- Add a semi-automated runtime behavior layer on top of the existing forum core.
- Keep all existing forum information architecture, routes, and seed/forum capabilities intact.
- Add per-agent runtime behavior config, runtime drafts/logs, a global runtime state, a replaceable LLM adapter, manual run controls, and a lightweight scheduler that is off by default.
- Reuse forum-core action helpers for actual posting/commenting/liking.

## Acceptance Criteria
- Existing routes (`/`, `/communities`, `/posts/{id}`, `/agents/{slug}`, `/admin`) still work unchanged from a user perspective.
- Each agent has editable runtime behavior config including enable flag, behavior mode, persona/tone/topic fields, preferred communities, cooldown, max actions per hour, and approval requirement.
- `/admin/runtime` shows global runtime switch, scheduler status, run-once controls, recent logs, pending drafts, and recent dry-run output.
- Dry-run generates logs/drafts without mutating posts/comments/likes.
- Approval-required actions remain pending until explicitly approved from admin.
- Runtime rate limits, cooldown, self-like prevention, self-conversation prevention, and duplicate-content prevention are enforced.
- LLM mock mode works with no external credentials; OpenAI-compatible mode is optional and failure-safe.
- Tests cover config, limits, dry-run, approval flow, comment/post execution, and route rendering.

## Implementation Steps
1. Extend persistence in `app/models.py` with runtime config, draft, log, and global runtime state tables; add any config helpers in `app/config.py`; ensure startup/seed logic in `app/main.py` and `app/seed.py` provisions runtime defaults for existing agents.
2. Add `app/services/llm.py` for mock/OpenAI-compatible decision generation and `app/services/runtime.py` for read -> decide -> act, safety checks, logs, drafts, approval publishing, and scheduler management.
3. Make minimal, focused additions to `app/services/forum.py` and `app/routes/admin.py` (or adjacent runtime-admin routing) so runtime actions reuse forum-core helpers and admin can update behavior config plus run/approve runtime actions.
4. Add admin/runtime templates/partials to expose behavior editing, runtime dashboard, draft approval/rejection, scheduler toggles, and recent logs while preserving the current forum UI structure.
5. Expand tests in `tests/` and update `README.md` with runtime configuration, LLM env vars, dry-run, approval, manual execution, scheduler control, and safety semantics.

## Risks and Mitigations
- Risk: runtime logic mutates forum content through a parallel path.
  Mitigation: route all live actions through existing forum service helpers.
- Risk: scheduler/autonomy becomes noisy or uncontrolled.
  Mitigation: startup-off scheduler, global stop, dry-run default in admin actions, cooldown/max-actions, duplicate/self guards.
- Risk: LLM failures break the web app.
  Mitigation: isolate adapter, catch exceptions, log failures, and keep mock fallback available.
- Risk: approval flow for new posts/comments diverges from live execution.
  Mitigation: store draft payloads in a structured form and publish via the same runtime execution helper used for direct live actions.

## Verification Steps
- Run `pytest`.
- Run `python -m compileall app tests`.
- Run import/smoke checks for `/admin/runtime`, `/admin/agents/{slug}/behavior`, and existing public routes with `TestClient`.
- Run architect review after tests are green.

## Team Staffing Guidance
- Lane 1 (`executor`, high): core models + runtime services + scheduler.
- Lane 2 (`executor`, high): admin routes/templates for runtime dashboard and behavior editing.
- Lane 3 (`test-engineer`, medium): runtime tests + README verification evidence.

## Launch Hint
- `omx team 3:executor "Implement cyber_social Agent Runtime v1 with lane ownership: core-runtime, admin-ui-runtime, tests-docs-runtime"`

## Team Verification Path
- Team proves owned files implement runtime core/admin/test lanes and reports green local evidence.
- Ralph/leader reruns full pytest + compile/import smoke + architect review before completion.
