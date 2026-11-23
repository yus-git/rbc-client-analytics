"""Build target-specific artifacts locally. This command never calls a cloud API."""

import argparse
import base64
import json
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from build_hybrid_model import GOLD, build as build_model
from build_notebook import build as build_notebook
from build_demo_reports import RDL_NAME, REPORT_NAME, build as build_reports, envelope

BRONZE = {
    "dim_date": ("lh_bronze_channel", "dbo"),
    "dim_channel": ("lh_bronze_channel", "dbo"),
    "dim_account": ("lh_bronze_uc", "dbo"),
    "dim_product": ("lh_bronze_uc", "dbo"),
    "fact_interaction": ("lh_bronze_uc", "dbo"),
    "dim_account_owner": ("lh_bronze_sql_onprem", "ca_demo"),
    "bridge_account_owner": ("lh_bronze_sql_onprem", "ca_demo"),
    "fact_account_monthly": ("lh_bronze_s3", "dbo"),
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def guid(value):
    parsed = uuid.UUID(value)
    if parsed.int == 0:
        raise ValueError("An empty GUID is not a deployed resource ID.")
    return str(parsed)


def validate(config, stage):
    guid(config["workspace_id"])
    names = {"lh_ca_gold"} if stage == "model" else set()
    if stage == "notebooks":
        names = {v[0] for v in BRONZE.values()} | {"lh_ca_silver", "lh_ca_gold"}
    for name in names:
        guid(config["lakehouses"][name])
    if stage == "notebooks":
        ids = [config["lakehouses"][name] for name in names]
        if len(set(ids)) != len(ids):
            raise ValueError("Bronze, Silver and Gold require distinct lakehouse IDs.")
    if stage == "model":
        for name in ("sql_server", "sql_database", "postgres_server", "postgres_database",
                     "databricks_host", "databricks_http_path", "databricks_catalog"):
            value = config[name]
            if not isinstance(value, str) or not value.strip() or re.search(r"[<>\r\n]", value):
                raise ValueError(f"Replace the example value for {name}.")
        if not re.fullmatch(r"[A-Za-z0-9.-]+\.azuredatabricks\.net", config["databricks_host"]):
            raise ValueError("Use the Azure Databricks hostname, without scheme or path.")
        if not re.fullmatch(r"/sql/1\.0/warehouses/[A-Za-z0-9]+", config["databricks_http_path"]):
            raise ValueError("Use the SQL warehouse HTTP path, not a cluster or workspace URL.")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", config["databricks_catalog"]):
            raise ValueError("Use a simple catalog identifier.")
    if stage in {"paginated", "interactive"}:
        guid(config["semantic_model_id"])
    if stage == "interactive":
        guid(config["paginated_report_id"])


def pristine_gold(config, contract):
    source = "DirectLake - Gold"
    url = ("https://onelake.dfs.fabric.microsoft.com/" + config["workspace_id"]
           + "/" + config["lakehouses"]["lh_ca_gold"])
    database = {
        "compatibilityLevel": 1702,
        "model": {
            "culture": "en-US",
            "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "dataAccessOptions": {"returnErrorValuesAsNull": False},
            "expressions": [{
                "name": source, "kind": "m", "lineageTag": str(uuid.uuid4()),
                "expression": [f'AzureStorage.DataLake("{url}", [HierarchicalNavigation=true])'],
            }],
            "tables": [{
                "name": name, "lineageTag": str(uuid.uuid4()),
                "columns": [{"name": c["name"], "sourceColumn": c["name"],
                             "lineageTag": str(uuid.uuid4())} for c in contract["tables"][name]["columns"]],
                "partitions": [{"name": name, "mode": "directLake", "source": {
                    "type": "entity", "schemaName": "dbo", "entityName": name, "expressionSource": source,
                }}],
            } for name in sorted(GOLD)],
        },
    }
    return {"definition": {"parts": [
        {"path": "model.bim", "payloadType": "InlineBase64",
         "payload": base64.b64encode(json.dumps(database).encode()).decode()},
        {"path": "definition.pbism", "payloadType": "InlineBase64",
         "payload": base64.b64encode(b'{"version":"4.2"}').decode()},
    ]}}


def build_notebooks(config, contract, output):
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    tables = {name: contract["tables"][name] for name in BRONZE}
    snapshot = pq.read_table(ROOT / "data" / "s3" / "fact_account_monthly.parquet")
    amounts = [c["name"] for c in tables["fact_account_monthly"]["columns"]
               if c["type"].startswith("decimal")]
    latest = pc.max(snapshot["DateKey"]).as_py()
    baseline = {
        "months": len(pc.unique(snapshot["DateKey"])),
        "totals": {c: str(pc.sum(snapshot[c]).as_py()) for c in amounts},
        "latest_date_key": latest,
        "latest_aum_cad": str(pc.sum(snapshot.filter(
            pc.equal(snapshot["DateKey"], latest))["ClosingBalanceCAD"]).as_py()),
    }
    sources = {name: {"lakehouse_id": config["lakehouses"][lh], "schema": schema}
               for name, (lh, schema) in BRONZE.items()}
    for layer in ("silver", "gold"):
        lakehouse = "lh_ca_" + layer
        settings = {
            "workspace_id": config["workspace_id"], "target_lakehouse_id": config["lakehouses"][lakehouse],
            "silver_lakehouse_id": config["lakehouses"]["lh_ca_silver"],
            "sources": sources, "tables": tables, "snapshot_baseline": baseline,
        }
        name = "nb_ca_" + ("bronze_to_silver" if layer == "silver" else "silver_to_gold")
        build_notebook(
            ROOT / "notebooks" / "transform_demo_medallion.py",
            config["workspace_id"], config["lakehouses"][lakehouse], lakehouse,
            output_path=output / f"{name}.ipynb", title=name,
            introduction="Run only in the configured target lakehouse. A PASSED marker is required "
                         "before downstream consumption. Table writes are not cross-table atomic.",
            parameter_source=f"layer = {layer!r}\nconfig_json = {json.dumps(settings)!r}",
        )


def run(stage, config, output):
    validate(config, stage)
    output.mkdir(parents=True, exist_ok=True)
    contract = read(ROOT / "data" / "data_contract.json")
    if stage == "notebooks":
        build_notebooks(config, contract, output)
    elif stage == "model":
        dbx = {"catalog": {"name": config["databricks_catalog"]}, "sqlWarehouse": {"odbc_params": {
            "hostname": config["databricks_host"], "path": config["databricks_http_path"],
        }}}
        build_model(pristine_gold(config, contract), contract, dbx, output / "model", settings=config)
        definition = read(output / "model" / "update_definition.json")["definition"]
        write(output / "model" / "create.json", {
            "displayName": "sm_client_analytics", "definition": definition,
        })
    else:
        before = read(output / "model" / "update_definition.json")
        link = ("https://app.powerbi.com/groups/" + config["workspace_id"] + "/rdlreports/"
                + (config["paginated_report_id"] or "not-created"))
        parts, rdl = build_reports(before, config["semantic_model_id"], link)
        if stage == "paginated":
            (output / f"{RDL_NAME}.rdl").write_bytes(rdl)
            request = envelope({f"{RDL_NAME}.rdl": rdl}, RDL_NAME, "Synthetic advisor performance pack", "")
            request["definition"].pop("format")
            write(output / "paginated.create.json", request)
        else:
            encoded = {}
            for path, content in parts.items():
                if path == "semanticModelDiagramLayout.json":
                    continue
                encoded[path] = json.dumps(content, indent=2).encode()
                target = output / "ClientAnalytics.Report" / Path(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(encoded[path])
            write(output / "interactive.create.json", envelope(
                encoded, REPORT_NAME, "Synthetic multi-source client analytics", "PBIR"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["notebooks", "model", "paginated", "interactive"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / ".generated")
    args = parser.parse_args()
    run(args.stage, read(args.config), args.output)
    print(f"Built {args.stage} locally in {args.output}. No cloud changes made.")
