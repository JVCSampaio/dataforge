FROM apache/airflow:3.3.2-python3.11

# Pacotes que o ETL do DataForge importa dentro das tarefas.
# O arquivo de constraints vem na imagem e evita trocar as versões do Airflow.
COPY requirements.txt /opt/airflow/dataforge-requirements.txt
COPY dags /opt/airflow/dags
RUN pip install --no-cache-dir \
    --constraint "/home/airflow/constraints.txt" \
    -r /opt/airflow/dataforge-requirements.txt
