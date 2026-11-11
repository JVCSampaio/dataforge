from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete, select

from dataforge.config import Settings, load_settings
from dataforge.db.models import Commit, CountryEconomy, Event, RepoLanguage, Repository, SyncState, User
from dataforge.ingest import event_is_in_window, ingest_csv, ingest_github, run_ingest


def _sync_snapshot(session, source: str) -> dict | None:
    state = session.scalar(select(SyncState).where(SyncState.source == source))
    if state is None:
        return None
    return {
        "last_sync_at": state.last_sync_at,
        "last_event_date": state.last_event_date,
        "rows_fetched": state.rows_fetched,
    }


def _restore_sync(session, source: str, saved: dict | None) -> None:
    state = session.scalar(select(SyncState).where(SyncState.source == source))
    if saved is None:
        if state is not None:
            session.delete(state)
        return
    if state is None:
        state = SyncState(source=source)
        session.add(state)
    state.last_sync_at = saved["last_sync_at"]
    state.last_event_date = saved["last_event_date"]
    state.rows_fetched = saved["rows_fetched"]


def _event_snapshot(session) -> list[dict]:
    return [
        {
            "id": row.id,
            "user_login": row.user_login,
            "type": row.type,
            "repo": row.repo,
            "created_at": row.created_at,
            "raw": row.raw,
        }
        for row in session.scalars(select(Event))
    ]


def test_missing_timestamps_do_not_move_the_watermark():
    from dataforge.ingest import _later, _parse_dt

    stamp = datetime(2024, 6, 1, tzinfo=UTC)
    assert _parse_dt(None) is None
    assert _parse_dt("") is None
    assert _later(stamp, None) == stamp
    assert _later(None, None) is None


def test_event_window_keeps_the_boundary():
    stamp = datetime(2024, 6, 1, tzinfo=UTC)
    assert event_is_in_window(stamp, stamp) is True
    assert event_is_in_window(stamp - timedelta(seconds=1), stamp) is False
    assert event_is_in_window(None, stamp) is True
    assert event_is_in_window(stamp, None) is True
    assert event_is_in_window(datetime(2024, 6, 1), stamp) is True


def test_ingest_incremental(db_session):
    """A windowed GitHub run inserts events, and the next run does not insert more."""
    settings = load_settings()
    saved_events = _event_snapshot(db_session)
    saved_state = _sync_snapshot(db_session, "github")
    db_session.execute(delete(Event))
    state = db_session.scalar(select(SyncState).where(SyncState.source == "github"))
    if state is not None:
        db_session.delete(state)
    db_session.commit()

    try:
        first = run_ingest(db_session, settings, source="github")
        db_session.commit()
        second = run_ingest(db_session, settings, source="github")
        db_session.commit()

        first_n = first["github"]
        second_n = second["github"]
        assert first_n > 0, "initial windowed ingest should pull at least one event"
        assert second_n <= first_n, "incremental run should not fetch more than the initial one"
    finally:
        db_session.rollback()
        db_session.execute(delete(Event))
        for row in saved_events:
            db_session.add(Event(**row))
        _restore_sync(db_session, "github", saved_state)
        db_session.commit()


