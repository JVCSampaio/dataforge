import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from dataforge.config import load_settings
from dataforge.db.models import Base, CountryEconomy, User
from dataforge.ingest import run_ingest


@pytest.fixture(scope="session")
def db_session():
    """Use the real database (compose/CI or local). Skips if unreachable."""
    settings = load_settings()
    try:
        engine = create_engine(settings.database_url)
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
    except SQLAlchemyError:
        pytest.skip("PostgreSQL not reachable at DATABASE_URL")
    return session


@pytest.fixture(scope="session")
def ingested(db_session):
    """Ingest once for the whole session, but only if the DB is empty.

    CI pre-populates via `python -m dataforge ingest --source all`, so when
    data is already present we skip re-hitting the GitHub API (faster + cheaper).
    """
    settings = load_settings()
    already = (
        db_session.scalar(select(func.count()).select_from(User)) or 0
        + (db_session.scalar(select(func.count()).select_from(CountryEconomy)) or 0)
    )
    if already > 0:
        return {"github": 0, "csv": 0}
    results = run_ingest(db_session, settings, source="all")
    db_session.commit()
    return results
