# %% Parameters
layer = "silver"
config_json = "{}"

# %% Validate context and start the run
import json
from datetime import datetime, timezone
from decimal import Decimal
from functools import reduce
from uuid import uuid4

import notebookutils
from pyspark.sql import functions as F
from pyspark.storagelevel import StorageLevel

config = json.loads(config_json)
if layer not in {"silver", "gold"}:
    raise ValueError("Layer must be silver or gold.")
context = notebookutils.runtime.context
if str(context["currentWorkspaceId"]) != config["workspace_id"]:
    raise ValueError("Notebook is running in a different workspace from its deployment.")
if str(context["defaultLakehouseId"]) != config["target_lakehouse_id"]:
    raise ValueError("Wrong default lakehouse; no tables will be written.")
if context["defaultLakehouseName"] != f"lh_ca_{layer}":
    raise ValueError("The target is not the configured Silver/Gold lakehouse.")
if config["target_lakehouse_id"] in {
    item["lakehouse_id"] for item in config["sources"].values()
}:
    raise ValueError("Refusing to overwrite a Bronze source lakehouse.")

spark.conf.set("spark.sql.ansi.enabled", "true")
spark.conf.set("spark.sql.session.timeZone", "UTC")
spark.conf.set("spark.sql.shuffle.partitions", "16")
spark.conf.set("spark.databricks.delta.optimizeWrite.enabled", "true")
spark.conf.set("spark.sql.parquet.vorder.default", str(layer == "gold").lower())
if layer == "gold":
    spark.conf.set("spark.databricks.delta.optimizeWrite.binSize", "1g")

endpoint = notebookutils.conf.get("trident.onelake.endpoint").removeprefix("https://").rstrip("/")
run_id = str(uuid4())
started_at = datetime.now(timezone.utc).isoformat()
contracts = config["tables"]
baseline = config["snapshot_baseline"]
report = {
    "run_id": run_id,
    "layer": layer,
    "status": "RUNNING",
    "started_at_utc": started_at,
    "workspace_id": config["workspace_id"],
    "lakehouse_id": config["target_lakehouse_id"],
    "checks": [],
    "tables": {},
    "external_relationships_deferred": [
        f"{name}.{column} -> {target}"
        for name, contract in contracts.items()
        for column, target in contract["references"].items()
        if target.split(".")[0] not in contracts
    ],
}
report_folder = f"Files/medallion_runs/{layer}"
notebookutils.fs.mkdirs(report_folder)


def publish_report():
    payload = json.dumps(report, indent=2)
    notebookutils.fs.put(f"{report_folder}/{run_id}.json", payload, True)
    notebookutils.fs.put(f"{report_folder}/latest.json", payload, True)


def require(condition, message):
    if not condition:
        report["status"] = "FAILED"
        report["error"] = message
        publish_report()
        raise ValueError(message)


def check(name, violations):
    violations = int(violations)
    report["checks"].append({"name": name, "violations": violations})
    print(f"{'PASS' if violations == 0 else 'FAIL'} {name}: {violations}", flush=True)
    require(violations == 0, f"Data quality check failed: {name} ({violations} violations)")


def lakehouse_root(lakehouse_id):
    return f"abfss://{config['workspace_id']}@{endpoint}/{lakehouse_id}"


publish_report()
upstream_run_id = None
if layer == "gold":
    silver_report = json.loads(notebookutils.fs.head(
        f"{lakehouse_root(config['silver_lakehouse_id'])}/Files/medallion_runs/silver/latest.json",
        1024 * 1024,
    ))
    require(silver_report["status"] == "PASSED", "Run Bronze-to-Silver successfully first.")
    require(silver_report["lakehouse_id"] == config["silver_lakehouse_id"], "Wrong Silver report.")
    require(set(silver_report["tables"]) == set(contracts), "Silver report has a different table set.")
    upstream_run_id = silver_report["run_id"]
    report["upstream_silver_run_id"] = upstream_run_id