def test_github_watermark_is_the_newest_event_across_users(db_session, monkeypatch):
    """A 404 user is skipped, old events stay out, and the watermark is the global max."""
    watermark = datetime(2024, 6, 1, tzinfo=UTC)
    newest = datetime(2024, 8, 1, tzinfo=UTC)
    events = {
        "alpha": [
            {
                "id": 9000000000001,
                "type": "WatchEvent",
                "repo": {"name": "alpha/old"},
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "id": 9000000000002,
                "type": "PushEvent",
                "repo": {"name": "alpha/edge"},
                "created_at": "2024-06-01T00:00:00Z",
            },
            {
                "id": 9000000000003,
                "type": "PushEvent",
                "repo": {"name": "alpha/new"},
                "created_at": "2024-08-01T00:00:00Z",
            },
        ],
        "beta": [
            {
                "id": 9000000000004,
                "type": "IssuesEvent",
                "repo": {"name": "beta/mid"},
                "created_at": "2024-07-01T00:00:00Z",
            },
        ],
    }
    opened: list = []

    class FakeGitHub:
        def __init__(self, token=None, timeout=30.0):
            self.closed = False
            opened.append(self)

        def close(self):
            self.closed = True

        def get_user(self, login):
            if login == "ghost":
                request = httpx.Request("GET", "https://api.github.com/users/ghost")
                response = httpx.Response(404, request=request)
                raise httpx.HTTPStatusError("missing", request=request, response=response)
            return {
                "login": login,
                "name": login,
                "type": "User",
                "followers": 2,
                "created_at": "2014-01-01T00:00:00Z",
            }

        def get_repos(self, login):
            return []

        def get_events(self, login, per_page=100):
            return events[login]

    monkeypatch.setattr("dataforge.ingest.GitHubClient", FakeGitHub)
    saved_state = _sync_snapshot(db_session, "github")
    state = db_session.scalar(select(SyncState).where(SyncState.source == "github"))
    if state is None:
        state = SyncState(source="github", rows_fetched=0)
        db_session.add(state)
    state.last_event_date = watermark
    state.last_sync_at = watermark
    state.rows_fetched = 0
    db_session.commit()

    settings = Settings(
        database_url=load_settings().database_url,
        github_users=["ghost", "alpha", "beta"],
        github_days_back=30,
        github_top_repos_per_user=1,
        github_token=None,
    )
    try:
        inserted = ingest_github(db_session, settings)
        db_session.commit()
        assert inserted == 3
        assert opened[-1].closed is True
        assert db_session.get(User, "ghost") is None
        assert db_session.get(Event, 9000000000001) is None
        assert db_session.get(Event, 9000000000003) is not None
        stored = db_session.scalar(select(SyncState).where(SyncState.source == "github"))
        assert stored.last_event_date == newest
        assert stored.rows_fetched == 3

        again = ingest_github(db_session, settings)
        db_session.commit()
        assert again == 0
        stored = db_session.scalar(select(SyncState).where(SyncState.source == "github"))
        assert stored.last_event_date == newest
    finally:
        db_session.rollback()
        db_session.execute(delete(Event).where(Event.id >= 9000000000001))
        db_session.execute(delete(User).where(User.login.in_(["ghost", "alpha", "beta"])))
        _restore_sync(db_session, "github", saved_state)
        db_session.commit()


def test_csv_upsert_is_idempotent_and_stores_nulls(db_session, tmp_path):
    csv_path = tmp_path / "mini.csv"
    csv_path.write_text(
        "country,year,lifeExp,pop,gdpPercap\nTestland,2001,70,1000,50\nNulland,2002,,5,1.5\n",
        encoding="utf-8",
    )
    settings = load_settings()
    settings.csv_source = str(csv_path)
    saved_state = _sync_snapshot(db_session, "csv")
    try:
        assert ingest_csv(db_session, settings) == 2
        db_session.commit()
        assert ingest_csv(db_session, settings) == 0
        db_session.commit()
        missing = db_session.scalar(select(CountryEconomy).where(CountryEconomy.country == "Nulland"))
        assert missing.life_expectancy is None
        assert missing.population == 5

        csv_path.write_text(
            "country,year,lifeExp,pop,gdpPercap\nTestland,2001,71,1100,55\nNulland,2002,,5,1.5\n",
            encoding="utf-8",
        )
        assert ingest_csv(db_session, settings) == 0
        db_session.commit()
        updated = db_session.scalar(
            select(CountryEconomy).where(CountryEconomy.country == "Testland", CountryEconomy.year == 2001)
        )
        assert updated.life_expectancy == 71
        assert updated.population == 1100
        assert updated.gdp_per_cap == 55
    finally:
        db_session.rollback()
        db_session.execute(delete(CountryEconomy).where(CountryEconomy.country.in_(["Testland", "Nulland"])))
        _restore_sync(db_session, "csv", saved_state)
        db_session.commit()


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.github.com/missing")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("missing", request=request, response=response)


