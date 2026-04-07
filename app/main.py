from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.db import build_database
from app.presentation import build_templates
from app.routes import admin, api, web
from app.seed import ensure_seed_data
from app.services import runtime


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    database = build_database(resolved_settings)
    templates = build_templates(resolved_settings)
    scheduler = runtime.RuntimeScheduler(database, resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.create_all()
        with database.session() as session:
            ensure_seed_data(session, resolved_settings)
            runtime.ensure_runtime_bootstrap(session, resolved_settings)
        scheduler.start()
        try:
            yield
        finally:
            scheduler.stop()
            database.dispose()

    app = FastAPI(title=resolved_settings.app_name, lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.db = database
    app.state.templates = templates
    app.state.runtime_scheduler = scheduler

    app.include_router(web.router)
    app.include_router(admin.router)
    app.include_router(api.router)

    return app


app = create_app()
