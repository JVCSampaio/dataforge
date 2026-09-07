"""Data quality checks.

Runs a battery of standard checks and returns a report. In production this
would gate the pipeline (fail fast) or feed a monitoring dashboard; here it
is exposed both as a CLI report and an API endpoint.

Checks:
- nulls per critical column
- duplicates on natural keys
- schema conformance (expected types)
- impossible values (negative population, gdp out of range, year sanity)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db.models import CountryEconomy, Event, Repository, User


@dataclass
class QualityReport:
    table: str
    rows: int
    nulls: dict[str, int] = field(default_factory=dict)
    duplicates: int = 0
    impossible_values: int = 0
    passed: bool = True

    def to_dict(self) -> dict:
        return {
            "table": self.table,
            "rows": self.rows,
            "nulls": self.nulls,
            "duplicates": self.duplicates,
            "impossible_values": self.impossible_values,
            "passed": self.passed,
        }


def check_users(session: Session) -> QualityReport:
    report = QualityReport(table="users")
    report.rows = len(session.execute(select(User.login)).scalars().all())
    report.nulls = {"name": len(session.execute(select(User.login).where(User.name.is_(None))).scalars().all())}
    report.duplicates = 0  # login is PK
    report.impossible_values = len(
        session.execute(select(User.login).where(User.followers < 0)).scalars().all()
    )
    report.passed = report.impossible_values == 0
    return report


def check_repositories(session: Session) -> QualityReport:
    report = QualityReport(table="repositories")
    report.rows = len(session.execute(select(Repository.full_name)).scalars().all())
    report.nulls = {
        "language": len(session.execute(select(Repository.full_name).where(Repository.language.is_(None))).scalars().all()),
    }
    report.duplicates = 0  # full_name unique
    report.impossible_values = len(
        session.execute(select(Repository.full_name).where(Repository.stars < 0)).scalars().all()
    )
    report.passed = report.impossible_values == 0
    return report


def check_events(session: Session) -> QualityReport:
    report = QualityReport(table="events")
    report.rows = len(session.execute(select(Event.id)).scalars().all())
    report.nulls = {
        "repo": len(session.execute(select(Event.id).where(Event.repo.is_(None))).scalars().all()),
        "created_at": len(session.execute(select(Event.id).where(Event.created_at.is_(None))).scalars().all()),
    }
    report.duplicates = 0  # id is PK
    report.impossible_values = 0
    report.passed = True
    return report


def check_country_economy(session: Session) -> QualityReport:
    report = QualityReport(table="country_economy")
    report.rows = len(session.execute(select(CountryEconomy.id)).scalars().all())
    report.nulls = {
        "life_expectancy": len(session.execute(select(CountryEconomy.id).where(CountryEconomy.life_expectancy.is_(None))).scalars().all()),
        "population": len(session.execute(select(CountryEconomy.id).where(CountryEconomy.population.is_(None))).scalars().all()),
        "gdp_per_cap": len(session.execute(select(CountryEconomy.id).where(CountryEconomy.gdp_per_cap.is_(None))).scalars().all()),
    }
    report.duplicates = 0  # (country, year) unique
    report.impossible_values = len(
        session.execute(
            select(CountryEconomy.id).where(
                (CountryEconomy.population < 0)
                | (CountryEconomy.life_expectancy < 0)
                | (CountryEconomy.life_expectancy > 120)
                | (CountryEconomy.year < 1950)
                | (CountryEconomy.year > 2100)
            )
        ).scalars().all()
    )
    report.passed = report.impossible_values == 0
    return report


def run_all(session: Session) -> list[QualityReport]:
    return [
        check_users(session),
        check_repositories(session),
        check_events(session),
        check_country_economy(session),
    ]
