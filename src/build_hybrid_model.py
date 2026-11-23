"""Extend the backed-up eight-table Gold model without replacing its item identity."""

import argparse
import base64
import copy
import json
import re
import uuid
from pathlib import Path

from build_semantic_model import CURRENCY, MEASURES, TABLE_NAMES, friendly, model_type, validate_contract


DIRECT_QUERY = {"dim_client", "dim_advisor", "fact_transaction"}
IMPORT = {"dim_campaign", "fact_target", "fact_opportunity"}
GOLD = set(TABLE_NAMES) - DIRECT_QUERY - IMPORT
EXTRA_MEASURES = {
    "Account Monthly": [
        ("Latest Snapshot Date", "VAR _key = MAX('Account Monthly'[Date Key]) RETURN IF(NOT ISBLANK(_key), DATE(INT(_key / 10000), INT(MOD(_key, 10000) / 100), MOD(_key, 100)))",
         "yyyy-MM-dd", "Latest available month-end in the current filter context, not the last date in the calendar."),
        ("Revenue YTD", "TOTALYTD([Revenue], 'Calendar'[Date])", CURRENCY,
         "Calendar-year cumulative revenue. Use a year/month filter for a meaningful YTD comparison."),
        ("Revenue Prior Year", "CALCULATE([Revenue], DATEADD('Calendar'[Date], -1, YEAR))", CURRENCY,
         "Revenue for the selected dates shifted back one calendar year."),
        ("Revenue YoY %", "VAR _prior = [Revenue Prior Year] RETURN DIVIDE([Revenue] - _prior, _prior)", "0.0%",
         "Revenue growth against the same selected period last year; blank when no prior revenue exists."),
        ("AUM Prior Year", "CALCULATE([Assets Under Management], DATEADD('Calendar'[Date], -1, YEAR))", CURRENCY,
         "Last visible month-end assets in the corresponding prior-year period."),
        ("Monthly Snapshot Rows", "COUNTROWS('Account Monthly')", "#,##0",
         "Count of account/month-end observations; not a count of distinct accounts."),
    ],
    "Accounts": [
        ("Accounts in Master", "COUNTROWS('Accounts')", "#,##0",
         "Accounts in the master dimension; fact/date filters do not flow back into this count."),
    ],
    "Clients": [
        ("Client Version Count", "COUNTROWS('Clients')", "#,##0",
         "SCD type 2 records. Historical versions explain why this exceeds the number of business clients."),
    ],
    "Account Ownership": [
        ("Owner Allocated Assets",
         "VAR _lastSnapshot = MAX('Account Monthly'[Date Key]) "
         "VAR _allocation = CALCULATETABLE(SUMMARIZECOLUMNS('Accounts'[Account Key], "
         "\"_balance\", SUM('Account Monthly'[Closing Balance CAD]), "
         "\"_weight\", SUM('Account Ownership'[Ownership Weight])), "
         "KEEPFILTERS('Calendar'[Date Key] = _lastSnapshot)) "
         "RETURN SUMX(_allocation, [_balance] * [_weight])",
         CURRENCY, "Latest visible assets allocated using current ownership weights. Additive across owners; not historical ownership attribution."),
    ],
    "Targets": [
        ("Revenue Variance", "VAR _target = [Revenue Target] RETURN IF(NOT ISBLANK(_target), [Revenue] - _target)",
         CURRENCY, "Actual revenue less the selected scenario target. Blank where target grain/scenario is not supported."),
        ("Selected Target Scenario", "SELECTEDVALUE('Targets'[Scenario], \"Select one scenario\")", "@",
         "Use as a report subtitle to make the required Plan/Stretch scenario selection explicit."),
    ],
    "Opportunities": [
        ("Estimated Opportunity Value", "SUM('Opportunities'[Estimated Value CAD])", CURRENCY,
         "Unweighted estimated value across selected opportunity stages, by creation date."),
    ],
}


