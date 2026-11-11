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


@pytest.mark.parametrize(
    "path",
    [
        "/metrics/event-activity",
        "/metrics/repo-ranking",
        "/metrics/gdp-life",
        "/metrics/event-types",
    ],
)
def test_metric_endpoints_return_lists(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_life_trend_returns_the_series(client, ingested):
    resp = client.get("/metrics/life-trend", params={"country": "Brazil"})
    assert resp.status_code == 200
    body = resp.json()
    assert body
    assert [row["year"] for row in body] == sorted(row["year"] for row in body)


def test_health_when_the_session_factory_is_missing(monkeypatch):
    from fastapi import HTTPException

    from dataforge.api import health

    monkeypatch.setattr("dataforge.api.SessionLocal", None)
    with pytest.raises(HTTPException) as caught:
        health()
    assert caught.value.status_code == 503


def test_health_when_the_database_is_down(monkeypatch):
    from fastapi import HTTPException
    from sqlalchemy.exc import OperationalError

    from dataforge.api import health

    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("down"))

        def close(self):
            self.closed = True

    broken = BrokenSession()
    monkeypatch.setattr("dataforge.api.SessionLocal", lambda: broken)
    with pytest.raises(HTTPException) as caught:
        health()
    assert caught.value.status_code == 503
    assert broken.closed is True


def test_quality_report_endpoint(client):
    resp = client.get("/quality/report")
    assert resp.status_code == 200
    body = resp.json()
    assert {"generated_at", "passed", "tables", "freshness", "volume"} <= set(body)
    assert len(body["tables"]) == 4
    assert {item["source"] for item in body["freshness"]} == {"github", "csv"}
    assert {item["table"] for item in body["volume"]} == {
        "users",
        "repositories",
        "languages",
        "events",
        "commits",
        "country_economy",
    }
