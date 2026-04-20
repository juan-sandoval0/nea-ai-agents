# Databricks notebook source
# MAGIC %md
# MAGIC # Investor Digest (stub)
# MAGIC
# MAGIC Replaces the synchronous `GET /api/digest/weekly` path
# MAGIC (`agents.news_aggregator.digest.generate_weekly_digest`) plus the
# MAGIC clustering step in `generate_investor_digest`.
# MAGIC
# MAGIC Implementation lands in **Task 2.6**. This stub exists so the Asset
# MAGIC Bundle declared in `databricks.yml` validates and deploys.
# MAGIC
# MAGIC When Task 2.6 implements it, the notebook must:
# MAGIC 1. Read `days` from `dbutils.widgets`
# MAGIC 2. Call `agents.news_aggregator.digest.generate_weekly_digest(days=days)`
# MAGIC 3. Dual-write: Delta table `nea.digests` + Supabase `briefing_news` /
# MAGIC    `digest_stories` for the frontend slice
# MAGIC 4. Record run metadata in `job_runs`

# COMMAND ----------

dbutils.widgets.text("days", "7")
days = int(dbutils.widgets.get("days"))

print(f"[investor_digest stub] days={days}")
print("Implementation pending Task 2.6 — see notebook header for scope.")