# %% Read logical Delta columns and conform the business schema
frames = {}
source_paths = {}
for name, contract in contracts.items():
    location = config["sources"][name]
    source_path = (
        f"{lakehouse_root(location['lakehouse_id'])}/Tables/{location['schema']}/{name}"
        if layer == "silver"
        else f"{lakehouse_root(config['silver_lakehouse_id'])}/Tables/dbo/{name}"
    )
    source_paths[name] = source_path
    raw = spark.read.format("delta").load(source_path)
    expected_columns = [column["name"] for column in contract["columns"]]
    require(not (set(expected_columns) - set(raw.columns)), f"{name}: required columns are missing.")
    if layer == "gold":
        require("_RunId" in raw.columns, f"{name}: Silver lineage column is missing.")
        require(
            not raw.filter(F.col("_RunId").isNull() | (F.col("_RunId") != upstream_run_id)).limit(1).count(),
            f"{name}: Silver contains rows from a different or incomplete run.",
        )
    expressions = []
    for column in contract["columns"]:
        expression = F.col(column["name"]).cast(column["type"])
        if column["type"] == "string":
            expression = F.trim(expression)
        expressions.append(expression.alias(column["name"], metadata={}))
    frame = raw.select(*expressions).persist(StorageLevel.MEMORY_AND_DISK)
    frames[name] = frame
    frame.createOrReplaceTempView(name)
    invalid = reduce(lambda left, right: left | right, [F.col(c).isNull() for c in expected_columns])
    stats = frame.agg(
        F.count("*").alias("rows"),
        F.countDistinct(F.struct(*contract["primary_key"])).alias("unique_keys"),
        F.sum(F.when(invalid, 1).otherwise(0)).alias("null_rows"),
        F.sum(F.when(~F.col("IsSynthetic"), 1).otherwise(0)).alias("non_synthetic_rows"),
    ).first()
    check(f"{name}: expected row count", abs(stats["rows"] - contract["expected_rows"]))
    check(f"{name}: unique primary key", stats["rows"] - stats["unique_keys"])
    check(f"{name}: required values", stats["null_rows"])
    check(f"{name}: synthetic marker", stats["non_synthetic_rows"])

# %% Validate relationships, ownership and financial rules before any table writes
for name, contract in contracts.items():
    for column, target in contract["references"].items():
        dimension, target_column = target.split(".")
        if dimension in frames:
            violations = frames[name].join(
                frames[dimension],
                frames[name][column] == frames[dimension][target_column],
                "left_anti",
            ).count()
            check(f"{name}.{column}: references {target}", violations)

business_checks = {
    "Ownership weights sum to one": """
        SELECT count(*) FROM (
            SELECT AccountKey FROM bridge_account_owner GROUP BY AccountKey
            HAVING sum(OwnershipWeight) <> 1 OR min(OwnershipWeight) <= 0
        )
    """,
    "Every account has owners": """
        SELECT count(*) FROM dim_account a LEFT ANTI JOIN bridge_account_owner b
        ON a.AccountKey=b.AccountKey
    """,
    "Snapshot accounting equation": """
        SELECT count(*) FROM fact_account_monthly
        WHERE OpeningBalanceCAD + NetFlowCAD + MarketMovementCAD <> ClosingBalanceCAD
    """,
    "Snapshot balance continuity": """
        SELECT count(*) FROM (
            SELECT OpeningBalanceCAD,
                   lag(ClosingBalanceCAD) OVER (PARTITION BY AccountKey ORDER BY DateKey) PreviousClose
            FROM fact_account_monthly
        ) WHERE PreviousClose IS NOT NULL AND PreviousClose <> OpeningBalanceCAD
    """,
    "Snapshots are month-end": """
        SELECT count(*) FROM fact_account_monthly f JOIN dim_date d ON f.DateKey=d.DateKey
        WHERE f.DateKey <> d.MonthEndDateKey
    """,
    "Each account has the complete monthly history": f"""
        SELECT count(*) FROM (
            SELECT AccountKey FROM fact_account_monthly GROUP BY AccountKey
            HAVING count(*) <> {baseline['months']}
        )
    """,
    "Calendar dates are continuous and keys match": """
        SELECT abs(count(*) - datediff(max(Date), min(Date)) - 1)
             + sum(CASE WHEN DateKey <> CAST(date_format(Date, 'yyyyMMdd') AS INT) THEN 1 ELSE 0 END)
        FROM dim_date
    """,
    "Interaction duration and satisfaction": """
        SELECT count(*) FROM fact_interaction
        WHERE DurationMinutes <= 0 OR SatisfactionScore NOT BETWEEN 1 AND 5
    """,
    "Account currency is CAD": "SELECT count(*) FROM dim_account WHERE CurrencyCode <> 'CAD'",
}
for name, query in business_checks.items():
    check(name, spark.sql(query).first()[0])

