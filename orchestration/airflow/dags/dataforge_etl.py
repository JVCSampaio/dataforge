"""DAG que orquestra o ETL do DataForge.

Cria as tabelas, ingere GitHub e CSV em paralelo e, em seguida, roda a
qualidade. A tarefa falha quando o relatório da execução vem reprovado.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

ARGUMENTOS_PADRAO = {
    "owner": "dataforge",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


def inicializar_banco() -> str:
    """Cria as tabelas. A operação é idempotente."""
    from dataforge.config import load_settings
    from dataforge.db.migrate import init_db

    settings = load_settings()
    init_db(settings.database_url)
    return "tabelas criadas"


def ingerir(fonte: str) -> dict:
    """Roda a ingestão de uma fonte (`github` ou `csv`)."""
    from dataforge.config import load_settings
    from dataforge.db.session import make_session
    from dataforge.ingest import run_ingest

    settings = load_settings()
    session = make_session(settings.database_url)
    try:
        return run_ingest(session, settings, fonte)
    finally:
        session.close()


def verificar_qualidade() -> dict:
    """Roda o relatório completo e falha se a execução vier reprovada.

    Além dos valores impossíveis, a execução reprova quando uma fonte está
    ausente ou atrasada, ou quando alguma tabela perde volume além do limite.
    Se `QUALITY_REPORT_DIR` estiver definido, grava Markdown e HTML nesse diretório.
    """
    from pathlib import Path

    from dataforge.config import load_settings
    from dataforge.db.session import make_session
    from dataforge.quality import collect_quality_run, write_quality_reports

    settings = load_settings()
    session = make_session(settings.database_url)
    try:
        run = collect_quality_run(
            session,
            max_age_hours=settings.quality_max_age_hours,
            drop_ratio=settings.quality_row_drop_ratio,
            update_baseline=True,
        )
        if settings.quality_report_dir:
            write_quality_reports(run, Path(settings.quality_report_dir))
    finally:
        session.close()

    if not run.passed:
        detalhes = "; ".join(run.problems())
        raise RuntimeError(f"checagens de qualidade reprovadas: {detalhes}")
    return run.to_dict()


with DAG(
    dag_id="dataforge_etl",
    description="Orquestra a ingestão e a qualidade de dados do DataForge",
    default_args=ARGUMENTOS_PADRAO,
    schedule="0 6 * * *",
    start_date=datetime(2024, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    tags=["dataforge", "etl"],
) as dag:
    tarefa_banco = PythonOperator(
        task_id="inicializar_banco",
        python_callable=inicializar_banco,
    )
    tarefa_github = PythonOperator(
        task_id="ingerir_github",
        python_callable=ingerir,
        op_kwargs={"fonte": "github"},
    )
    tarefa_csv = PythonOperator(
        task_id="ingerir_csv",
        python_callable=ingerir,
        op_kwargs={"fonte": "csv"},
    )
    tarefa_qualidade = PythonOperator(
        task_id="verificar_qualidade",
        python_callable=verificar_qualidade,
        # Um relatório reprovado continua reprovado na nova tentativa: falha na hora.
        retries=0,
    )

    tarefa_banco >> [tarefa_github, tarefa_csv] >> tarefa_qualidade
