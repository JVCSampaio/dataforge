from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select

from dataforge.db.models import QualityBaseline, SyncState
from dataforge.quality import (
    FreshnessStatus,
    QualityReport,
    QualityRun,
    VolumeStatus,
    collect_quality_run,
    freshness_status,
    render_html,
    render_markdown,
    volume_status,
    write_quality_reports,
)

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def test_freshness_status_boundaries():
    limit = timedelta(hours=36)
    assert freshness_status(None, NOW, limit) == "missing"
    assert freshness_status(NOW - timedelta(hours=1), NOW, limit) == "ok"
    assert freshness_status(NOW - timedelta(hours=36), NOW, limit) == "ok"
    assert freshness_status(NOW - timedelta(hours=36, seconds=1), NOW, limit) == "stale"
    assert freshness_status(datetime(2026, 11, 11, 10, 0), NOW, limit) == "ok"


def test_volume_status_drop_rules():
    assert volume_status(4, None, 0.5) == "no_baseline"
    assert volume_status(4, 0, 0.5) == "ok"
    assert volume_status(6, 10, 0.5) == "ok"
    assert volume_status(5, 10, 0.5) == "anomaly"
    assert volume_status(1, 3, 0.5) == "anomaly"
    assert volume_status(2, 3, 0.5) == "ok"


def test_collect_rejects_invalid_limits(db_session):
    with pytest.raises(ValueError):
        collect_quality_run(db_session, max_age_hours=0, drop_ratio=0.5, update_baseline=False)
    with pytest.raises(ValueError):
        collect_quality_run(db_session, max_age_hours=36, drop_ratio=0, update_baseline=False)


def test_volume_drop_uses_the_stored_baseline(db_session):
    db_session.execute(delete(QualityBaseline))
    db_session.add(QualityBaseline(table_name="users", row_count=1_000_000, captured_at=NOW))
    db_session.commit()
    try:
        run = collect_quality_run(
            db_session,
            max_age_hours=36,
            drop_ratio=0.5,
            now=NOW,
            update_baseline=False,
        )
        users = next(item for item in run.volume if item.table == "users")
        assert users.status == "anomaly"
        assert users.ok is False
        assert users.previous_rows == 1_000_000
        assert run.passed is False
        assert "volume users" in run.problems()
    finally:
        db_session.execute(delete(QualityBaseline))
        db_session.commit()


def test_first_run_records_baseline_and_second_run_is_stable(db_session):
    db_session.execute(delete(QualityBaseline))
    db_session.commit()
    first = collect_quality_run(db_session, max_age_hours=36, drop_ratio=0.5, update_baseline=True)
    assert all(item.status == "no_baseline" for item in first.volume)
    stored = db_session.scalar(select(func.count()).select_from(QualityBaseline))
    assert stored == 6
    second = collect_quality_run(db_session, max_age_hours=36, drop_ratio=0.5, update_baseline=True)
    assert all(item.status == "ok" for item in second.volume)
    db_session.execute(delete(QualityBaseline))
    db_session.commit()


def test_report_lists_both_sources(db_session):
    run = collect_quality_run(db_session, max_age_hours=36, drop_ratio=0.5, update_baseline=False)
    assert {item.source for item in run.freshness} == {"github", "csv"}


def test_problems_lists_every_failed_check():
    run = QualityRun(
        generated_at=NOW,
        tables=[QualityReport(table="users", rows=1, passed=False)],
        freshness=[FreshnessStatus("csv", NOW, 1.0, 36, "stale")],
        volume=[VolumeStatus("events", 1, 10, -0.9, "anomaly")],
        max_age_hours=36,
        drop_ratio=0.5,
    )
    assert run.problems() == ["tables users", "freshness csv", "volume events"]
    assert VolumeStatus("events", 1, 1, 0.0, "ok").ok is True
    only_tables = QualityRun(
        generated_at=NOW,
        tables=[QualityReport(table="users", rows=1, passed=False)],
        freshness=[FreshnessStatus("csv", NOW, 1.0, 36, "ok")],
        volume=[VolumeStatus("events", 1, 1, 0.0, "ok")],
        max_age_hours=36,
        drop_ratio=0.5,
    )
    assert only_tables.problems() == ["tables users"]


def test_fresh_sync_reports_age_and_a_stale_source_fails(db_session):
    saved: dict[str, tuple | None] = {}
    for source in ("github", "csv"):
        state = db_session.scalar(select(SyncState).where(SyncState.source == source))
        if state is None:
            saved[source] = None
            state = SyncState(source=source, rows_fetched=0)
            db_session.add(state)
        else:
            saved[source] = (state.last_sync_at, state.last_event_date, state.rows_fetched)
        state.last_sync_at = NOW - timedelta(hours=2)
    db_session.commit()
    try:
        run = collect_quality_run(
            db_session, max_age_hours=36, drop_ratio=0.5, now=NOW, update_baseline=False
        )
        github = next(item for item in run.freshness if item.source == "github")
        assert github.status == "ok"
        assert github.ok is True
        assert github.age_hours == pytest.approx(2.0)

        state = db_session.scalar(select(SyncState).where(SyncState.source == "github"))
        state.last_sync_at = datetime(2020, 1, 1, tzinfo=UTC)
        db_session.commit()
        stale = collect_quality_run(
            db_session, max_age_hours=36, drop_ratio=0.5, now=NOW, update_baseline=False
        )
        github = next(item for item in stale.freshness if item.source == "github")
        assert github.status == "stale"
        assert stale.passed is False
    finally:
        for source, previous in saved.items():
            state = db_session.scalar(select(SyncState).where(SyncState.source == source))
            if previous is None:
                if state is not None:
                    db_session.delete(state)
                continue
            state.last_sync_at, state.last_event_date, state.rows_fetched = previous
        db_session.commit()


def _sample_run() -> QualityRun:
    return QualityRun(
        generated_at=NOW,
        tables=[
            QualityReport(
                table="<users>",
                rows=2,
                nulls={"name": 1},
                duplicates=0,
                impossible_values=0,
                passed=True,
            ),
            QualityReport(table="events", rows=0, nulls={}, passed=True),
        ],
        freshness=[
            FreshnessStatus("github", None, None, 36, "missing"),
            FreshnessStatus("csv", NOW, 1.5, 36, "ok"),
        ],
        volume=[
            VolumeStatus("users", 2, 8, -0.75, "anomaly"),
            VolumeStatus("events", 1, None, None, "no_baseline"),
        ],
        max_age_hours=36,
        drop_ratio=0.5,
    )


def test_markdown_and_html_share_the_run_result(tmp_path):
    run = _sample_run()
    markdown = render_markdown(run)
    assert "Resultado da execução: reprovado" in markdown
    assert "ausente" in markdown
    assert "anomalia" in markdown
    assert "-75.0%" in markdown
    assert "sem linha de base" in markdown

    page = render_html(run)
    assert "&lt;users&gt;" in page
    assert "<users>" not in page.replace("&lt;users&gt;", "")
    assert 'class="bad"' in page
    paths = write_quality_reports(run, tmp_path)
    assert paths[0].suffix == ".md"
    assert paths[1].suffix == ".html"
    assert paths[0].read_text(encoding="utf-8") == markdown