snapshot = frames["fact_account_monthly"]
totals = snapshot.agg(*[F.sum(column).alias(column) for column in baseline["totals"]]).first()
for column, expected in baseline["totals"].items():
    require(totals[column] == Decimal(expected), f"Snapshot total differs from source baseline: {column}")
latest = snapshot.agg(F.max("DateKey")).first()[0]
require(latest == baseline["latest_date_key"], "Latest snapshot date differs from the reference baseline.")
latest_aum = snapshot.filter(F.col("DateKey") == latest).agg(F.sum("ClosingBalanceCAD")).first()[0]
require(latest_aum == Decimal(baseline["latest_aum_cad"]), "Latest AUM differs from the reference baseline.")
report["snapshot_totals"] = {column: str(totals[column]) for column in baseline["totals"]}
report["latest_date_key"] = latest
report["latest_aum_cad"] = str(latest_aum)
print(f"Verified latest AUM: CAD {latest_aum}", flush=True)

# %% Materialize validated snapshots and verify the persisted rows
spark.sql("CREATE SCHEMA IF NOT EXISTS dbo")
for name, frame in frames.items():
    target = f"dbo.{name}"
    output = frame
    if layer == "silver":
        output = (
            frame.withColumn("_RunId", F.lit(run_id))
            .withColumn("_IngestedAtUtc", F.lit(started_at).cast("timestamp"))
            .withColumn("_SourcePath", F.lit(source_paths[name]))
        )
    if spark.catalog.tableExists(target):
        properties = {row.key: row.value for row in spark.sql(f"SHOW TBLPROPERTIES {target}").collect()}
        require(
            properties.get("demo.pipeline") == "client_analytics_medallion"
            and properties.get("demo.layer") == layer,
            f"Refusing to replace untagged table {target}.",
        )
    else:
        ddl = ", ".join(f"`{field.name}` {field.dataType.simpleString()}" for field in output.schema)
        spark.sql(
            f"CREATE TABLE {target} ({ddl}) USING DELTA TBLPROPERTIES "
            f"('demo.pipeline'='client_analytics_medallion', 'demo.layer'='{layer}')"
        )
    if contracts[name]["expected_rows"] <= 24000:
        output = output.coalesce(1)
    output.write.format("delta").mode("overwrite").saveAsTable(target)
    if layer == "gold":
        spark.sql(f"OPTIMIZE {target} VORDER")
    persisted = spark.table(target)
    require(persisted.schema.simpleString() == output.schema.simpleString(), f"{target}: schema changed on write.")
    business_columns = [column["name"] for column in contracts[name]["columns"]]
    stored_business = persisted.select(*business_columns)
    require(
        not stored_business.exceptAll(frame).limit(1).count()
        and not frame.exceptAll(stored_business).limit(1).count(),
        f"{target}: persisted business values differ from the validated input.",
    )
    rows = persisted.count()
    check(f"{target}: persisted row count", abs(rows - contracts[name]["expected_rows"]))
    if layer == "silver":
        require(
            not persisted.filter(F.col("_RunId").isNull() | (F.col("_RunId") != run_id)).limit(1).count(),
            f"{target}: persisted lineage does not match this run.",
        )
    report["tables"][name] = {
        "rows": rows,
        "source": source_paths[name],
        "schema": persisted.schema.simpleString(),
        "persisted_values_match": True,
    }
    print(f"Published {layer}.{name}: {rows:,} rows", flush=True)

# %% Publish the verified completion marker
report["total_rows"] = sum(table["rows"] for table in report["tables"].values())
require(report["total_rows"] == sum(t["expected_rows"] for t in contracts.values()), "Unexpected total row count.")
report["status"] = "PASSED"
report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
publish_report()
display(spark.createDataFrame(
    [(name, value["rows"]) for name, value in report["tables"].items()],
    "TableName STRING, RowCount LONG",
))
for frame in frames.values():
    frame.unpersist()
print(json.dumps({
    "layer": layer, "status": report["status"], "run_id": run_id,
    "tables": len(report["tables"]), "total_rows": report["total_rows"],
    "latest_aum_cad": report["latest_aum_cad"],
    "external_relationships_deferred": report["external_relationships_deferred"],
}, indent=2))
