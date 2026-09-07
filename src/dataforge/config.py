import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    """Runtime configuration, sourced from environment variables with sane defaults."""

    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg2://dataforge:dataforge@localhost:5432/dataforge",
        )
    )
    github_users: list[str] = field(
        default_factory=lambda: [
            u.strip()
            for u in os.getenv("GITHUB_USERS", "guillaumegomez,jakevdp,vintaugh,adamchainz").split(",")
            if u.strip()
        ]
    )
    github_days_back: int = field(default_factory=lambda: int(os.getenv("GITHUB_DAYS_BACK", "30")))
    github_top_repos_per_user: int = field(default_factory=lambda: int(os.getenv("GITHUB_TOP_REPOS_PER_USER", "10")))
    csv_source: str = field(
        default_factory=lambda: os.getenv(
            "CSV_SOURCE",
            "https://raw.githubusercontent.com/plotly/datasets/master/gapminder_unfiltered.csv",
        )
    )
    http_timeout: float = 30.0


def load_settings() -> Settings:
    return Settings()
