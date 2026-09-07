"""DataForge: a small, real data platform.

Pipeline: sources (GitHub API + public CSV) -> raw ingestion -> data quality
checks -> PostgreSQL -> transformation/analytics (SQL) -> FastAPI.
"""

__version__ = "0.1.0"
