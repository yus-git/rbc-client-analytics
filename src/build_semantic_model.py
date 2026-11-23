"""Build a Direct Lake definition from the successful, runtime-generated data contract."""

import argparse
import base64
import json
import re
from pathlib import Path

TABLE_NAMES = {
    "dim_date": "Calendar",
    "dim_client": "Clients",
    "dim_account_owner": "Account Owners",
    "dim_account": "Accounts",
    "dim_advisor": "Advisors",
    "dim_product": "Products",
    "dim_channel": "Channels",
    "dim_campaign": "Campaigns",
    "bridge_account_owner": "Account Ownership",
    "fact_transaction": "Transactions",
    "fact_account_monthly": "Account Monthly",
    "fact_interaction": "Interactions",
    "fact_opportunity": "Opportunities",
    "fact_target": "Targets",
}
CURRENCY = '"CAD " #,##0.00;("CAD " #,##0.00);"CAD " 0.00'
MEASURES = {
    "Transactions": [
        ("Transaction Count", "COUNTROWS('Transactions')", "#,##0", "Booked transaction events."),
        ("Net Contributions", "SUM('Transactions'[Signed Amount CAD])", CURRENCY, "Contributions less withdrawals by booking date."),
        ("Transaction Fees", "SUM('Transactions'[Fee CAD])", CURRENCY, "Illustrative transaction fees."),
        ("Settled Net Contributions",
         "CALCULATE([Net Contributions], USERELATIONSHIP('Transactions'[Settlement Date Key], 'Calendar'[Date Key]))",
         CURRENCY, "Net contributions using settlement date instead of booking date."),
    ],
    "Clients": [
        ("Clients in Master", "DISTINCTCOUNT('Clients'[Client Id])", "#,##0", "Distinct business clients; does not count SCD versions twice."),
        ("Transacting Clients",
         "CALCULATE(DISTINCTCOUNT('Clients'[Client Id]), KEEPFILTERS(TREATAS(VALUES('Transactions'[Client Key]), 'Clients'[Client Key])))",
         "#,##0", "Clients with transactions in the selected fact/date context."),
    ],
    "Account Monthly": [
        ("Assets Under Management",
         "VAR _lastSnapshot = MAX('Account Monthly'[Date Key]) RETURN CALCULATE(SUM('Account Monthly'[Closing Balance CAD]), KEEPFILTERS('Calendar'[Date Key] = _lastSnapshot))",
         CURRENCY, "Closing assets at the last visible month-end. Never sum balances over time."),
        ("Revenue", "SUM('Account Monthly'[Revenue CAD])", CURRENCY, "Synthetic advisory revenue plus transaction fees."),
        ("Cost", "SUM('Account Monthly'[Cost CAD])", CURRENCY, "Synthetic operating cost."),
        ("Profit", "[Revenue] - [Cost]", CURRENCY, "Revenue less cost."),
        ("Profit Margin", "DIVIDE([Profit], [Revenue])", "0.0%", "Profit as a proportion of revenue."),
        ("Monthly Net Flows", "SUM('Account Monthly'[Net Flow CAD])", CURRENCY, "Monthly net flows reconcile to booked transactions."),
        ("Balance Reconciliation Difference",
         "SUM('Account Monthly'[Opening Balance CAD]) + SUM('Account Monthly'[Net Flow CAD]) + SUM('Account Monthly'[Market Movement CAD]) - SUM('Account Monthly'[Closing Balance CAD])",
         CURRENCY, "Must be zero in every slice: opening plus flows plus market movement equals closing."),
    ],
    "Account Ownership": [
        ("Owner Linked Assets",
         "CALCULATE([Assets Under Management], KEEPFILTERS(TREATAS(VALUES('Account Ownership'[Account Key]), 'Accounts'[Account Key])))",
         CURRENCY, "Distinct accounts linked to selected current owners. Non-additive across owners of joint accounts; not an ownership-weighted allocation."),
    ],
    "Interactions": [
        ("Interaction Count", "COUNTROWS('Interactions')", "#,##0", "Client interactions in selected context."),
        ("Average Satisfaction", "AVERAGE('Interactions'[Satisfaction Score])", "0.00", "Mean synthetic satisfaction score on a 1-5 scale."),
    ],
    "Opportunities": [
        ("Opportunity Count", "COUNTROWS('Opportunities')", "#,##0", "Opportunities by creation date."),
        ("Open Weighted Pipeline",
         "CALCULATE(SUMX('Opportunities', 'Opportunities'[Estimated Value CAD] * 'Opportunities'[Probability]), KEEPFILTERS('Opportunities'[Stage] = \"Open\"))",
         CURRENCY, "As-of pipeline weighted by synthetic win probability, sliced by creation date."),
        ("Expected Close Pipeline",
         "CALCULATE([Open Weighted Pipeline], USERELATIONSHIP('Opportunities'[Expected Close Date Key], 'Calendar'[Date Key]))",
         CURRENCY, "Open weighted pipeline by expected close date."),
        ("Won Value",
         "CALCULATE(SUM('Opportunities'[Estimated Value CAD]), KEEPFILTERS('Opportunities'[Stage] = \"Won\"), USERELATIONSHIP('Opportunities'[Actual Close Date Key], 'Calendar'[Date Key]))",
         CURRENCY, "Won opportunity value by actual close date."),
    ],
    "Targets": [
        ("Revenue Target",
         "IF(HASONEVALUE('Targets'[Scenario]) && NOT(ISFILTERED('Clients') || ISFILTERED('Accounts') || ISFILTERED('Account Owners') || ISFILTERED('Channels') || ISFILTERED('Campaigns')), SUM('Targets'[Revenue Target CAD]))",
         CURRENCY, "Requires exactly one scenario. Returns blank for unsupported client/account/channel/campaign grain."),
        ("Revenue Attainment",
         "DIVIDE([Revenue], [Revenue Target])", "0.0%", "Revenue divided by target for the selected scenario and supported shared dimensions."),
    ],
}