def test_github_upserts_repo_language_and_commit(db_session, monkeypatch):
    repo = {
        "full_name": "repo-user/demo",
        "owner": {"login": "repo-user"},
        "name": "demo",
        "stargazers_count": 3,
        "forks_count": 1,
        "open_issues_count": 0,
        "language": "Python",
        "created_at": "2020-01-01T00:00:00Z",
        "pushed_at": "2024-01-01T00:00:00Z",
    }
    languages = {"Python": 80, "SQL": 20}
    commits = [
        {
            "sha": "a" * 40,
            "commit": {
                "message": "first line\nbody",
                "author": {"name": "Repo User", "date": "2024-01-02T00:00:00Z"},
            },
            "author": {"login": "repo-user"},
        },
        {
            "sha": "b" * 40,
            "commit": {
                "message": "named only",
                "author": {"name": "Ada", "date": "2024-01-03T00:00:00Z"},
            },
            "author": None,
        },
    ]

    class FakeGitHub:
        def __init__(self, token=None, timeout=30.0):
            self.closed = False

        def close(self):
            self.closed = True

        def get_user(self, login):
            return {
                "login": login,
                "name": "Repo User",
                "type": "User",
                "followers": 4,
                "created_at": "2015-01-01T00:00:00Z",
            }

        def get_repos(self, login):
            return [repo]

        def get_repo_languages(self, full_name):
            return languages

        def get_commits(self, full_name, per_page=10):
            return commits

        def get_events(self, login, per_page=100):
            return []

    monkeypatch.setattr("dataforge.ingest.GitHubClient", FakeGitHub)
    saved_state = _sync_snapshot(db_session, "github")
    settings = Settings(
        database_url=load_settings().database_url,
        github_users=["repo-user"],
        github_top_repos_per_user=1,
        github_token=None,
    )
    try:
        assert ingest_github(db_session, settings) == 0
        db_session.commit()
        stored_repo = db_session.scalar(select(Repository).where(Repository.full_name == "repo-user/demo"))
        assert stored_repo.stars == 3
        lang_rows = db_session.scalars(
            select(RepoLanguage).where(RepoLanguage.repo_id == stored_repo.id)
        ).all()
        assert {row.name: row.percent for row in lang_rows} == {"Python": 80.0, "SQL": 20.0}
        named = db_session.scalar(select(Commit).where(Commit.sha == "b" * 40))
        assert named.author == "Ada"
        message = db_session.scalar(select(Commit).where(Commit.sha == "a" * 40))
        assert message.message == "first line"

        repo["stargazers_count"] = 9
        languages["Python"] = 70
        languages["SQL"] = 30
        commits[0]["commit"]["message"] = "updated"
        assert ingest_github(db_session, settings) == 0
        db_session.commit()
        db_session.refresh(stored_repo)
        assert stored_repo.stars == 9
        db_session.refresh(message)
        assert message.message == "updated"
        refreshed = db_session.scalars(
            select(RepoLanguage).where(RepoLanguage.repo_id == stored_repo.id)
        ).all()
        assert {row.name: row.percent for row in refreshed}["Python"] == 70.0
    finally:
        db_session.rollback()
        db_session.execute(delete(Commit).where(Commit.repo == "repo-user/demo"))
        repo_row = db_session.scalar(select(Repository).where(Repository.full_name == "repo-user/demo"))
        if repo_row is not None:
            db_session.execute(delete(RepoLanguage).where(RepoLanguage.repo_id == repo_row.id))
            db_session.delete(repo_row)
        db_session.execute(delete(User).where(User.login == "repo-user"))
        _restore_sync(db_session, "github", saved_state)
        db_session.commit()


def test_github_skips_unavailable_repo_details(db_session, monkeypatch):
    class FakeGitHub:
        def __init__(self, token=None, timeout=30.0):
            pass

        def close(self):
            pass

        def get_user(self, login):
            return {"login": login, "name": login, "type": "User", "followers": 1, "created_at": None}

        def get_repos(self, login):
            return [
                {
                    "full_name": "error-user/demo",
                    "owner": {"login": "error-user"},
                    "name": "demo",
                    "stargazers_count": 1,
                    "forks_count": 0,
                    "open_issues_count": 0,
                    "language": None,
                    "created_at": None,
                    "pushed_at": None,
                }
            ]

        def get_repo_languages(self, full_name):
            raise _http_error(403)

        def get_commits(self, full_name, per_page=10):
            raise _http_error(409)

        def get_events(self, login, per_page=100):
            raise _http_error(403)

    monkeypatch.setattr("dataforge.ingest.GitHubClient", FakeGitHub)
    saved_state = _sync_snapshot(db_session, "github")
    settings = Settings(
        database_url=load_settings().database_url,
        github_users=["error-user"],
        github_top_repos_per_user=1,
        github_token=None,
    )
    try:
        assert ingest_github(db_session, settings) == 0
        db_session.commit()
        assert (
            db_session.scalar(select(Repository).where(Repository.full_name == "error-user/demo")) is not None
        )
        assert db_session.scalar(select(Commit).where(Commit.repo == "error-user/demo")) is None
    finally:
        db_session.rollback()
        repo_row = db_session.scalar(select(Repository).where(Repository.full_name == "error-user/demo"))
        if repo_row is not None:
            db_session.execute(delete(RepoLanguage).where(RepoLanguage.repo_id == repo_row.id))
            db_session.delete(repo_row)
        db_session.execute(delete(User).where(User.login == "error-user"))
        _restore_sync(db_session, "github", saved_state)
        db_session.commit()


