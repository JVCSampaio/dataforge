"""Data quality checks and the per-run report.

Table checks cover nulls, duplicate natural keys, and impossible values.
The run report adds source freshness and row-count drops against the previous
execution, then renders the same result as Markdown and HTML.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db.models import (
    Commit,
    CountryEconomy,
    Event,
    QualityBaseline,
    RepoLanguage,
    Repository,
    SyncState,
    User,
)

log = logging.getLogger("dataforge.quality")

TRACKED_SOURCES = ("github", "csv")
VOLUME_TABLES = (
    "users",
    "repositories",
    "languages",
    "events",
    "commits",
    "country_economy",
)
_VOLUME_MODELS = {
    "users": User,
    "repositories": Repository,
    "languages": RepoLanguage,
    "events": Event,
    "commits": Commit,
    "country_economy": CountryEconomy,
}
_STATUS_PT = {
    "ok": "ok",
    "stale": "atrasada",
    "missing": "ausente",
    "no_baseline": "sem linha de base",
    "anomaly": "anomalia",
    "failed": "reprovado",
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).isoformat()


def _count(session: Session, model, *criteria) -> int:
    statement = select(func.count()).select_from(model)
    if criteria:
        statement = statement.where(*criteria)
    return int(session.scalar(statement) or 0)


def _duplicate_groups(session: Session, model, *columns) -> int:
    grouped = select(*columns).group_by(*columns).having(func.count() > 1).subquery()
    return int(session.scalar(select(func.count()).select_from(grouped)) or 0)


@dataclass
class QualityReport:
    table: str
    rows: int
    nulls: dict[str, int] = field(default_factory=dict)
    duplicates: int = 0
    impossible_values: int = 0
    passed: bool = True

    def to_dict(self) -> dict:
        return {
            "table": self.table,
            "rows": self.rows,
            "nulls": self.nulls,
            "duplicates": self.duplicates,
            "impossible_values": self.impossible_values,
            "passed": self.passed,
        }


@dataclass
class FreshnessStatus:
    source: str
    last_sync_at: datetime | None
    age_hours: float | None
    max_age_hours: float
    status: str

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "last_sync_at": _iso(self.last_sync_at),
            "age_hours": None if self.age_hours is None else round(self.age_hours, 2),
            "max_age_hours": self.max_age_hours,
            "status": self.status,
        }


@dataclass
class VolumeStatus:
    table: str
    rows: int
    previous_rows: int | None
    change_ratio: float | None
    status: str

    @property
    def ok(self) -> bool:
        return self.status != "anomaly"

    def to_dict(self) -> dict:
        return {
            "table": self.table,
            "rows": self.rows,
            "previous_rows": self.previous_rows,
            "change_ratio": None if self.change_ratio is None else round(self.change_ratio, 4),
            "status": self.status,
        }


@dataclass
class QualityRun:
    generated_at: datetime
    tables: list[QualityReport]
    freshness: list[FreshnessStatus]
    volume: list[VolumeStatus]
    max_age_hours: float
    drop_ratio: float

    @property
    def passed(self) -> bool:
        return (
            all(item.passed for item in self.tables)
            and all(item.ok for item in self.freshness)
            and all(item.ok for item in self.volume)
        )

    def problems(self) -> list[str]:
        items: list[str] = []
        failed = [item.table for item in self.tables if not item.passed]
        if failed:
            items.append("tables " + ", ".join(failed))
        stale = [item.source for item in self.freshness if not item.ok]
        if stale:
            items.append("freshness " + ", ".join(stale))
        drops = [item.table for item in self.volume if item.status == "anomaly"]
        if drops:
            items.append("volume " + ", ".join(drops))
        return items

    def to_dict(self) -> dict:
        return {
            "generated_at": _iso(self.generated_at),
            "passed": self.passed,
            "max_age_hours": self.max_age_hours,
            "drop_ratio": self.drop_ratio,
            "tables": [item.to_dict() for item in self.tables],
            "freshness": [item.to_dict() for item in self.freshness],
            "volume": [item.to_dict() for item in self.volume],
        }


def check_users(session: Session) -> QualityReport:
    report = QualityReport(table="users", rows=_count(session, User))
    report.nulls = {"name": _count(session, User, User.name.is_(None))}
    report.duplicates = _duplicate_groups(session, User, User.login)
    report.impossible_values = _count(session, User, User.followers < 0)
    report.passed = report.impossible_values == 0
    return report


def check_repositories(session: Session) -> QualityReport:
    report = QualityReport(table="repositories", rows=_count(session, Repository))
    report.nulls = {"language": _count(session, Repository, Repository.language.is_(None))}
    report.duplicates = _duplicate_groups(session, Repository, Repository.full_name)
    report.impossible_values = _count(session, Repository, Repository.stars < 0)
    report.passed = report.impossible_values == 0
    return report


def check_events(session: Session) -> QualityReport:
    report = QualityReport(table="events", rows=_count(session, Event))
    report.nulls = {
        "repo": _count(session, Event, Event.repo.is_(None)),
        "created_at": _count(session, Event, Event.created_at.is_(None)),
    }
    report.duplicates = _duplicate_groups(session, Event, Event.id)
    report.impossible_values = 0
    report.passed = report.impossible_values == 0
    return report


def check_country_economy(session: Session) -> QualityReport:
    report = QualityReport(table="country_economy", rows=_count(session, CountryEconomy))
    report.nulls = {
        "life_expectancy": _count(session, CountryEconomy, CountryEconomy.life_expectancy.is_(None)),
        "population": _count(session, CountryEconomy, CountryEconomy.population.is_(None)),
        "gdp_per_cap": _count(session, CountryEconomy, CountryEconomy.gdp_per_cap.is_(None)),
    }
    report.duplicates = _duplicate_groups(
        session, CountryEconomy, CountryEconomy.country, CountryEconomy.year
    )
    report.impossible_values = _count(
        session,
        CountryEconomy,
        (CountryEconomy.population < 0)
        | (CountryEconomy.life_expectancy < 0)
        | (CountryEconomy.life_expectancy > 120)
        | (CountryEconomy.year < 1950)
        | (CountryEconomy.year > 2100),
    )
    report.passed = report.impossible_values == 0
    return report


def run_all(session: Session) -> list[QualityReport]:
    return [
        check_users(session),
        check_repositories(session),
        check_events(session),
        check_country_economy(session),
    ]


def freshness_status(last_sync_at: datetime | None, now: datetime, max_age: timedelta) -> str:
    """Classify one source. Missing sync data is `missing`; older than the limit is `stale`."""
    if last_sync_at is None:
        return "missing"
    if _as_utc(now) - _as_utc(last_sync_at) > max_age:
        return "stale"
    return "ok"


def volume_status(current: int, previous: int | None, drop_ratio: float) -> str:
    """Compare a row count with the previous run.

    The first observation (`previous is None`) is `no_baseline`. A drop of
    `drop_ratio` or more, when the previous count was positive, is `anomaly`.
    """
    if previous is None:
        return "no_baseline"
    if previous <= 0:
        return "ok"
    if current <= previous * (1 - drop_ratio):
        return "anomaly"
    return "ok"


def _validate_limits(max_age_hours: float, drop_ratio: float) -> None:
    if max_age_hours <= 0:
        raise ValueError("QUALITY_MAX_AGE_HOURS must be positive")
    if not 0 < drop_ratio <= 1:
        raise ValueError("QUALITY_ROW_DROP_RATIO must be in the interval (0, 1]")


def collect_quality_run(
    session: Session,
    *,
    max_age_hours: float,
    drop_ratio: float,
    now: datetime | None = None,
    update_baseline: bool = False,
) -> QualityRun:
    """Build the run report. Set `update_baseline` from the CLI and the DAG, not from the API."""
    _validate_limits(max_age_hours, drop_ratio)
    moment = now or datetime.now(UTC)
    max_age = timedelta(hours=max_age_hours)
    tables = run_all(session)
    baselines = {row.table_name: row for row in session.scalars(select(QualityBaseline))}

    volume: list[VolumeStatus] = []
    counts: dict[str, int] = {}
    for name in VOLUME_TABLES:
        current = _count(session, _VOLUME_MODELS[name])
        counts[name] = current
        previous = baselines.get(name)
        previous_rows = None if previous is None else previous.row_count
        status = volume_status(current, previous_rows, drop_ratio)
        change = None
        if previous_rows:
            change = (current - previous_rows) / previous_rows
        if status == "anomaly":
            log.warning("row count drop on %s: %s -> %s", name, previous_rows, current)
        volume.append(
            VolumeStatus(
                table=name,
                rows=current,
                previous_rows=previous_rows,
                change_ratio=change,
                status=status,
            )
        )

    freshness: list[FreshnessStatus] = []
    for source in TRACKED_SOURCES:
        state = session.scalar(select(SyncState).where(SyncState.source == source))
        last_sync = None if state is None else state.last_sync_at
        status = freshness_status(last_sync, moment, max_age)
        age = None
        if last_sync is not None:
            age = (_as_utc(moment) - _as_utc(last_sync)).total_seconds() / 3600
        if status != "ok":
            log.warning("freshness %s for %s", status, source)
        freshness.append(
            FreshnessStatus(
                source=source,
                last_sync_at=last_sync,
                age_hours=age,
                max_age_hours=max_age_hours,
                status=status,
            )
        )

    if update_baseline:
        for name, current in counts.items():
            row = baselines.get(name)
            if row is None:
                session.add(QualityBaseline(table_name=name, row_count=current, captured_at=moment))
            else:
                row.row_count = current
                row.captured_at = moment
        session.commit()

    return QualityRun(
        generated_at=moment,
        tables=tables,
        freshness=freshness,
        volume=volume,
        max_age_hours=max_age_hours,
        drop_ratio=drop_ratio,
    )


def _pt(status: str) -> str:
    return _STATUS_PT.get(status, status)


def _format_change(ratio: float | None) -> str:
    if ratio is None:
        return "n/d"
    return f"{ratio:+.1%}"


def _format_hours(value: float | None) -> str:
    if value is None:
        return "n/d"
    return f"{value:.2f}"


def _format_nulls(nulls: dict[str, int]) -> str:
    if not nulls:
        return "0"
    return ", ".join(f"{key}={value}" for key, value in nulls.items())


def render_markdown(run: QualityRun) -> str:
    resultado = "aprovado" if run.passed else "reprovado"
    queda = f"{run.drop_ratio:.0%}"
    lines = [
        "# Relatório de qualidade DataForge",
        "",
        f"Gerado em: {_iso(run.generated_at)}",
        "",
        f"Resultado da execução: {resultado}",
        "",
        f"Limite de frescor: {run.max_age_hours:g} h. Fonte ausente ou mais antiga que o limite reprova a execução.",
        (
            f"Queda de volume: {queda} ou mais em relação à contagem anterior marca anomalia. "
            "A primeira medição grava a linha de base e aparece como sem linha de base."
        ),
        "",
        "## Tabelas",
        "",
        "| Tabela | Linhas | Nulos | Duplicatas | Valores impossíveis | Situação |",
        "| --- | ---: | --- | ---: | ---: | --- |",
    ]
    for item in run.tables:
        situacao = "ok" if item.passed else "reprovado"
        lines.append(
            "| "
            + " | ".join(
                [
                    item.table,
                    str(item.rows),
                    _format_nulls(item.nulls),
                    str(item.duplicates),
                    str(item.impossible_values),
                    situacao,
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Frescor das fontes",
            "",
            "| Fonte | Última sincronização | Idade (h) | Limite (h) | Situação |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    for item in run.freshness:
        lines.append(
            "| "
            + " | ".join(
                [
                    item.source,
                    _iso(item.last_sync_at) or "n/d",
                    _format_hours(item.age_hours),
                    f"{item.max_age_hours:g}",
                    _pt(item.status),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Volume",
            "",
            "| Tabela | Linhas agora | Linhas antes | Variação | Situação |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )
    for item in run.volume:
        lines.append(
            "| "
            + " | ".join(
                [
                    item.table,
                    str(item.rows),
                    "n/d" if item.previous_rows is None else str(item.previous_rows),
                    _format_change(item.change_ratio),
                    _pt(item.status),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _status_class(status: str) -> str:
    if status == "ok":
        return "ok"
    if status == "no_baseline":
        return "neutral"
    return "bad"


def _cell(value: object, css: str | None = None) -> str:
    class_attr = f' class="{css}"' if css else ""
    return f"<td{class_attr}>{html.escape(str(value), quote=True)}</td>"


def render_html(run: QualityRun) -> str:
    resultado = "aprovado" if run.passed else "reprovado"
    queda = f"{run.drop_ratio:.0%}"
    table_rows = []
    for item in run.tables:
        situacao = "ok" if item.passed else "failed"
        table_rows.append(
            "<tr>"
            + _cell(item.table)
            + _cell(item.rows)
            + _cell(_format_nulls(item.nulls))
            + _cell(item.duplicates)
            + _cell(item.impossible_values)
            + _cell(_pt(situacao), _status_class(situacao))
            + "</tr>"
        )
    freshness_rows = []
    for item in run.freshness:
        freshness_rows.append(
            "<tr>"
            + _cell(item.source)
            + _cell(_iso(item.last_sync_at) or "n/d")
            + _cell(_format_hours(item.age_hours))
            + _cell(f"{item.max_age_hours:g}")
            + _cell(_pt(item.status), _status_class(item.status))
            + "</tr>"
        )
    volume_rows = []
    for item in run.volume:
        volume_rows.append(
            "<tr>"
            + _cell(item.table)
            + _cell(item.rows)
            + _cell("n/d" if item.previous_rows is None else item.previous_rows)
            + _cell(_format_change(item.change_ratio))
            + _cell(_pt(item.status), _status_class(item.status))
            + "</tr>"
        )
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Relatório de qualidade DataForge</title>
<style>
body {{ font-family: sans-serif; margin: 2rem; color: #1a1a1a; line-height: 1.4; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }}
th {{ background: #f4f4f4; }}
.ok {{ color: #0b6b2a; }}
.bad {{ color: #9b1c1c; }}
.neutral {{ color: #555; }}
</style>
</head>
<body>
<h1>Relatório de qualidade DataForge</h1>
<p>Gerado em: {html.escape(_iso(run.generated_at) or "", quote=True)}</p>
<p>Resultado da execução: <strong class="{_status_class("ok" if run.passed else "failed")}">{resultado}</strong></p>
<p>Limite de frescor: {run.max_age_hours:g} h. Fonte ausente ou mais antiga que o limite reprova a execução.</p>
<p>Queda de volume: {queda} ou mais em relação à contagem anterior marca anomalia. A primeira medição grava a linha de base e aparece como sem linha de base.</p>
<h2>Tabelas</h2>
<table>
<thead><tr><th>Tabela</th><th>Linhas</th><th>Nulos</th><th>Duplicatas</th><th>Valores impossíveis</th><th>Situação</th></tr></thead>
<tbody>
{"".join(table_rows)}
</tbody>
</table>
<h2>Frescor das fontes</h2>
<table>
<thead><tr><th>Fonte</th><th>Última sincronização</th><th>Idade (h)</th><th>Limite (h)</th><th>Situação</th></tr></thead>
<tbody>
{"".join(freshness_rows)}
</tbody>
</table>
<h2>Volume</h2>
<table>
<thead><tr><th>Tabela</th><th>Linhas agora</th><th>Linhas antes</th><th>Variação</th><th>Situação</th></tr></thead>
<tbody>
{"".join(volume_rows)}
</tbody>
</table>
</body>
</html>
"""


def write_quality_reports(run: QualityRun, directory: str | Path) -> tuple[Path, Path]:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    stamp = _as_utc(run.generated_at).strftime("%Y%m%dT%H%M%SZ")
    markdown_path = target / f"quality-{stamp}.md"
    html_path = target / f"quality-{stamp}.html"
    markdown_path.write_text(render_markdown(run), encoding="utf-8")
    html_path.write_text(render_html(run), encoding="utf-8")
    return markdown_path, html_path