def friendly(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)


def model_type(spark_type: str) -> str:
    if spark_type.startswith("decimal("):
        scale = int(spark_type.rstrip(")").split(",")[1])
        if scale > 4:
            raise ValueError(f"Precision review required for {spark_type}")
        return "decimal"
    supported = {"int": "int64", "bigint": "int64", "string": "string", "date": "dateTime", "boolean": "boolean"}
    if spark_type not in supported:
        raise ValueError(f"Unsupported model data type: {spark_type}")
    return supported[spark_type]


def validate_contract(contract: dict) -> None:
    if contract["status"] != "PASSED" or not contract["all_data_synthetic"]:
        raise ValueError("Only a successful synthetic data build can be deployed.")
    tables = contract["tables"]
    if set(tables) != set(TABLE_NAMES):
        raise ValueError("Unexpected table set; review the model mapping before deploying.")
    for name, table in tables.items():
        columns = {column["name"]: column["type"] for column in table["columns"]}
        if len(columns) != len(table["columns"]):
            raise ValueError(f"Duplicate column in {name}")
        if not table["grain"] or not table["primary_key"] or not set(table["primary_key"]) <= columns.keys():
            raise ValueError(f"Missing grain or valid primary key in {name}")
        inactive = table["inactive_relationship_columns"]
        if len(inactive) != len(set(inactive)) or not set(inactive) <= table["references"].keys():
            raise ValueError(f"Inactive relationship has no unique reference in {name}")
        if not name.startswith("dim_"):
            event_key = set(table["primary_key"]) if len(table["primary_key"]) == 1 else set()
            unmapped = {key for key in columns if key.endswith("Key")} - table["references"].keys() - event_key
            if unmapped:
                raise ValueError(f"Unmapped foreign key in {name}: {sorted(unmapped)}")
        active_dimensions = set()
        for column, target in table["references"].items():
            dimension, dimension_column = target.split(".")
            if not dimension.startswith("dim_") or name.startswith("dim_"):
                raise ValueError(f"Not a star-schema relationship: {name}.{column} -> {target}")
            if column not in columns or dimension not in tables:
                raise ValueError(f"Relationship references a missing table/column: {name}.{column} -> {target}")
            target_columns = {item["name"]: item["type"] for item in tables[dimension]["columns"]}
            if dimension_column not in target_columns:
                raise ValueError(f"Relationship references a missing dimension column: {target}")
            if columns[column] != target_columns[dimension_column]:
                raise ValueError(f"Relationship key types differ: {name}.{column} -> {target}")
            if tables[dimension]["primary_key"] != [dimension_column]:
                raise ValueError(f"Relationship must reference a unique single-column dimension key: {target}")
            if column not in inactive:
                if dimension in active_dimensions:
                    raise ValueError(f"{name} has multiple active relationships to {dimension}")
                active_dimensions.add(dimension)


