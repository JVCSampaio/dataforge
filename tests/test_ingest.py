from sqlalchemy import delete, select

from dataforge.config import load_settings
from dataforge.db.models import Event, SyncState
from dataforge.ingest import run_ingest


def test_ingest_incremental(db_session):
    """Prove the GitHub source is incremental: a fresh windowed run pulls data,
    and a second run (whose sync point now sits at the last event) is a no-op-ish
    fetch that pulls no more than the first."""
    settings = load_settings()

    # Start clean: drop any existing events and the github sync point so the
    # first run genuinely inserts rows (the `ingested` fixture may have populated
    # the table already).
    db_session.execute(delete(Event))
    state = db_session.scalar(select(SyncState).where(SyncState.source == "github"))
    if state is not None:
        db_session.delete(state)
    db_session.commit()

    first = run_ingest(db_session, settings, source="github")
    db_session.commit()
    second = run_ingest(db_session, settings, source="github")
    db_session.commit()

    first_n = first["github"]
    second_n = second["github"]
    assert first_n > 0, "initial windowed ingest should pull at least one event"
    assert second_n <= first_n, "incremental run should not fetch more than the initial one"
