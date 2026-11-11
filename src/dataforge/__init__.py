"""DataForge: a small, real data platform.

Pipeline: sources (GitHub API + public CSV) -> raw ingestion -> data quality
checks (nulls, ranges, freshness, volume) -> PostgreSQL -> SQL analytics -> FastAPI.
"""

__version__ = "0.1.0"
