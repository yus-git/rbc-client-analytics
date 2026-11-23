# Databricks notebook source
# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "ca_dq")
dbutils.widgets.text("source_file", "")
dbutils.widgets.text("external_table_location", "")

# COMMAND ----------
import re

catalog = dbutils.widgets.get("catalog").strip()
schema = dbutils.widgets.get("schema").strip()
source_file = dbutils.widgets.get("source_file").strip()
external_location = dbutils.widgets.get("external_table_location").strip()
if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item) for item in (catalog, schema)):
    raise ValueError("Supply simple, existing Unity Catalog catalog/schema identifiers.")
if not source_file.startswith("/Volumes/") or not source_file.endswith(".parquet"):
    raise ValueError("Upload fact_transaction.parquet to a UC volume and supply its full /Volumes/... path.")
if external_location and (
    not external_location.startswith("abfss://")
    or any(character in external_location for character in ("'", "\n", "\r"))
):
    raise ValueError("An optional external table location must be an approved, unused ABFSS path.")

target = f"`{catalog}`.`{schema}`.`fact_transaction`"
spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}`")
if spark.catalog.tableExists(target):
    raise RuntimeError(f"Refusing to replace existing table {target}. Select a new isolated schema.")

expected = {
    "TransactionKey": "bigint", "BookingDateKey": "int", "SettlementDateKey": "int",
    "ClientKey": "int", "AccountKey": "int", "AdvisorKey": "int", "ProductKey": "int",
    "ChannelKey": "int", "SignedAmountCAD": "decimal(18,2)", "FeeCAD": "decimal(18,2)",
    "TransactionType": "string", "IsSynthetic": "boolean",
}
data = spark.read.parquet(source_file)
if {column.name: column.dataType.simpleString() for column in data.schema} != expected:
    raise ValueError("Parquet types or columns differ from the validated export.")
if data.count() != 1000000:
    raise ValueError("Expected the complete 1,000,000-row transaction export.")
data.createOrReplaceTempView("incoming_client_transactions")
invalid = spark.sql("""
    SELECT count(*) - count(DISTINCT TransactionKey)
         + sum(CASE WHEN TransactionKey IS NULL OR IsSynthetic IS NULL OR NOT IsSynthetic
                    THEN 1 ELSE 0 END) violations
    FROM incoming_client_transactions
""").first()[0]
if invalid:
    raise ValueError("Duplicate transaction keys or missing synthetic-data markers detected.")

writer = data.write.format("delta").mode("error")
if external_location:
    writer = writer.option("path", external_location)
writer.saveAsTable(target)
actual = spark.table(target).count()
if actual != 1000000:
    raise RuntimeError(f"Persisted row count mismatch: {actual}")
display(spark.sql(f"SELECT count(*) TransactionCount, sum(SignedAmountCAD) NetContributionsCAD FROM {target}"))
