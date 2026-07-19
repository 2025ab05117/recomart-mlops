# RecoMart Local Airflow Environment

The project pins Apache Airflow 3.1.2 and installs it with the official
constraints file for the active Python minor version. Native Windows is not an
official Airflow runtime; use Docker or WSL for the full scheduler and UI.

For Docker:

```powershell
docker compose -f airflow/compose.yaml up --build
```

For Linux/WSL after creating `.airflow-venv`:

```bash
AIRFLOW_VERSION=3.1.2
PYTHON_VERSION=3.12
pip install "apache-airflow==${AIRFLOW_VERSION}" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"
./airflow/scripts/start_airflow.sh
```

The standalone credentials are written beneath `AIRFLOW_HOME`; do not commit
that directory. Open `http://localhost:8080` after the health endpoint responds.
