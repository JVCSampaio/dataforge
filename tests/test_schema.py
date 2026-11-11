from pathlib import Path

SQL = Path(__file__).resolve().parents[1] / "migrations" / "001_init.sql"


def test_documented_ddl_matches_the_models():
    text = SQL.read_text(encoding="utf-8")
    assert "id          BIGINT PRIMARY KEY" in text
    assert "CREATE TABLE IF NOT EXISTS quality_baseline (" in text
    assert "table_name   VARCHAR(50) PRIMARY KEY" in text