def new_tag() -> str:
    return str(uuid.uuid4())


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def m_text(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def parameter(name: str, value: str, description: str) -> dict:
    return {
        "name": name, "kind": "m", "lineageTag": new_tag(), "description": description,
        "expression": m_text(value) + ' meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]',
    }


def partition(source: str, spec: dict) -> dict:
    names = "{" + ", ".join(m_text(c["name"]) for c in spec["columns"]) + "}"
    if source in {"dim_client", "dim_advisor"}:
        query = (
            "let\n    Source = Sql.Database(SqlServer, SqlDatabase),\n"
            f'    Data = Source{{[Schema="ca_demo", Item="{source}"]}}[Data],\n'
            f"    Selected = Table.SelectColumns(Data, {names})\nin\n    Selected"
        )
    elif source == "fact_transaction":
        query = (
            "let\n    Source = Databricks.Catalogs(DatabricksHost, DatabricksHttpPath, "
            '[Catalog=null, Database=null, Implementation="2.0"]),\n'
            '    Catalog = Source{[Name=DatabricksCatalog, Kind="Database"]}[Data],\n'
            '    Schema = Catalog{[Name="ca_dq", Kind="Schema"]}[Data],\n'
            '    Data = Schema{[Name="fact_transaction", Kind="Table"]}[Data],\n'
            f"    Selected = Table.SelectColumns(Data, {names})\nin\n    Selected"
        )
    elif source == "fact_opportunity":
        query = (
            "let\n    Source = PostgreSQL.Database(PostgresServer, PostgresDatabase),\n"
            '    Data = Source{[Schema="ca_demo", Item="fact_opportunity"]}[Data],\n'
            f"    Selected = Table.SelectColumns(Data, {names})\nin\n    Selected"
        )
    else:
        m_types = {"int64": "Int64.Type", "decimal": "Currency.Type", "dateTime": "type date",
                   "boolean": "type logical", "string": "type text"}
        conversions = ", ".join(
            "{" + m_text(c["name"]) + ", " + m_types[model_type(c["type"])] + "}"
            for c in spec["columns"]
        )
        query = (
            "let\n    Source = AzureStorage.DataLake(OneLakeSourceUrl, [HierarchicalNavigation=false]),\n"
            '    Files = Table.SelectRows(Source, each [Name] = "Client_Analytics_Planning.xlsx" '
            'and Text.EndsWith([Folder Path], "/Files/planning/")),\n'
            '    Binary = if Table.RowCount(Files) = 1 then Files{0}[Content] '
            'else error "Expected exactly one planning workbook in Files/planning.",\n'
            "    Workbook = Excel.Workbook(Binary, null, true),\n"
            f'    Data = Workbook{{[Item="{source}", Kind="Table"]}}[Data],\n'
            f"    Selected = Table.SelectColumns(Data, {names}),\n"
            f'    Typed = Table.TransformColumnTypes(Selected, {{{conversions}}}, "en-US")\nin\n    Typed'
        )
    return {"name": TABLE_NAMES[source], "mode": "directQuery" if source in DIRECT_QUERY else "import",
            "source": {"type": "m", "expression": query.splitlines()}}


def column_description(source: str, column: str, spec: dict) -> str:
    if column in spec["references"]:
        return "Relationship key to " + spec["references"][column] + "; filter using the related dimension."
    special = {
        "ClientKey": "Historical client-version surrogate key. Use this, not Client Id, to relate dated facts.",
        "ClientId": "Stable business client identifier shared by all historical client versions.",
        "EffectiveFrom": "Inclusive start of this synthetic client-version validity interval.",
        "EffectiveToExclusive": "Exclusive end of this client-version validity interval.",
        "IsCurrent": "Whether this is the current client version. Do not remove historical versions from the model.",
        "Scenario": "Choose one planning scenario, Plan or Stretch, before comparing actuals and targets.",
        "OwnershipWeight": "Current owner's fraction of the account; all owners' weights sum to one per account.",
        "ClosingBalanceCAD": "Account balance at month-end in CAD; additive across accounts, not across dates.",
        "SignedAmountCAD": "Booked contribution or withdrawal in CAD; reconciles to monthly net flows.",
        "IsSynthetic": "True for every row in this synthetic dataset; no real client data.",
        "Probability": "Synthetic win probability from zero to one; used to weight open opportunity value.",
        "Region": "Synthetic regional grouping for this dimension's analytical role.",
        "AdvisorRegion": "Synthetic advisor-office region; independent of a client's region.",
    }
    if column in special:
        return special[column]
    return f"{friendly(column)} for {TABLE_NAMES[source]}. {spec['grain']}."


def add_hierarchy(table: dict, name: str, columns: list[str]) -> None:
    table.setdefault("hierarchies", []).append({
        "name": name, "lineageTag": new_tag(),
        "levels": [{"name": c, "ordinal": i, "column": c, "lineageTag": new_tag()}
                   for i, c in enumerate(columns)],
    })


def build(before: dict, contract: dict, databricks: dict, output: Path, *, settings: dict) -> dict:
    validate_contract(contract)
    parts = before["definition"]["parts"]
    bim_part = next(p for p in parts if p["path"] == "model.bim")
    database = json.loads(base64.b64decode(bim_part["payload"]))
    model = database["model"]
    existing = {t["name"]: t for t in model["tables"]}
    if set(existing) != GOLD or model.get("relationships") or any(t.get("measures") for t in existing.values()):
        raise ValueError("Expected the backed-up eight-table, uncustomized Gold model; review concurrent changes.")
    for source, table in existing.items():
        if len(table["partitions"]) != 1 or table["partitions"][0]["mode"] != "directLake":
            raise ValueError(f"{source} is not a single-partition Direct Lake table.")
        if table["partitions"][0]["source"].get("schemaName") != "dbo":
            raise ValueError("Unexpected Gold schema.")
    expression = model["expressions"][0]
    expression_text = "\n".join(expression["expression"])
    match = re.search(r'AzureStorage.DataLake\("([^"]+)"', expression_text)
    if not match:
        raise ValueError("Expected a Direct Lake on OneLake connection.")
    one_lake = match.group(1).rstrip("/")
    # Keep the validated Direct Lake expression unchanged when adding other sources.
    warehouse = databricks["sqlWarehouse"]["odbc_params"]
    values = [
        ("OneLakeSourceUrl", one_lake, "Gold lakehouse URL; parameterize for deployment stages."),
        ("SqlServer", settings["sql_server"], "Match the configured gateway connection exactly."),
        ("SqlDatabase", settings["sql_database"], "Authoritative SQL client and advisor dimensions."),
        ("DatabricksHost", warehouse["hostname"], "Azure Databricks SQL warehouse hostname."),
        ("DatabricksHttpPath", warehouse["path"], "SQL warehouse HTTP path, not the UC mirroring endpoint."),
        ("DatabricksCatalog", databricks["catalog"]["name"], "Authoritative transaction catalog."),
        ("PostgresServer", settings["postgres_server"], "PostgreSQL host reached through the configured connection."),
        ("PostgresDatabase", settings["postgres_database"], "Authoritative opportunity database."),
    ]
    model["expressions"].extend(parameter(*value) for value in values)
    database["compatibilityLevel"] = max(database["compatibilityLevel"], 1702)
    model["discourageImplicitMeasures"] = True
    model["dataAccessOptions"]["returnErrorValuesAsNull"] = False
    model["description"] = (
        "Synthetic Client Analytics composite model: Gold Direct Lake, SQL and Databricks DirectQuery, "
        "PostgreSQL and Excel Import. CAD amounts; facts through 2026-10-31. "
        "Historical economic clients and current account owners are distinct roles."
    )
    annotations = {a["name"]: a["value"] for a in model.get("annotations", [])}
    annotations["__PBI_TimeIntelligenceEnabled"] = "0"
    annotations["PBI_QueryOrder"] = json.dumps([expression["name"]] + [v[0] for v in values] + list(TABLE_NAMES.values()))
    annotations["ClientAnalyticsStorageDesign"] = "8 DirectLake / 3 DirectQuery / 3 Import business tables"
    model["annotations"] = [{"name": k, "value": v} for k, v in annotations.items()]
    tables = []
    relationships = []
    for source, name in TABLE_NAMES.items():
        spec = contract["tables"][source]
        table = copy.deepcopy(existing[source]) if source in GOLD else {
            "name": name, "lineageTag": new_tag(), "columns": [], "partitions": [partition(source, spec)]
        }
        table["name"] = name
        table["description"] = spec["grain"] + ". Synthetic data; financial amounts are in CAD."
        original_columns = {c["sourceColumn"]: c for c in table["columns"]}
        columns = []
        for definition in spec["columns"]:
            raw = definition["name"]
            col = copy.deepcopy(original_columns.get(raw, {"lineageTag": new_tag()}))
            dtype = model_type(definition["type"])
            col.update(name=friendly(raw), sourceColumn=raw, dataType=dtype, summarizeBy="none",
                       description=column_description(source, raw, spec))
            col["isHidden"] = (
                raw.endswith(("Key", "Id")) or raw == "IsSynthetic"
                or source.startswith("fact_") and dtype != "string"
                or raw in {"EffectiveFrom", "EffectiveToExclusive", "OwnershipWeight"}
            )
            col.pop("formatString", None)
            if dtype == "dateTime":
                col["formatString"] = "yyyy-MM-dd"
            elif dtype == "decimal":
                col["formatString"] = CURRENCY if raw.endswith("CAD") else "0.00"
            elif dtype == "int64":
                col["formatString"] = "0"
            col["annotations"] = [{"name": "SummarizationSetBy", "value": "User"}]
            if name == "Calendar" and raw == "Date":
                col["isKey"] = True
            if name == "Calendar" and raw == "MonthName":
                col["sortByColumn"] = "Month Number"
            columns.append(col)
        table["columns"] = columns
        if name == "Calendar":
            table["dataCategory"] = "Time"
            add_hierarchy(table, "Calendar Drilldown", ["Calendar Year", "Calendar Quarter", "Month Name", "Date"])
            add_hierarchy(table, "Fiscal Drilldown", ["Fiscal Year", "Fiscal Quarter", "Year Month", "Date"])
        if name == "Clients":
            add_hierarchy(table, "Client Segmentation", ["Region", "Segment", "Client Name"])
        if name == "Advisors":
            add_hierarchy(table, "Advisor Organization", ["Advisor Region", "Branch Name", "Team Name", "Advisor Name"])
        if name == "Products":
            add_hierarchy(table, "Product Portfolio", ["Product Family", "Product Name"])
        if name == "Account Owners":
            add_hierarchy(table, "Owner Households", ["Household Name", "Owner Name"])
        table["measures"] = [
            {"name": n, "expression": dax, "formatString": fmt, "description": desc,
             "displayFolder": "Data Validation" if n.endswith(("Rows", "Count")) else "Client Analytics",
             "lineageTag": new_tag()}
            for n, dax, fmt, desc in MEASURES.get(name, []) + EXTRA_MEASURES.get(name, [])
        ]
        tables.append(table)
        for key, target in spec["references"].items():
            target_table, target_column = target.split(".")
            relationships.append({
                "name": f"{name} {friendly(key)} to {TABLE_NAMES[target_table]}",
                "fromTable": name, "fromColumn": friendly(key), "fromCardinality": "many",
                "toTable": TABLE_NAMES[target_table], "toColumn": friendly(target_column), "toCardinality": "one",
                "crossFilteringBehavior": "oneDirection",
                "isActive": key not in spec["inactive_relationship_columns"],
                "relyOnReferentialIntegrity": False,
            })
    model["tables"] = tables
    model["relationships"] = relationships
    model["roles"] = [{
        "name": "Example - Ontario Advisors", "modelPermission": "read",
        "description": "Illustrative advisor-office RLS. Does not constitute client/account entitlement security. No members assigned.",
        "tablePermissions": [{"name": "Advisors", "filterExpression": "'Advisors'[Advisor Region] = \"Ontario\""}],
    }]
    model["perspectives"] = [
        {"name": name, "description": "Convenience view of the same model; not a security boundary.",
         "tables": [{"name": t["name"], "columns": [{"name": c["name"]} for c in t["columns"] if not c["isHidden"]],
                     "measures": [{"name": m["name"]} for m in t["measures"]],
                     "hierarchies": [{"name": h["name"]} for h in t.get("hierarchies", [])]}
                    for t in tables if t["name"] in selected]}
        for name, selected in {
            "Executive Overview": {"Calendar", "Clients", "Advisors", "Products", "Account Monthly", "Targets"},
            "Advisor Opportunities": {"Calendar", "Clients", "Advisors", "Products", "Campaigns", "Opportunities", "Interactions", "Channels"},
            "Account Ownership and Transactions": {"Calendar", "Clients", "Advisors", "Accounts", "Account Owners", "Account Ownership", "Products", "Transactions", "Channels", "Account Monthly"},
        }.items()
    ]
    output.mkdir(parents=True, exist_ok=True)
    text = json.dumps(database, indent=2)
    (output / "model.bim").write_text(text, encoding="utf-8")
    definition_parts = [
        {**p, "payload": base64.b64encode(text.encode()).decode()} if p["path"] == "model.bim" else p
        for p in parts if p["path"] != ".platform"
    ]
    payload = {"definition": {"format": "TMSL", "parts": definition_parts}}
    (output / "update_definition.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return database
