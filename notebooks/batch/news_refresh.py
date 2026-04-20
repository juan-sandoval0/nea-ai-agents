# Databricks notebook source
# MAGIC %md
# MAGIC # News Refresh (stub)
# MAGIC
# MAGIC Replaces `services/api.py::_run_news_refresh_job`, which today runs as a
# MAGIC `threading.Thread` on Railway and will not survive the Railway
# MAGIC decommission in Phase 2.7.
# MAGIC
# MAGIC Implementation lands in **Task 2.6**. This stub exists so the Asset
# MAGIC Bundle declared in `databricks.yml` validates and deploys.
# MAGIC
# MAGIC When Task 2.6 implements it, the notebook must:
# MAGIC 1. Read `days` and `refresh_competitors` from `dbutils.widgets`
# MAGIC 2. Call `agents.news_aggregator.agent.cmd_check(...)`
# MAGIC 3. Call `agents.news_aggregator.investor_digest.generate_investor_digest(days=days)`
# MAGIC 4. Dual-write results: Delta table (history) + Supabase (app-facing)
# MAGIC 5. Upsert a row in `job_runs` so the frontend can poll status

# COMMAND ----------

dbutils.widgets.text("days", "7")
dbutils.widgets.text("refresh_competitors", "true")

days = int(dbutils.widgets.get("days"))
refresh_competitors = dbutils.widgets.get("refresh_competitors").lower() == "true"

print(f"[news_refresh stub] days={days} refresh_competitors={refresh_competitors}")
print("Implementation pending Task 2.6 — see notebook header for scope.")
