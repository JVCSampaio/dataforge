from sqlalchemy import delete

from dataforge.db.models import CountryEconomy, User
from dataforge.quality import check_country_economy, check_users, run_all


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
        assert isinstance(d["duplicates"], int)
        assert d["duplicates"] >= 0


def test_null_name_is_counted_without_failing(db_session):
    db_session.add(User(login="__nullname__", name=None, type="User", followers=1))
    db_session.commit()
    try:
        report = check_users(db_session)
        assert report.nulls["name"] >= 1
        assert report.passed is True
    finally:
        db_session.execute(delete(User).where(User.login == "__nullname__"))
        db_session.commit()


def test_negative_followers_fail_the_user_check(db_session):
    db_session.add(User(login="__neg__", name="Neg", type="User", followers=-5))
    db_session.commit()
    try:
        report = check_users(db_session)
        assert report.impossible_values >= 1
        assert report.passed is False
    finally:
        db_session.execute(delete(User).where(User.login == "__neg__"))
        db_session.commit()


def test_year_before_1950_fails_the_country_check(db_session):
    db_session.add(
        CountryEconomy(
            country="__bad__",
            year=1900,
            life_expectancy=70,
            population=10,
            gdp_per_cap=10,
        )
    )
    db_session.commit()
    try:
        report = check_country_economy(db_session)
        assert report.impossible_values >= 1
        assert report.passed is False
    finally:
        db_session.execute(delete(CountryEconomy).where(CountryEconomy.country == "__bad__"))
        db_session.commit()
