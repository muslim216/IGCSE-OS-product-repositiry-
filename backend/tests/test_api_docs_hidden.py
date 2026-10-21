"""SA-12: the interactive docs and the route map are not public on a deployment."""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

PATHS = ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"]


@pytest.mark.parametrize("path", PATHS)
def test_docs_are_404_when_deployed(monkeypatch, path):
    monkeypatch.setattr(get_settings(), "render", True)
    app = create_app()
    assert TestClient(app).get(path).status_code == 404
    # Only the URLs go; the schema itself is still buildable.
    assert app.openapi()["paths"]


@pytest.mark.parametrize("path", PATHS)
def test_docs_stay_up_locally(monkeypatch, path):
    monkeypatch.setattr(get_settings(), "render", False)
    assert TestClient(create_app()).get(path).status_code == 200
