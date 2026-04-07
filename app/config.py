from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    app_name: str
    root_dir: Path
    data_dir: Path
    templates_dir: Path
    database_url: str
    operator_secret: str
    demo_agent_slug: str
    demo_agent_key: str
    default_llm_backend: str
    openai_compatible_base_url: str
    openai_compatible_api_key: str
    openai_compatible_model: str
    runtime_scheduler_poll_seconds: int


def build_settings(root_dir: Path | None = None, database_url: str | None = None) -> Settings:
    root = (root_dir or Path(__file__).resolve().parent.parent).resolve()
    data_dir = root / "data"
    templates_dir = root / "app" / "templates"
    default_database_url = f"sqlite:///{(data_dir / 'cyber_social.db').as_posix()}"

    return Settings(
        app_name="cyber_social",
        root_dir=root,
        data_dir=data_dir,
        templates_dir=templates_dir,
        database_url=database_url or os.getenv("CYBER_SOCIAL_DATABASE_URL", default_database_url),
        operator_secret=os.getenv("CYBER_SOCIAL_OPERATOR_SECRET", "cyber-social-local-operator-secret"),
        demo_agent_slug="cinder",
        demo_agent_key="demo-cinder-001",
        default_llm_backend=os.getenv("CYBER_SOCIAL_LLM_BACKEND", "mock"),
        openai_compatible_base_url=os.getenv("CYBER_SOCIAL_OPENAI_BASE_URL", ""),
        openai_compatible_api_key=os.getenv("CYBER_SOCIAL_OPENAI_API_KEY", ""),
        openai_compatible_model=os.getenv("CYBER_SOCIAL_OPENAI_MODEL", ""),
        runtime_scheduler_poll_seconds=max(5, int(os.getenv("CYBER_SOCIAL_RUNTIME_POLL_SECONDS", "30"))),
    )


def get_settings() -> Settings:
    return build_settings()
