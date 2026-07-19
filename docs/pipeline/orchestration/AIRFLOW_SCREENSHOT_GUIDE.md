# Airflow Assignment Screenshot Guide

Capture screenshots only from a real completed Airflow run; do not fabricate or
edit task states.

1. **DAG listing:** open **DAGs** and show
   `recomart_end_to_end_pipeline` enabled with its successful latest run.
2. **Grid:** open the successful run's **Grid** view and show every required
   task in green.
3. **Graph:** open **Graph** and show generation → ingestion → validation →
   quality gate → preparation → features → feature gate → versioning → modeling
   → lineage finalization → summary.
4. **Final task log:** select `generate_pipeline_summary` → **Log**. Include the
   lines containing `status=SUCCESS`, batch ID, feature batch ID, model run ID,
   and MLflow run IDs.
5. **Duration:** capture the run/task duration panel or Gantt view available in
   the installed Airflow UI.
6. **Optional MLflow:** open the experiment run referenced by the final log and
   show its parameters, metrics, and artifacts.

Keep the browser address bar or page heading visible enough to establish which
tool and run are shown. Cross-check identifiers against
`reports/orchestration/dag_run_id=<id>/execution_evidence.txt`.
