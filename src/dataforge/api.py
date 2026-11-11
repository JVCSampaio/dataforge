"""FastAPI application: read-only analytics + health + quality endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from . import analytics
from .config import load_settings
from .db.models import Base
from .quality import collect_quality_run, run_all

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


@contextmanager
def _session_scope():
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@app.get("/health")
def health() -> dict:
    with _session_scope() as session:
        try:
            session.execute(text("SELECT 1"))
        except OperationalError as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        return {"status": "ok"}


@app.get("/metrics/top-repos", summary="Top repos by stars")
def top_repos(limit: int = Query(10, ge=1, le=100)) -> list[dict]:
    with _session_scope() as session:
        return analytics.top_repos_by_language(session, limit)


@app.get("/metrics/language-share", summary="Repo count and stars per language")
def language_share() -> list[dict]:
    with _session_scope() as session:
        return analytics.language_share(session)


@app.get("/metrics/event-activity", summary="Events per month (optionally per user)")
def event_activity(user: str | None = Query(None)) -> list[dict]:
    with _session_scope() as session:
        return analytics.monthly_event_activity(session, user)


@app.get("/metrics/repo-ranking", summary="Window-function ranking of repos within each owner")
def repo_ranking() -> list[dict]:
    with _session_scope() as session:
        return analytics.repo_ranking_with_gaps(session)


@app.get("/metrics/gdp-life", summary="Cross-country GDP vs life expectancy for a year")
def gdp_life(year: int = Query(2007, ge=1950, le=2100)) -> list[dict]:
    with _session_scope() as session:
        return analytics.gdp_life_scatter(session, year)


@app.get("/metrics/life-trend", summary="Life expectancy trend for one country")
def life_trend(country: str = Query("Brazil")) -> list[dict]:
    with _session_scope() as session:
        rows = analytics.life_expectancy_trend(session, country)
    if not rows:
        raise HTTPException(status_code=404, detail=f"no data for {country}")
    return rows


@app.get("/metrics/event-types", summary="Event type distribution")
def event_types(limit: int = Query(10, ge=1, le=100)) -> list[dict]:
    with _session_scope() as session:
        return analytics.top_event_types(session, limit)


@app.get("/quality", summary="Data quality report across the four checked tables")
def quality() -> list[dict]:
    with _session_scope() as session:
        return [item.to_dict() for item in run_all(session)]


@app.get("/quality/report", summary="Freshness, volume, and table checks for the latest baseline")
def quality_report() -> dict:
    """Read the full run report. This endpoint does not move `quality_baseline`."""
    settings = load_settings()
    with _session_scope() as session:
        run = collect_quality_run(
            session,
            max_age_hours=settings.quality_max_age_hours,
            drop_ratio=settings.quality_row_drop_ratio,
            update_baseline=False,
        )
        return run.to_dict()
