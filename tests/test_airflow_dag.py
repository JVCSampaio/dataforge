"""Importação da DAG do Airflow.

O teste do DagBag só roda quando o pacote apache-airflow está instalado.
Sem ele, o pytest ignora o caso, e o CI segue com requirements.txt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PASTA_DAGS = RAIZ / "orchestration" / "airflow" / "dags"


def test_arquivo_da_dag_tem_sintaxe_valida():
    origem = PASTA_DAGS / "dataforge_etl.py"
    compile(origem.read_text(encoding="utf-8"), str(origem), "exec")


def test_dagbag_importa_sem_erro(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRFLOW_HOME", str(tmp_path))
    monkeypatch.setenv("AIRFLOW__CORE__LOAD_EXAMPLES", "False")
    monkeypatch.setenv("AIRFLOW__CORE__DAGS_FOLDER", str(PASTA_DAGS))
    monkeypatch.setenv("AIRFLOW__CORE__EXECUTOR", "SequentialExecutor")
    monkeypatch.setenv("AIRFLOW__CORE__UNIT_TEST_MODE", "True")
    monkeypatch.setenv("AIRFLOW__CORE__LOAD_DEFAULT_CONNECTIONS", "False")
    monkeypatch.setenv(
        "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN",
        f"sqlite:///{tmp_path / 'airflow.db'}",
    )
    pytest.importorskip(
        "airflow",
        reason="apache-airflow não está instalado neste ambiente",
    )
    from airflow.models import DagBag

    bag = DagBag(dag_folder=str(PASTA_DAGS), safe_mode=False)
    assert bag.import_errors == {}
    assert "dataforge_etl" in bag.dags

    dag = bag.dags["dataforge_etl"]
    assert dag.default_args["retries"] == 2
    qualidade = dag.get_task("verificar_qualidade")
    assert qualidade.retries == 2
    assert set(qualidade.upstream_task_ids) == {"ingerir_github", "ingerir_csv"}
    assert dag.schedule == "0 6 * * *"
