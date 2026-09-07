"""Thin, dependency-light client for the public GitHub REST API.

Uses httpx directly (no github3/PyGithub) to keep the stack minimal.
All calls are read-only and respect a single shared client so connections are
reused across an ingestion run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Self

import httpx

GITHUB_API = "https://api.github.com"


class GitHubClient:
    def __init__(self, token: str | None = None, timeout: float = 30.0):
        self._client = httpx.Client(
            base_url=GITHUB_API,
            timeout=timeout,
            headers={"Accept": "application/vnd.github+json"},
        )
        if token:
            self._client.headers["Authorization"] = f"Bearer {token}"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        resp = self._client.get(path, params=params or {})
        resp.raise_for_status()
        return resp.json()

    def get_user(self, login: str) -> dict:
        return self._get(f"/users/{login}")

    def get_repos(self, login: str, per_page: int = 30) -> list[dict]:
        return self._get(f"/users/{login}/repos", params={"per_page": per_page, "sort": "pushed"})

    def get_repo_languages(self, full_name: str) -> dict[str, float]:
        """Return {language: bytes}; callers convert to percentages."""
        return self._get(f"/repos/{full_name}/languages")

    def get_events(self, login: str, since: datetime | None = None, per_page: int = 100) -> list[dict]:
        params: dict = {"per_page": per_page}
        if since is not None:
            params["since"] = since.isoformat()
        return self._get(f"/users/{login}/events", params=params)

    def get_commits(self, full_name: str, per_page: int = 30) -> list[dict]:
        return self._get(f"/repos/{full_name}/commits", params={"per_page": per_page})


def languages_to_percent(raw: dict[str, int]) -> dict[str, float]:
    """Convert GitHub's byte counts to percentages of the total."""
    total = sum(raw.values())
    if not total:
        return {}
    return {lang: round(b / total * 100, 2) for lang, b in raw.items()}


def utcnow() -> datetime:
    return datetime.now(UTC)
