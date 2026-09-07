from sqlalchemy import create_engine

from .models import Base


def init_db(database_url: str) -> None:
    """Create all tables. Idempotent (CREATE TABLE IF NOT EXISTS semantics via create_all)."""
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
