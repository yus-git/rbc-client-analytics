"""Load the supplied CSVs into NEW tables in an existing SQL Server/Azure SQL database.

Requires pyodbc and Microsoft ODBC Driver 18 for SQL Server.
Set RBCCA_SQL_CONNECTION_STRING through your local secure environment; never commit it.
No databases are created; no existing tables are replaced. All table loads commit together.
"""

import csv
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path


def value(text: str, data_type: str):
    if text == "":
        return None
    if data_type in ("int", "bigint"):
        return int(text)
    if data_type.startswith("decimal("):
        return Decimal(text)
    if data_type == "date":
        return date.fromisoformat(text)
    if data_type == "boolean":
        if text.lower() not in ("true", "false"):
            raise ValueError(f"Invalid boolean value: {text}")
        return text.lower() == "true"
    return text


def main() -> None:
    import pyodbc

    connection_string = os.environ.get("RBCCA_SQL_CONNECTION_STRING")
    if not connection_string:
        raise RuntimeError("Set RBCCA_SQL_CONNECTION_STRING securely before running.")
    root = Path(__file__).resolve().parent
    contract = json.loads((root.parent / "data_contract.json").read_text(encoding="utf-8"))
    tables = json.loads((root / "table_list.json").read_text(encoding="utf-8"))
    connection = pyodbc.connect(connection_string, autocommit=False)
    try:
        cursor = connection.cursor()
        cursor.execute((root / "schema_sqlserver.sql").read_text(encoding="utf-8"))
        cursor.fast_executemany = True
        for name in tables:
            definition = contract["tables"][name]
            columns = definition["columns"]
            names = [column["name"] for column in columns]
            insert = (
                f"INSERT INTO [ca_demo].[{name}] ("
                + ", ".join(f"[{name}]" for name in names)
                + ") VALUES (" + ", ".join("?" for _ in names) + ")"
            )
            with (root / "data" / f"{name}.csv").open(encoding="utf-8", newline="") as source:
                reader = csv.reader(source)
                if next(reader) != names:
                    raise ValueError(f"CSV column order differs from the contract: {name}")
                batch = []
                for row in reader:
                    if len(row) != len(columns):
                        raise ValueError(f"Malformed CSV record in {name}")
                    batch.append(tuple(value(text, column["type"]) for text, column in zip(row, columns)))
                    if len(batch) == 1000:
                        cursor.executemany(insert, batch)
                        batch.clear()
                if batch:
                    cursor.executemany(insert, batch)
            actual = cursor.execute(f"SELECT COUNT_BIG(*) FROM [ca_demo].[{name}]").fetchone()[0]
            if actual != definition["expected_rows"]:
                raise ValueError(f"{name}: expected {definition['expected_rows']} rows, got {actual}")
            print(f"Validated {name}: {actual:,} rows", flush=True)
        cursor.execute((root / "foreign_keys_sqlserver.sql").read_text(encoding="utf-8"))
        connection.commit()
        print("All tables and local foreign keys committed successfully.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
