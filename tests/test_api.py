import os

import pytest
from fastapi.testclient import TestClient

from dataforge.config import load_settings

os.environ.setdefault("DATABASE_URL", load_settings().database_url)

from dataforge.api import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_top_repos_endpoint(client):
    resp = client.get("/metrics/top-repos", params={"limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) <= 5


def test_language_share_endpoint(client):
    resp = client.get("/metrics/language-share")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_quality_endpoint(client):
    resp = client.get("/quality")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 4


def test_life_trend_404(client):
    resp = client.get("/metrics/life-trend", params={"country": "NoSuchCountry"})
    assert resp.status_code == 404
