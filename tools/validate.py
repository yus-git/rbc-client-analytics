"""Validate the customer package without connecting to any cloud service."""

import ast
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def validate():
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    from openpyxl import load_workbook

    contract = json.loads((ROOT / "data" / "data_contract.json").read_text(encoding="utf-8"))
    datasets = {}
    for path in (ROOT / "data").rglob("*.parquet"):
        datasets[path.stem] = pq.read_table(path)
    for path in (ROOT / "data").rglob("*.csv"):
        if path.stem not in contract["tables"]:
            continue
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        datasets[path.stem] = pa.Table.from_pylist(rows)
    book = load_workbook(ROOT / "data" / "excel" / "Client_Analytics_Planning.xlsx", data_only=True)
    for sheet in book:
        for name in sheet.tables:
            cells = list(sheet[sheet.tables[name].ref])
            headers = [c.value for c in cells[0]]
            datasets[name] = pa.Table.from_pylist([dict(zip(headers, (c.value for c in row))) for row in cells[1:]])
    assert set(datasets) == set(contract["tables"]), "Seed inventory differs from the contract"
    for name, table in datasets.items():
        spec = contract["tables"][name]
        assert table.num_rows == spec["expected_rows"], (name, table.num_rows)
        assert set(table.column_names) == {c["name"] for c in spec["columns"]}, name
        flags = pc.cast(table["IsSynthetic"], pa.string()).to_pylist()
        assert all(str(v).lower() == "true" for v in flags), f"Non-synthetic or missing flag: {name}"
        keys = table.select(spec["primary_key"]).to_pylist()
        normalized = [tuple(str(row[k]) for k in spec["primary_key"]) for row in keys]
        assert len(set(normalized)) == len(normalized), f"Duplicate primary keys: {name}"
        assert all(all(v not in {"None", ""} for v in key) for key in normalized), name
    for name, table in datasets.items():
        for col, target in contract["tables"][name]["references"].items():
            dimension, key = target.split(".")
            allowed = {str(v) for v in datasets[dimension][key].to_pylist()}
            values = {str(v) for v in table[col].to_pylist() if v is not None and v != ""}
            assert values <= allowed, f"Orphan foreign keys: {name}.{col}"
    assert str(pc.sum(datasets["fact_transaction"]["SignedAmountCAD"]).as_py()) == "-1438757.40"
    assert str(pc.sum(datasets["fact_transaction"]["FeeCAD"]).as_py()) == "500220.78"
    for path in ROOT.rglob("*.py"):
        if not any(x in path.parts for x in (".venv", ".git", ".generated")):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for path in [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]:
        for link in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            target = link.split("#")[0]
            if not target or re.match(r"[a-z]+://", target):
                continue
            assert (path.parent / unquote(target)).exists(), f"Broken link: {path}: {link}"
    manifest = ROOT / "data" / "SHA256SUMS.txt"
    if manifest.exists():
        for line in manifest.read_text().splitlines():
            digest, name = line.split("  ", 1)
            path = ROOT / "data" / name
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, f"Checksum mismatch: {name}"
    print(f"PASS: {len(datasets)} tables / {sum(t.num_rows for t in datasets.values()):,} synthetic rows; "
          "all PKs/FKs, totals, Python syntax, local documentation links and seed checksums.")


if __name__ == "__main__":
    validate()
