"""Analytics layer: non-trivial SQL (CTEs, window functions, aggregations).

These queries are the "show me you know SQL" part of the project. Each one is
a real business question, not a toy SELECT.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def top_repos_by_language(session: Session, limit: int = 10) -> list[dict]:
    """Top repos per language by stars (JOIN repositories -> repo_languages,
    aggregation + ordering)."""
    q = text(
        """
        SELECT r.full_name, rl.name AS language, r.stars, r.forks, r.open_issues
        FROM repositories r
        JOIN repo_languages rl ON rl.repo_id = r.id
        WHERE rl.percent >= 50
        ORDER BY r.stars DESC
        LIMIT :limit
        """
    )
    return [dict(row._mapping) for row in session.execute(q, {"limit": limit})]


def language_share(session: Session) -> list[dict]:
    """Share of tracked repos per language (aggregation)."""
    q = text(
        """
        SELECT language, COUNT(*) AS repo_count, SUM(stars) AS total_stars
        FROM repositories
        WHERE language IS NOT NULL
        GROUP BY language
        ORDER BY repo_count DESC, total_stars DESC
        """
    )
    return [dict(row._mapping) for row in session.execute(q)]


def monthly_event_activity(session: Session, user: str | None = None) -> list[dict]:
    """Events per month, optionally per user (aggregation over time)."""
    q = text(
        """
        SELECT date_trunc('month', created_at) AS month, COUNT(*) AS events
        FROM events
        WHERE (:user IS NULL OR user_login = :user)
        GROUP BY month
        ORDER BY month
        """
    )
    return [dict(row._mapping) for row in session.execute(q, {"user": user})]


def repo_ranking_with_gaps(session: Session) -> list[dict]:
    """
    Window functions: rank repos within each owner by stars and compute the
    star gap to the previous repo of the same owner.
    """
    q = text(
        """
        WITH ranked AS (
            SELECT full_name, owner, language, stars,
                   ROW_NUMBER() OVER (PARTITION BY owner ORDER BY stars DESC) AS rank_in_owner,
                   LAG(stars) OVER (PARTITION BY owner ORDER BY stars DESC) AS prev_stars
            FROM repositories
        )
        SELECT full_name, owner, language, stars, rank_in_owner,
               COALESCE(stars - prev_stars, 0) AS star_gap_to_prev
        FROM ranked
        ORDER BY owner, rank_in_owner
        """
    )
    return [dict(row._mapping) for row in session.execute(q)]


def gdp_life_scatter(session: Session, year: int) -> list[dict]:
    """Cross-country comparison for a given year (filter + select)."""
    q = text(
        """
        SELECT country, life_expectancy, population, gdp_per_cap
        FROM country_economy
        WHERE year = :year
        ORDER BY gdp_per_cap DESC
        """
    )
    return [dict(row._mapping) for row in session.execute(q, {"year": year})]


def life_expectancy_trend(session: Session, country: str) -> list[dict]:
    """Trend of life expectancy for one country over years (time series)."""
    q = text(
        """
        SELECT year, life_expectancy, gdp_per_cap
        FROM country_economy
        WHERE country = :country
        ORDER BY year
        """
    )
    return [dict(row._mapping) for row in session.execute(q, {"country": country})]


def top_event_types(session: Session, limit: int = 10) -> list[dict]:
    """Which event types dominate (aggregation)."""
    q = text(
        """
        SELECT type, COUNT(*) AS n
        FROM events
        GROUP BY type
        ORDER BY n DESC
        LIMIT :limit
        """
    )
    return [dict(row._mapping) for row in session.execute(q, {"limit": limit})]
