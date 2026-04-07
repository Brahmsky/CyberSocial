from __future__ import annotations

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import build_settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'cyber_social-test.db').as_posix()}"
    return build_settings(root_dir=PROJECT_ROOT, database_url=database_url)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
