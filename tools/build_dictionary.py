"""Generate the customer data dictionary from the sanitized seed contract."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    contract = json.loads((ROOT / "data" / "data_contract.json").read_text(encoding="utf-8"))
    lines = [
        "# Data dictionary", "",
        "[Home](../README.md) | [Source/storage inventory](architecture.md)", "",
        "Generated from the sanitized seed contract with `python tools/build_dictionary.py`.",
        "Names below are physical source columns; the semantic model uses friendly display names.",
        "All financial amounts suffixed CAD are in Canadian dollars. All records are synthetic.", "",
        "The `IsSynthetic` field is a required data-quality flag, not an access-control mechanism.", "",
    ]
    for name, table in contract["tables"].items():
        lines += [f"## {name}", "", f"**Grain:** {table['grain']}.",
                  f"**Rows:** {table['expected_rows']:,}.",
                  "**Primary key:** " + ", ".join(f"`{k}`" for k in table["primary_key"]) + ".", "",
                  "| Column | Source type | Relationship role |", "|---|---|---|"]
        for c in table["columns"]:
            role = []
            if c["name"] in table["primary_key"]:
                role.append("Primary key")
            target = table["references"].get(c["name"])
            if target:
                role.append("References `" + target + "`")
            if c["name"] in table["inactive_relationship_columns"]:
                role.append("Inactive date role")
            lines.append(f"| `{c['name']}` | `{c['type']}` | {'; '.join(role)} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    path = ROOT / "docs" / "data-dictionary.md"
    path.write_text(build(), encoding="utf-8")
    print(f"Wrote {path}")
