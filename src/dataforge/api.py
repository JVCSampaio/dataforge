"""FastAPI application: read-only analytics + health + quality endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from . import analytics
from .config import load_settings
from .db.models import Base
from .quality import run_all

engine = None
SessionLocal = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, SessionLocal
    settings = load_settings()
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    yield
    engine.dispose()


app = FastAPI(
    title="DataForge Analytics API",
    version="0.1.0",
    description="Read-only analytics over ingested GitHub + public CSV data.",
    lifespan=lifespan,
)


def _session():
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    return SessionLocal()


@app.get("/health")
def health() -> dict:
    session = _session()
    try:
        session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except OperationalError:
        raise HTTPException(status_code=503, detail="database unavailable")


@app.get("/metrics/top-repos", summary="Top repos by stars")
def top_repos(limit: int = Query(10, ge=1, le=100)) -> list[dict]:
    return analytics.top_repos_by_language(_session(), limit)


@app.get("/metrics/language-share", summary="Repo count and stars per language")
def language_share() -> list[dict]:
    return analytics.language_share(_session())


@app.get("/metrics/event-activity", summary="Events per month (optionally per user)")
def event_activity(user: str | None = Query(None)) -> list[dict]:
    return analytics.monthly_event_activity(_session(), user)


@app.get("/metrics/repo-ranking", summary="Window-function ranking of repos within each owner")
def repo_ranking() -> list[dict]:
    return analytics.repo_ranking_with_gaps(_session())


@app.get("/metrics/gdp-life", summary="Cross-country GDP vs life expectancy for a year")
def gdp_life(year: int = Query(2007, ge=1950, le=2100)) -> list[dict]:
    return analytics.gdp_life_scatter(_session(), year)


@app.get("/metrics/life-trend", summary="Life expectancy trend for one country")
def life_trend(country: str = Query("Brazil")) -> list[dict]:
    rows = analytics.life_expectancy_trend(_session(), country)
    if not rows:
        raise HTTPException(status_code=404, detail=f"no data for {country}")
    return rows


@app.get("/metrics/event-types", summary="Event type distribution")
def event_types(limit: int = Query(10, ge=1, le=100)) -> list[dict]:
    return analytics.top_event_types(_session(), limit)


@app.get("/quality", summary="Data quality report across all tables")
def quality() -> list[dict]:
    return [r.to_dict() for r in run_all(_session())]
