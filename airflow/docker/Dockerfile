FROM apache/airflow:3.1.2-python3.12

COPY airflow/project-requirements.txt /tmp/recomart-requirements.txt
RUN pip install --no-cache-dir -r /tmp/recomart-requirements.txt --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.1.2/constraints-3.12.txt

ENV PYTHONPATH=/opt/airflow/project
WORKDIR /opt/airflow/project


