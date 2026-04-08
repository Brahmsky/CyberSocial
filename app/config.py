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
    llm_request_timeout_seconds: int
    llm_max_tokens: int
    llm_temperature: float
    runtime_scheduler_poll_seconds: int
    default_locale: str
    supported_locales: tuple[str, ...]
    locale_cookie_name: str


def build_settings(root_dir: Path | None = None, database_url: str | None = None) -> Settings:
    root = (root_dir or Path(__file__).resolve().parent.parent).resolve()
    data_dir = root / "data"
    templates_dir = root / "app" / "templates"
    default_database_url = f"sqlite:///{(data_dir / 'cyber_social.db').as_posix()}"

    supported_locales = tuple(
        locale.strip()
        for locale in os.getenv("CYBER_SOCIAL_SUPPORTED_LOCALES", "zh-CN,en").split(",")
        if locale.strip()
    ) or ("zh-CN", "en")

    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "")
    llm_mode = os.getenv("LLM_MODE") or os.getenv("CYBER_SOCIAL_LLM_BACKEND", "mock")
    llm_base_url = os.getenv("LLM_BASE_URL") or os.getenv("CYBER_SOCIAL_OPENAI_BASE_URL", "") or ("https://api.deepseek.com/v1" if deepseek_api_key else "")
    llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("CYBER_SOCIAL_OPENAI_API_KEY", "") or deepseek_api_key
    llm_model = os.getenv("LLM_MODEL") or os.getenv("CYBER_SOCIAL_OPENAI_MODEL", "") or ("deepseek-chat" if deepseek_api_key else "")
    llm_timeout_seconds = int(os.getenv("LLM_TIMEOUT_SECONDS") or os.getenv("CYBER_SOCIAL_LLM_TIMEOUT_SECONDS", "20"))
    llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS") or os.getenv("CYBER_SOCIAL_LLM_MAX_TOKENS", "280"))
    llm_temperature = float(os.getenv("LLM_TEMPERATURE") or os.getenv("CYBER_SOCIAL_LLM_TEMPERATURE", "0.25"))

    return Settings(
        app_name="cyber_social",
        root_dir=root,
        data_dir=data_dir,
        templates_dir=templates_dir,
        database_url=database_url or os.getenv("CYBER_SOCIAL_DATABASE_URL", default_database_url),
        operator_secret=os.getenv("CYBER_SOCIAL_OPERATOR_SECRET", "cyber-social-local-operator-secret"),
        demo_agent_slug="cinder",
        demo_agent_key="demo-cinder-001",
        default_llm_backend=llm_mode,
        openai_compatible_base_url=llm_base_url,
        openai_compatible_api_key=llm_api_key,
        openai_compatible_model=llm_model,
        llm_request_timeout_seconds=max(5, llm_timeout_seconds),
        llm_max_tokens=max(64, llm_max_tokens),
        llm_temperature=max(0.0, min(llm_temperature, 2.0)),
        runtime_scheduler_poll_seconds=max(5, int(os.getenv("CYBER_SOCIAL_RUNTIME_POLL_SECONDS", "30"))),
        default_locale=os.getenv("CYBER_SOCIAL_DEFAULT_LOCALE", "zh-CN"),
        supported_locales=supported_locales,
        locale_cookie_name=os.getenv("CYBER_SOCIAL_LOCALE_COOKIE", "cyber_social_locale"),
    )


def get_settings() -> Settings:
    return build_settings()
