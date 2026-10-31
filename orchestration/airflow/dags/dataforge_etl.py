"""DAG que orquestra o ETL do DataForge.

Cria as tabelas, ingere GitHub e CSV em paralelo e, em seguida, roda a
qualidade. A tarefa de qualidade falha quando algum relatório vem reprovado.
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


def verificar_qualidade() -> list[dict]:
    """Roda os relatórios e falha se algum vier com passed falso."""
    from dataforge.config import load_settings
    from dataforge.db.session import make_session
    from dataforge.quality import run_all

    settings = load_settings()
    session = make_session(settings.database_url)
    try:
        relatorios = [item.to_dict() for item in run_all(session)]
    finally:
        session.close()

    reprovados = [item["table"] for item in relatorios if not item["passed"]]
    if reprovados:
        nomes = ", ".join(reprovados)
        raise RuntimeError(f"checagens de qualidade reprovadas: {nomes}")
    return relatorios


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
        retries=2,
        retry_delay=timedelta(minutes=5),
    )

    tarefa_banco >> [tarefa_github, tarefa_csv] >> tarefa_qualidade
