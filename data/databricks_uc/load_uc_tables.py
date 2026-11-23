# Databricks notebook source
# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "ca_uc")
dbutils.widgets.text("source_folder", "")
dbutils.widgets.text("external_base_location", "")

# COMMAND ----------
import json
import re
from pathlib import Path

catalog = dbutils.widgets.get("catalog").strip()
schema = dbutils.widgets.get("schema").strip()
source_folder = dbutils.widgets.get("source_folder").strip()
external_base = dbutils.widgets.get("external_base_location").strip()
if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) for value in (catalog, schema)):
    raise ValueError("Supply simple Unity Catalog identifiers for an existing catalog and a fresh schema.")
if not source_folder.startswith("/Volumes/"):
    raise ValueError("Upload the complete databricks_uc folder into a UC volume and supply its /Volumes/... path.")
if external_base and (
    not external_base.startswith("abfss://") or any(character in external_base for character in ("'", "\n", "\r"))
):
    raise ValueError("Optional external_base_location must be an approved, unused ADLS Gen2 ABFSS directory.")

definitions = json.loads((Path(source_folder) / "table_contract.json").read_text(encoding="utf-8"))
if set(definitions) != {"dim_account", "dim_product", "fact_interaction"}:
    raise ValueError("Only the three UC-mirroring tables belong in this schema.")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}`")
incoming = {}
for name, definition in definitions.items():
    target = f"`{catalog}`.`{schema}`.`{name}`"
    if spark.catalog.tableExists(target):
        raise RuntimeError(f"Refusing to replace existing table {target}; do not rerun a partly loaded schema.")
    data = spark.read.parquet(f"{source_folder.rstrip('/')}/{name}.parquet")
    expected = {column["name"]: column["type"] for column in definition["columns"]}
    if {column.name: column.dataType.simpleString() for column in data.schema} != expected:
        raise ValueError(f"Unexpected source schema: {name}")
    if data.count() != definition["expected_rows"]:
        raise ValueError(f"Unexpected row count: {name}")
    keys = definition["primary_key"]
    invalid_keys = " OR ".join(f"`{key}` IS NULL" for key in keys)
    if data.filter(f"({invalid_keys}) OR IsSynthetic IS NULL OR NOT IsSynthetic").limit(1).count():
        raise ValueError(f"Missing key or synthetic marker: {name}")
    if data.select(*keys).distinct().count() != definition["expected_rows"]:
        raise ValueError(f"Duplicate primary key: {name}")
    incoming[name] = data

for name, data in incoming.items():
    target = f"`{catalog}`.`{schema}`.`{name}`"
    writer = data.write.format("delta").mode("error")
    if external_base:
        writer = writer.option("path", f"{external_base.rstrip('/')}/{name}")
    writer.saveAsTable(target)
    persisted = spark.table(target)
    if persisted.count() != data.count():
        raise RuntimeError(f"Persisted count mismatch: {target}")
    if data.exceptAll(persisted).limit(1).count() or persisted.exceptAll(data).limit(1).count():
        raise RuntimeError(f"Persisted values changed: {target}")
    print(f"Verified {target}: {persisted.count():,} rows")

print("Only UC-mirroring tables loaded. This loader does not load fact_transaction or create a Fabric mirror.")
