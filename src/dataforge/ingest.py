"""Incremental ingestion layer.

Design goals that interviewers care about:
- INCREMENTAL: each source records where it stopped (sync_state); the next run
  only fetches data newer than that point.
- IDEMPOTENT: upserts + unique keys mean re-running never duplicates rows.
- TOLERANT: per-source failures are logged and do not abort the whole run.
"""

from __future__ import annotations

import logging
from datetime import datetime
from io import StringIO

import httpx
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .db.models import Commit, CountryEconomy, Event, RepoLanguage, Repository, SyncState, User
from .github_client import GitHubClient, languages_to_percent, utcnow

log = logging.getLogger("dataforge.ingest")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _get_sync_state(session: Session, source: str) -> SyncState | None:
    return session.scalar(select(SyncState).where(SyncState.source == source))


def _save_sync_state(session: Session, source: str, last_event_date: datetime | None, rows: int) -> None:
    state = _get_sync_state(session, source)
    now = utcnow()
    if state is None:
        state = SyncState(source=source, last_sync_at=now, last_event_date=last_event_date, rows_fetched=rows)
        session.add(state)
    else:
        state.last_sync_at = now
        state.last_event_date = last_event_date
        state.rows_fetched += rows


def ingest_github(session: Session, settings: Settings) -> int:
    """Fetch users, repos, languages, recent events and recent commits.

    Events are fetched only since the last successful sync (incremental).
    Users/repos are upserted, so re-running refreshes counts without
    duplicating rows. Returns the number of newly inserted event rows.
    """
    client = GitHubClient(token=None, timeout=settings.http_timeout)
    new_events = 0
    last_event_date: datetime | None = None
    try:
        state = _get_sync_state(session, "github")
        since = state.last_event_date if state else None
        if since is None:
            since = utcnow() - pd.Timedelta(days=settings.github_days_back)

        for login in settings.github_users:
            try:
                user = client.get_user(login)
            except httpx.HTTPStatusError as exc:
                log.warning("user %s unavailable (%s); skipping", login, exc.response.status_code)
                continue

            session.merge(User(
                login=user["login"],
                name=user.get("name"),
                type=user.get("type", "User"),
                followers=user.get("followers", 0),
                created_at=_parse_dt(user.get("created_at")),
            ))

            repos = client.get_repos(login)
            for index, repo in enumerate(repos):
                full_name = repo["full_name"]
                languages: dict[str, float] = {}
                if index < settings.github_top_repos_per_user:
                    try:
                        languages = languages_to_percent(client.get_repo_languages(full_name))
                    except httpx.HTTPStatusError as exc:
                        log.warning("languages for %s unavailable (%s)", full_name, exc.response.status_code)

                existing = session.scalar(select(Repository).where(Repository.full_name == full_name))
                if existing is None:
                    existing = Repository(full_name=full_name, owner=repo["owner"]["login"], name=repo["name"])
                    session.add(existing)
                existing.stars = repo.get("stargazers_count", 0)
                existing.forks = repo.get("forks_count", 0)
                existing.open_issues = repo.get("open_issues_count", 0)
                existing.language = repo.get("language")
                existing.created_at = _parse_dt(repo.get("created_at"))
                existing.pushed_at = _parse_dt(repo.get("pushed_at"))
                session.flush()  # assign repo.id so language FKs resolve

                for lang, pct in languages.items():
                    row = session.scalar(
                        select(RepoLanguage).where(
                            RepoLanguage.repo_id == existing.id, RepoLanguage.name == lang
                        )
                    )
                    if row is None:
                        session.add(RepoLanguage(repo_id=existing.id, name=lang, percent=pct))
                    else:
                        row.percent = pct

                try:
                    commits = client.get_commits(full_name, per_page=10)
                    for c in commits:
                        session.merge(_commit_row_for(c, full_name))
                except httpx.HTTPStatusError as exc:
                    log.warning("commits for %s unavailable (%s)", full_name, exc.response.status_code)

            events = client.get_events(login, since=since, per_page=100)
            for ev in events:
                row = _event_row_for(ev, login)
                if session.scalar(select(Event).where(Event.id == ev["id"])) is None:
                    session.add(row)
                    new_events += 1
            if events:
                last_event_date = max(_parse_dt(e["created_at"]) for e in events if e.get("created_at"))
        if last_event_date is None:
            last_event_date = since
        _save_sync_state(session, "github", last_event_date, new_events)
    finally:
        client.close()
    return new_events


def _commit_row_for(c: dict, full_name: str) -> Commit:
    commit = c.get("commit", {})
    return Commit(
        sha=c["sha"],
        repo=full_name,
        message=(commit.get("message") or "").splitlines()[0][:500],
        author=(c.get("author") or {}).get("login") or (commit.get("author") or {}).get("name"),
        committed_at=_parse_dt((commit.get("author") or {}).get("date")),
    )


def _event_row_for(ev: dict, login: str) -> Event:
    return Event(
        id=ev["id"],
        user_login=login,
        type=ev.get("type", "Unknown"),
        repo=ev.get("repo"),
        created_at=_parse_dt(ev.get("created_at")),
        raw=ev,
    )


def ingest_csv(session: Session, settings: Settings) -> int:
    """Load a public CSV into country_economy. Upserted on (country, year)."""
    src = settings.csv_source
    if src.startswith(("http://", "https://")):
        resp = httpx.get(src, timeout=settings.http_timeout)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
    else:
        df = pd.read_csv(src)

    df = df.rename(columns={
        "countryName": "country",
        "year": "year",
        "lifeExp": "life_expectancy",
        "pop": "population",
        "gdpPercap": "gdp_per_cap",
    })
    df = df[["country", "year", "life_expectancy", "population", "gdp_per_cap"]]
    df["year"] = df["year"].astype(int)

    count = 0
    for row in df.itertuples(index=False):
        existing = session.scalar(
            select(CountryEconomy).where(
                CountryEconomy.country == row.country,
                CountryEconomy.year == row.year,
            )
        )
        if existing is None:
            session.add(CountryEconomy(
                country=row.country, year=row.year,
                life_expectancy=float(row.life_expectancy),
                population=float(row.population),
                gdp_per_cap=float(row.gdp_per_cap),
            ))
            count += 1
        else:
            existing.life_expectancy = float(row.life_expectancy)
            existing.population = float(row.population)
            existing.gdp_per_cap = float(row.gdp_per_cap)
    session.flush()
    _save_sync_state(session, "csv", utcnow(), count)
    return count


def run_ingest(session: Session, settings: Settings, source: str = "all") -> dict:
    """Run ingestion for one or all sources. Returns per-source row counts."""
    results = {}
    if source in ("all", "github"):
        results["github"] = ingest_github(session, settings)
        session.commit()
    if source in ("all", "csv"):
        results["csv"] = ingest_csv(session, settings)
        session.commit()
    return results
