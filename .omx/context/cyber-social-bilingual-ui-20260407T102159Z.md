# Context Snapshot: cyber_social Lightweight Bilingual UI

## Task Statement
Add a lightweight locale layer to cyber_social with `zh-CN` default and `en` fallback, preserving the current FastAPI + SQLite + Jinja2 + HTMX monolith and keeping the forum/runtime/admin architecture intact.

## Desired Outcome
- Default UI language is Chinese (`zh-CN`)
- English (`en`) remains available through a lightweight switch
- Locale can be selected via query parameter and persisted via cookie
- Templates use a simple `t()` translation helper instead of scattered inline language checks
- Relative time and fixed status text are localized
- Public pages and admin/runtime pages follow the selected locale

## Known Facts / Evidence
- Current app already renders all public/admin/runtime UI through Jinja templates and route-local `render_template` helpers.
- Existing `relative_time` filter lives in `app/presentation.py`.
- No heavyweight i18n framework is present, which matches the requested lightweight scope.
- Current tests already cover public/admin/runtime flows and remain a good regression net.

## Constraints
- No SPA conversion
- No auth/login/OAuth additions
- No runtime rewrite
- No heavyweight i18n dependencies like Babel/gettext
- Do not translate user-generated content or seed body text
- Keep English support intact while making Chinese the default UI layer

## Unknowns / Open Questions
- None blocking. The user explicitly narrowed the scope to a minimal locale layer.

## Likely Codebase Touchpoints
- `app/config.py`
- `app/i18n.py`
- `app/presentation.py`
- `app/routes/web.py`
- `app/routes/admin.py`
- `app/templates/*.html`
- `tests/test_app.py`
- `tests/test_runtime.py`
