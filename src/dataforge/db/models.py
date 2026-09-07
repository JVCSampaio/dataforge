from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    login: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20))
    followers: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(255), unique=True)
    owner: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    stars: Mapped[int] = mapped_column(Integer, default=0)
    forks: Mapped[int] = mapped_column(Integer, default=0)
    open_issues: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RepoLanguage(Base):
    __tablename__ = "languages"
    __table_args__ = (UniqueConstraint("repo_id", "name", name="uq_languages_repo_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[int] = mapped_column(Integer, ForeignKey("repositories.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    percent: Mapped[float] = mapped_column(Float, default=0.0)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_login: Mapped[str] = mapped_column(String(100), index=True)
    type: Mapped[str] = mapped_column(String(50))
    repo: Mapped[str | None] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw: Mapped[dict | None] = mapped_column(JSON)


class Commit(Base):
    __tablename__ = "commits"
    __table_args__ = (UniqueConstraint("sha", "repo", name="uq_commits_sha_repo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sha: Mapped[str] = mapped_column(String(40), index=True)
    repo: Mapped[str] = mapped_column(String(255), index=True)
    message: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(200))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CountryEconomy(Base):
    __tablename__ = "country_economy"
    __table_args__ = (UniqueConstraint("country", "year", name="uq_country_year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country: Mapped[str] = mapped_column(String(100), index=True)
    year: Mapped[int] = mapped_column(Integer)
    life_expectancy: Mapped[float | None] = mapped_column(Float)
    population: Mapped[float | None] = mapped_column(Float)
    gdp_per_cap: Mapped[float | None] = mapped_column(Float)


class SyncState(Base):
    """Bookkeeping for incremental ingestion: where each source last stopped."""

    __tablename__ = "sync_state"

    source: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_fetched: Mapped[int] = mapped_column(Integer, default=0)
