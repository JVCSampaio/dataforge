from dataforge import analytics


def test_language_share(ingested, db_session):
    rows = analytics.language_share(db_session)
    assert rows
    assert all(row["repo_count"] > 0 for row in rows)


def test_top_repos_sorted(ingested, db_session):
    rows = analytics.top_repos_by_language(db_session, 5)
    assert len(rows) <= 5
    stars = [r["stars"] for r in rows]
    assert stars == sorted(stars, reverse=True)


def test_window_ranking_starts_at_one(ingested, db_session):
    rows = analytics.repo_ranking_with_gaps(db_session)
    assert rows
    seen: dict[str, list] = {}
    for row in rows:
        seen.setdefault(row["owner"], []).append(row["rank_in_owner"])
    for owner, ranks in seen.items():
        assert ranks[0] == 1, f"first rank for {owner} should be 1"


def test_monthly_events(ingested, db_session):
    rows = analytics.monthly_event_activity(db_session)
    assert rows
    assert all(r["events"] > 0 for r in rows)


def test_life_trend_sorted(ingested, db_session):
    rows = analytics.life_expectancy_trend(db_session, "Brazil")
    assert rows
    years = [r["year"] for r in rows]
    assert years == sorted(years)
