import json
from datetime import UTC, datetime

from dataforge.cli import main
from dataforge.quality import FreshnessStatus, QualityRun


def test_db_init_cli(db_session, capsys):
    assert main(["db-init"]) == 0
    assert "tables created" in capsys.readouterr().out


def test_metrics_cli(db_session, capsys):
    assert main(["metrics", "--top", "2"]) == 0
    assert "top_repos" in capsys.readouterr().out


def test_ingest_cli_reads_a_local_csv(db_session, tmp_path, monkeypatch, capsys):
    from sqlalchemy import delete, select

    from dataforge.db.models import CountryEconomy, SyncState

    path = tmp_path / "mini.csv"
    path.write_text(
        "country,year,lifeExp,pop,gdpPercap\nCliland,2004,66,7,3\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CSV_SOURCE", str(path))
    state = db_session.scalar(select(SyncState).where(SyncState.source == "csv"))
    saved = None if state is None else (state.last_sync_at, state.last_event_date, state.rows_fetched)
    try:
        assert main(["ingest", "--source", "csv"]) == 0
        assert json.loads(capsys.readouterr().out)["csv"] == 1
    finally:
        db_session.execute(delete(CountryEconomy).where(CountryEconomy.country == "Cliland"))
        state = db_session.scalar(select(SyncState).where(SyncState.source == "csv"))
        if saved is None:
            if state is not None:
                db_session.delete(state)
        else:
            state.last_sync_at, state.last_event_date, state.rows_fetched = saved
        db_session.commit()


def test_quality_cli_writes_reports(db_session, tmp_path, capsys):
    assert main(["quality", "--output-dir", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert len(payload) == 4
    markdown = list(tmp_path.glob("quality-*.md"))
    html = list(tmp_path.glob("quality-*.html"))
    assert len(markdown) == 1
    assert len(html) == 1
    body = markdown[0].read_text(encoding="utf-8")
    assert "Frescor das fontes" in body
    assert "## Volume" in body


def test_quality_cli_uses_report_dir_from_env(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("QUALITY_REPORT_DIR", str(tmp_path))
    assert main(["quality"]) == 0
    assert list(tmp_path.glob("quality-*.md"))


def test_quality_strict_exits_when_the_run_fails(monkeypatch):
    class Session:
        def close(self):
            self.closed = True

    session = Session()
    monkeypatch.setattr("dataforge.cli.make_session", lambda url: session)
    failed = QualityRun(
        generated_at=datetime(2026, 11, 11, tzinfo=UTC),
        tables=[],
        freshness=[FreshnessStatus("github", None, None, 36, "missing")],
        volume=[],
        max_age_hours=36,
        drop_ratio=0.5,
    )
    monkeypatch.setattr("dataforge.cli.collect_quality_run", lambda *args, **kwargs: failed)
    assert main(["quality", "--strict"]) == 1
    assert session.closed is True


def test_quality_strict_exits_zero_when_the_run_passes(monkeypatch, capsys):
    class Session:
        def close(self):
            self.closed = True

    session = Session()
    monkeypatch.setattr("dataforge.cli.make_session", lambda url: session)
    passed = QualityRun(
        generated_at=datetime(2026, 11, 11, tzinfo=UTC),
        tables=[],
        freshness=[],
        volume=[],
        max_age_hours=36,
        drop_ratio=0.5,
    )
    monkeypatch.setattr("dataforge.cli.collect_quality_run", lambda *args, **kwargs: passed)
    assert main(["quality", "--strict"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert session.closed is True
