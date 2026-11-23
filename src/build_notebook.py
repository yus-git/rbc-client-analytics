"""Package the cell source into a schema-validated Fabric notebook."""

import argparse
import ast
import json
from pathlib import Path

import nbformat


def build(
    source_path: Path, workspace_id: str, lakehouse_id: str, lakehouse_name: str,
    *, output_path: Path | None = None, title: str | None = None,
    introduction: str | None = None, parameter_source: str | None = None,
) -> Path:
    source = source_path.read_text(encoding="utf-8")
    ast.parse(source, filename=str(source_path))
    notebook = nbformat.v4.new_notebook()
    notebook.metadata = {
        "kernelspec": {
            "display_name": "Synapse PySpark",
            "language": "python",
            "name": "synapse_pyspark",
        },
        "language_info": {"name": "python"},
        "dependencies": {
            "lakehouse": {
                "default_lakehouse": lakehouse_id,
                "default_lakehouse_workspace_id": workspace_id,
                "default_lakehouse_name": lakehouse_name,
                "known_lakehouses": [{"id": lakehouse_id}],
            }
        },
    }
    notebook.cells.append(nbformat.v4.new_markdown_cell(
        "# Synthetic Client Analytics: multi-fact star schema\n\n"
        "Development demo only. All identities and financial values are synthetic. "
        "No external source connection, security policy, or production readiness is implied.\n\n"
        "The final cell publishes the success marker only after persisted-data quality checks "
        "and source extracts complete. A failed run can leave partial synthetic tables; "
        "inspect the error before explicitly enabling reset."
    ))
    if title is not None or introduction is not None:
        if title is None or introduction is None:
            raise ValueError("A custom notebook requires both title and introduction.")
        notebook.cells[0].source = f"# {title}\n\n{introduction}\n"
    for index, section in enumerate(source.split("# %% ")[1:]):
        title, code = section.split("\n", 1)
        cell = nbformat.v4.new_code_cell(code.rstrip() + "\n")
        cell.metadata["microsoft"] = {"language": "python"}
        if index == 0:
            cell.metadata["tags"] = ["parameters"]
            if parameter_source is not None:
                ast.parse(parameter_source)
                cell.source = parameter_source.rstrip() + "\n"
        notebook.cells.append(nbformat.v4.new_markdown_cell(f"## {title}"))
        notebook.cells.append(cell)
    nbformat.validate(notebook)
    output = output_path or source_path.with_suffix(".ipynb")
    nbformat.write(notebook, output)
    raw = json.loads(output.read_text(encoding="utf-8"))
    for cell in raw["cells"]:
        if cell["cell_type"] == "code":
            if not all(line.endswith("\n") for line in cell["source"]):
                raise ValueError("Each code source line must end with a newline.")
    print(f"Validated notebook with {len(notebook.cells)} cells: {output}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--lakehouse-id", required=True)
    parser.add_argument("--lakehouse-name", required=True)
    args = parser.parse_args()
    build(
        Path(__file__).with_name("generate_client_analytics.py"),
        args.workspace_id,
        args.lakehouse_id,
        args.lakehouse_name,
    )
