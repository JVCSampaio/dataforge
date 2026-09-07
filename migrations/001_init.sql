-- DataForge initial schema (PostgreSQL). Applied automatically by `python -m dataforge db-init`
-- via SQLAlchemy metadata; this file documents the canonical DDL.

CREATE TABLE IF NOT EXISTS users (
    login      VARCHAR(100) PRIMARY KEY,
    name       VARCHAR(200),
    type       VARCHAR(20) NOT NULL,
    followers  INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS repositories (
    id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name    VARCHAR(255) NOT NULL UNIQUE,
    owner        VARCHAR(100) NOT NULL,
    name         VARCHAR(200) NOT NULL,
    stars        INTEGER NOT NULL DEFAULT 0,
    forks        INTEGER NOT NULL DEFAULT 0,
    open_issues  INTEGER NOT NULL DEFAULT 0,
    language     VARCHAR(100),
    created_at   TIMESTAMPTZ,
    pushed_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS languages (
    id       INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repo_id  INTEGER NOT NULL REFERENCES repositories(id),
    name     VARCHAR(100) NOT NULL,
    percent  DOUBLE PRECISION NOT NULL DEFAULT 0,
    UNIQUE (repo_id, name)
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    user_login  VARCHAR(100) NOT NULL,
    type        VARCHAR(50) NOT NULL,
    repo        VARCHAR(255),
    created_at  TIMESTAMPTZ NOT NULL,
    raw         JSON
);
CREATE INDEX IF NOT EXISTS idx_events_user ON events (user_login);
CREATE INDEX IF NOT EXISTS idx_events_repo ON events (repo);
CREATE INDEX IF NOT EXISTS idx_events_created ON events (created_at);

CREATE TABLE IF NOT EXISTS commits (
    id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sha          VARCHAR(40) NOT NULL,
    repo         VARCHAR(255) NOT NULL,
    message      TEXT,
    author       VARCHAR(200),
    committed_at TIMESTAMPTZ,
    UNIQUE (sha, repo)
);
CREATE INDEX IF NOT EXISTS idx_commits_repo ON commits (repo);
CREATE INDEX IF NOT EXISTS idx_commits_sha ON commits (sha);

CREATE TABLE IF NOT EXISTS country_economy (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    country         VARCHAR(100) NOT NULL,
    year            INTEGER NOT NULL,
    life_expectancy DOUBLE PRECISION,
    population      DOUBLE PRECISION,
    gdp_per_cap     DOUBLE PRECISION,
    UNIQUE (country, year)
);
CREATE INDEX IF NOT EXISTS idx_country_economy_country ON country_economy (country);

CREATE TABLE IF NOT EXISTS sync_state (
    source          VARCHAR(50) PRIMARY KEY,
    last_sync_at    TIMESTAMPTZ,
    last_event_date TIMESTAMPTZ,
    rows_fetched    INTEGER NOT NULL DEFAULT 0
);