def test_csv_http_source_is_loaded(db_session, monkeypatch):
    class Response:
        text = "country,year,lifeExp,pop,gdpPercap\nHttpland,2003,60,9,2\n"

        def raise_for_status(self):
            return None

    monkeypatch.setattr("dataforge.ingest.httpx.get", lambda *args, **kwargs: Response())
    settings = load_settings()
    settings.csv_source = "https://example.com/gap.csv"
    saved_state = _sync_snapshot(db_session, "csv")
    try:
        assert ingest_csv(db_session, settings) == 1
        db_session.commit()
        row = db_session.scalar(select(CountryEconomy).where(CountryEconomy.country == "Httpland"))
        assert row.gdp_per_cap == 2
    finally:
        db_session.rollback()
        db_session.execute(delete(CountryEconomy).where(CountryEconomy.country == "Httpland"))
        _restore_sync(db_session, "csv", saved_state)
        db_session.commit()


def test_lookback_window_skips_old_events_and_extra_repos(db_session, monkeypatch):
    recent = datetime.now(UTC).replace(microsecond=0)
    old = recent - timedelta(days=10)

    def _repo(name: str) -> dict:
        return {
            "full_name": name,
            "owner": {"login": "window-user"},
            "name": name.split("/", 1)[1],
            "stargazers_count": 1,
            "forks_count": 0,
            "open_issues_count": 0,
            "language": "Python",
            "created_at": "2020-01-01T00:00:00Z",
            "pushed_at": "2024-01-01T00:00:00Z",
        }

    class FakeGitHub:
        def __init__(self, token=None, timeout=30.0):
            pass

        def close(self):
            pass

        def get_user(self, login):
            return {
                "login": login,
                "name": login,
                "type": "User",
                "followers": 1,
                "created_at": "2016-01-01T00:00:00Z",
            }

        def get_repos(self, login):
            return [_repo("window-user/first"), _repo("window-user/second")]

        def get_repo_languages(self, full_name):
            assert full_name == "window-user/first"
            return {"Python": 10}

        def get_commits(self, full_name, per_page=10):
            return []

        def get_events(self, login, per_page=100):
            return [
                {
                    "id": 9000000000201,
                    "type": "PushEvent",
                    "repo": {"name": "window-user/new"},
                    "created_at": recent.isoformat(),
                },
                {
                    "id": 9000000000202,
                    "type": "PushEvent",
                    "repo": {"name": "window-user/old"},
                    "created_at": old.isoformat(),
                },
            ]

    monkeypatch.setattr("dataforge.ingest.GitHubClient", FakeGitHub)
    saved_state = _sync_snapshot(db_session, "github")
    state = db_session.scalar(select(SyncState).where(SyncState.source == "github"))
    if state is not None:
        db_session.delete(state)
        db_session.commit()
    settings = Settings(
        database_url=load_settings().database_url,
        github_users=["window-user"],
        github_days_back=1,
        github_top_repos_per_user=1,
        github_token=None,
    )
    try:
        result = run_ingest(db_session, settings, source="github")
        assert result == {"github": 1}
        assert db_session.get(Event, 9000000000201) is not None
        assert db_session.get(Event, 9000000000202) is None
        second = db_session.scalar(select(Repository).where(Repository.full_name == "window-user/second"))
        assert db_session.scalars(select(RepoLanguage).where(RepoLanguage.repo_id == second.id)).all() == []
    finally:
        db_session.rollback()
        db_session.execute(delete(Event).where(Event.id >= 9000000000201))
        db_session.execute(delete(Commit).where(Commit.repo.like("window-user/%")))
        for full_name in ("window-user/first", "window-user/second"):
            repo_row = db_session.scalar(select(Repository).where(Repository.full_name == full_name))
            if repo_row is not None:
                db_session.execute(delete(RepoLanguage).where(RepoLanguage.repo_id == repo_row.id))
                db_session.delete(repo_row)
        db_session.execute(delete(User).where(User.login == "window-user"))
        _restore_sync(db_session, "github", saved_state)
        db_session.commit()
