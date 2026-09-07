from dataforge.quality import run_all


def test_quality_report_shape(db_session):
    reports = run_all(db_session)
    assert len(reports) == 4
    tables = {r.table for r in reports}
    assert {"users", "repositories", "events", "country_economy"} <= tables
    for r in reports:
        d = r.to_dict()
        assert set(d) == {"table", "rows", "nulls", "duplicates", "impossible_values", "passed"}
        assert isinstance(d["rows"], int)
        assert isinstance(d["passed"], bool)
