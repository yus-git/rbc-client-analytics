"""Build PBIP layout metadata; Fabric web layouts must be arranged in the web UI."""

import argparse
import base64
import copy
import json
from pathlib import Path

from build_semantic_model import TABLE_NAMES, friendly, validate_contract


def validate_schema(model: dict, contract: dict) -> None:
    validate_contract(contract)
    tables = {t["name"]: t for t in model["tables"]}
    if set(tables) != set(TABLE_NAMES.values()):
        raise ValueError("The live table set differs from the 14-table contract; review before organizing.")
    expected = {}
    for source, spec in contract["tables"].items():
        for column, target in spec["references"].items():
            dimension, target_column = target.split(".")
            key = (TABLE_NAMES[source], friendly(column), TABLE_NAMES[dimension], friendly(target_column))
            expected[key] = column not in spec["inactive_relationship_columns"]
    actual = {}
    for relation in model.get("relationships", []):
        key = tuple(relation[k] for k in ("fromTable", "fromColumn", "toTable", "toColumn"))
        if key in actual:
            raise ValueError(f"Duplicate relationship endpoints: {key}")
        if key not in expected:
            raise ValueError(f"Unexpected relationship: {key}")
        if (relation.get("fromCardinality", "many"), relation.get("toCardinality", "one")) != ("many", "one"):
            raise ValueError(f"Expected dimension-to-fact one-to-many cardinality: {key}")
        if relation.get("crossFilteringBehavior", "oneDirection") != "oneDirection":
            raise ValueError(f"Expected single-direction filtering: {key}")
        from_columns = {c["name"]: c for c in tables[key[0]]["columns"]}
        to_columns = {c["name"]: c for c in tables[key[2]]["columns"]}
        if from_columns[key[1]]["dataType"] != to_columns[key[3]]["dataType"]:
            raise ValueError(f"Relationship key types differ: {key}")
        actual[key] = relation.get("isActive", True)
    if actual != expected:
        raise ValueError("Relationship endpoints or active date roles differ from the source contract.")


def diagram(name: str, ordinal: int, placements: list[tuple], tables: dict, zoom: int = 75) -> dict:
    nodes = []
    for index, (table, x, y, height) in enumerate(placements):
        nodes.append({
            "location": {"x": x, "y": y},
            "nodeIndex": table,
            "nodeLineageTag": tables[table]["lineageTag"],
            "size": {"height": height, "width": 260},
            "zIndex": index,
        })
    return {
        "ordinal": ordinal,
        "scrollPosition": {"x": 0, "y": 0},
        "nodes": nodes,
        "name": name,
        "zoomValue": zoom,
        "pinKeyFieldsToTop": True,
        "showExtraHeaderInfo": False,
        "hideKeyFieldsWhenCollapsed": False,
        "tablesLocked": False,
    }


def organize(before: dict, contract: dict) -> tuple[dict, dict]:
    parts = before["definition"]["parts"]
    database = json.loads(base64.b64decode(next(p["payload"] for p in parts if p["path"] == "model.bim")))
    model = database["model"]
    validate_schema(model, contract)
    tables = {t["name"]: t for t in model["tables"]}
    dimensions = ["Calendar", "Clients", "Accounts", "Advisors", "Products", "Channels", "Campaigns", "Account Owners"]
    facts = ["Transactions", "Account Monthly", "Interactions", "Opportunities", "Targets", "Account Ownership"]
    diagrams = [diagram("All tables", 0,
                        [(t, 30 + i * 300, 30, 230) for i, t in enumerate(dimensions)]
                        + [(t, 180 + i * 330, 510, 350) for i, t in enumerate(facts)],
                        tables, zoom=50)]
    views = [
        ("01 AUM and Profitability", "Account Monthly", ["Clients", "Calendar", "Advisors", "Accounts", "Products"]),
        ("02 Transactions", "Transactions", ["Clients", "Calendar", "Advisors", "Accounts", "Products", "Channels"]),
        ("03 Interactions", "Interactions", ["Clients", "Calendar", "Advisors", "Channels", "Campaigns"]),
        ("04 Opportunities", "Opportunities", ["Clients", "Calendar", "Advisors", "Products", "Campaigns"]),
        ("05 Targets", "Targets", ["Advisors", "Calendar", "Products"]),
    ]
    positions = [(40, 20), (370, 20), (700, 20), (40, 660), (700, 660), (370, 660)]
    for ordinal, (name, fact, dimensions) in enumerate(views, 1):
        connected = {r["toTable"] for r in model["relationships"] if r["fromTable"] == fact}
        if connected != set(dimensions):
            raise ValueError(f"Layout must contain exactly the dimensions related to {fact}.")
        placements = [(t, x, y, 210) for t, (x, y) in zip(dimensions, positions)]
        placements.append((fact, 370, 310, 310))
        diagrams.append(diagram(name, ordinal, placements, tables))
    diagrams.append(diagram("06 Ownership Allocation", 6, [
        ("Account Owners", 30, 340, 250),
        ("Account Ownership", 360, 340, 280),
        ("Accounts", 690, 340, 250),
        ("Account Monthly", 1020, 340, 310),
        ("Calendar", 1020, 20, 230),
    ], tables, zoom=70))
    layout = {
        "version": "1.1.0", "diagrams": diagrams,
        "selectedDiagram": views[0][0], "defaultDiagram": "All tables",
    }
    new_parts = [copy.deepcopy(p) for p in parts if p["path"] not in {".platform", "diagramLayout.json"}]
    new_parts.append({
        "path": "diagramLayout.json", "payloadType": "InlineBase64",
        "payload": base64.b64encode(json.dumps(layout, indent=2).encode()).decode(),
    })
    return {"definition": {"format": "TMSL", "parts": new_parts}}, layout


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("hybrid_semantic_model"))
    args = parser.parse_args()
    before = json.loads(args.before.read_text(encoding="utf-8-sig"))
    contract = json.loads(Path(__file__).with_name("data_contract.json").read_text(encoding="utf-8-sig"))
    payload, layout = organize(before, contract)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "diagramLayout.json").write_text(json.dumps(layout, indent=2), encoding="utf-8")
    (args.output / "update_layout_definition.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"schema": "29 contract relationships validated",
                      "views": [d["name"] for d in layout["diagrams"]],
                      "semanticMetadataChanged": False}))