def build(contract_path: Path, output: Path) -> None:
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    validate_contract(contract)
    tables = contract["tables"]
    files = {
        "definition.pbism": json.dumps({
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
            "version": "4.2",
            "settings": {"qnaEnabled": True},
        }, indent=2),
        "definition/database.tmdl": "database 'Client Analytics Direct Lake'\n\tcompatibilityLevel: 1702\n\tcompatibilityMode: powerBI\n",
        "definition/model.tmdl": (
            "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
            "\tsourceQueryCulture: en-US\n\tdiscourageImplicitMeasures\n\n"
            + "\n".join(f"ref table '{name}'" for name in TABLE_NAMES.values()) + "\n"
        ),
        "definition/expressions.tmdl": (
            "expression 'Direct Lake Client Analytics' =\n"
            "\t\tlet\n"
            f'\t\t\tSource = AzureStorage.DataLake("https://onelake.dfs.fabric.microsoft.com/{contract["workspace_id"]}/{contract["lakehouse_id"]}", [HierarchicalNavigation=true])\n'
            "\t\tin\n\t\t\tSource\n\tkind: m\n"
        ),
    }
    relationships = []
    for source_name, table in tables.items():
        name = TABLE_NAMES[source_name]
        content = [f"/// {table['grain']}. All data synthetic.", f"table '{name}'"]
        if name == "Calendar":
            content.append("\tdataCategory: Time")
        for measure_name, expression, fmt, description in MEASURES.get(name, []):
            content.extend([
                "", f"\t/// {description}", f"\tmeasure '{measure_name}' = {expression}",
                f"\t\tformatString: {fmt}", "\t\tdisplayFolder: Client Analytics",
            ])
        for column in table["columns"]:
            original = column["name"]
            data_type = model_type(column["type"])
            hidden = (
                original.endswith(("Key", "Id")) or original == "IsSynthetic"
                or source_name.startswith("fact_") and data_type != "string"
                or original in ("EffectiveFrom", "EffectiveToExclusive", "OwnershipWeight")
            )
            content.extend(["", f"\tcolumn '{friendly(original)}'", f"\t\tdataType: {data_type}"])
            if hidden:
                content.append("\t\tisHidden")
            content.extend(["\t\tsummarizeBy: none", f"\t\tsourceColumn: {original}"])
            if data_type == "dateTime":
                content.append("\t\tformatString: yyyy-MM-dd")
            if name == "Calendar" and original == "Date":
                content.append("\t\tisKey")
            if name == "Calendar" and original == "MonthName":
                content.append("\t\tsortByColumn: 'Month Number'")
        if name == "Calendar":
            content.extend([
                "", "\thierarchy 'Calendar Drilldown'",
                "\t\tlevel Year", "\t\t\tordinal: 0", "\t\t\tcolumn: 'Calendar Year'",
                "\t\tlevel Quarter", "\t\t\tordinal: 1", "\t\t\tcolumn: 'Calendar Quarter'",
                "\t\tlevel Month", "\t\t\tordinal: 2", "\t\t\tcolumn: 'Month Name'",
                "\t\tlevel Day", "\t\t\tordinal: 3", "\t\t\tcolumn: Date",
            ])
        content.extend([
            "", f"\tpartition '{name}' = entity", "\t\tmode: directLake", "\t\tsource",
            f"\t\t\tentityName: {source_name}", "\t\t\tschemaName: gold",
            "\t\t\texpressionSource: 'Direct Lake Client Analytics'",
        ])
        files[f"definition/tables/{name}.tmdl"] = "\n".join(content) + "\n"
        for column, target in table["references"].items():
            dimension, dimension_column = target.split(".")
            relationships.extend([
                f"relationship '{name} {friendly(column)} to {TABLE_NAMES[dimension]}'",
                f"\tfromColumn: '{name}'.'{friendly(column)}'",
                f"\ttoColumn: '{TABLE_NAMES[dimension]}'.'{friendly(dimension_column)}'",
                "\tfromCardinality: many", "\ttoCardinality: one", "\tcrossFilteringBehavior: oneDirection",
            ])
            if column in table["inactive_relationship_columns"]:
                relationships.append("\tisActive: false")
            relationships.append("")
    files["definition/relationships.tmdl"] = "\n".join(relationships)
    output.mkdir(parents=True, exist_ok=True)
    parts = []
    for relative, text in files.items():
        path = output.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        parts.append({
            "path": relative,
            "payload": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "payloadType": "InlineBase64",
        })
    payload = {
        "displayName": "Client Analytics - Direct Lake",
        "type": "SemanticModel",
        "description": "Synthetic multi-fact star schema. Single-direction conformed dimensions, explicit DAX, inactive date roles and current-ownership bridge.",
        "definition": {"format": "TMDL", "parts": parts},
    }
    (output / "create_model.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Built {len(tables)} tables, {sum(len(t['references']) for t in tables.values())} relationships, "
          f"{sum(len(m) for m in MEASURES.values())} measures. Service validation/refresh is still required.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("semantic_model"))
    args = parser.parse_args()
    build(args.contract, args.output)
