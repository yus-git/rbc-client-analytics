import base64
import copy
import json
import re
import sys
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build import BRONZE, pristine_gold, read, run, validate
from build_hybrid_model import build as build_model
from build_demo_reports import RDL_NS


def environment():
    config = read(ROOT / "config" / "environment.example.json")
    config["workspace_id"] = str(uuid.uuid4())
    config["lakehouses"] = {name: str(uuid.uuid4()) for name in config["lakehouses"]}
    config.update(sql_server=r"sql.example.test\INSTANCE", postgres_server="postgres.example.test:5432",
                  databricks_host="adb-example.azuredatabricks.net",
                  databricks_http_path="/sql/1.0/warehouses/abcdef1234567890",
                  semantic_model_id=str(uuid.uuid4()), paginated_report_id=str(uuid.uuid4()))
    return config


class BuildTests(unittest.TestCase):
    def test_rejects_placeholders_and_shared_layer_ids(self):
        with self.assertRaises(ValueError):
            validate(read(ROOT / "config" / "environment.example.json"), "model")
        config = environment()
        config["lakehouses"]["lh_ca_gold"] = config["lakehouses"]["lh_ca_silver"]
        with self.assertRaisesRegex(ValueError, "distinct"):
            validate(config, "notebooks")

    def test_model_is_portable_and_preserves_storage_contract(self):
        config = environment()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            run("model", config, output)
            database = read(output / "model" / "model.bim")
            model = database["model"]
            tables = {t["name"]: t for t in model["tables"]}
            modes = [t["partitions"][0]["mode"] for t in tables.values()]
            self.assertEqual([modes.count(m) for m in ("directLake", "directQuery", "import")], [8, 3, 3])
            self.assertEqual(len(model["relationships"]), 29)
            self.assertEqual(sum(r["isActive"] for r in model["relationships"]), 26)
            self.assertTrue(all(r["crossFilteringBehavior"] == "oneDirection" for r in model["relationships"]))
            self.assertEqual(sum(len(t["measures"]) for t in tables.values()), 34)
            measures = {x["name"] for table in tables.values() for x in table["measures"]}
            for doc in (ROOT / "docs").glob("*.md"):
                for dax in re.findall(r"```dax\n(.*?)```", doc.read_text(), re.S):
                    references = set(re.findall(r"(?<!')\[([^\]]+)\]", dax))
                    self.assertTrue(references <= measures, (doc.name, references - measures))
            expr = {e["name"]: e["expression"] for e in model["expressions"]}
            self.assertIn(config["sql_server"], expr["SqlServer"])
            self.assertIn(config["postgres_server"], expr["PostgresServer"])
            self.assertIn(config["lakehouses"]["lh_ca_gold"], "\n".join(expr["DirectLake - Gold"]))
            tx = "\n".join(tables["Transactions"]["partitions"][0]["source"]["expression"])
            self.assertIn("Catalog=null, Database=null", tx)
            self.assertIn('Kind="Database"', tx)
            self.assertIn('Name="ca_dq"', tx)
            self.assertIn("Excel.Workbook", "\n".join(tables["Targets"]["partitions"][0]["source"]["expression"]))
            expected = read(ROOT / "data" / "data_contract.json")["tables"]
            by_source = {v: k for k, v in __import__("build_semantic_model").TABLE_NAMES.items()}
            for table in tables.values():
                self.assertEqual({c["sourceColumn"] for c in table["columns"]},
                                 {c["name"] for c in expected[by_source[table["name"]]]["columns"]})

    def test_existing_model_customizations_are_not_overwritten(self):
        config = environment()
        contract = read(ROOT / "data" / "data_contract.json")
        before = pristine_gold(config, contract)
        model = json.loads(base64.b64decode(before["definition"]["parts"][0]["payload"]))
        model["model"]["tables"][0]["measures"] = [{"name": "Existing", "expression": "1"}]
        before["definition"]["parts"][0]["payload"] = base64.b64encode(json.dumps(model).encode()).decode()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "uncustomized"):
                build_model(before, contract, {}, Path(folder), settings=config)

    def test_report_parameter_names_and_slicer_defaults(self):
        config = environment()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            for stage in ("model", "paginated", "interactive"):
                run(stage, config, output)
            ns = {"r": RDL_NS}
            root = ET.parse(output / "Client Analytics - Advisor Pack.rdl").getroot()
            query = root.find(".//r:DataSet[@Name='Performance']/r:Query", ns)
            text = query.find("r:CommandText", ns).text
            bindings = query.findall("r:QueryParameters/r:QueryParameter", ns)
            self.assertEqual({p.attrib["Name"] for p in bindings}, {"Month", "Region", "Scenario"})
            for p in bindings:
                self.assertIn("@" + p.attrib["Name"], text)
                self.assertEqual(p.find("r:Value", ns).text, "=Parameters!" + p.attrib["Name"] + ".Value")
            self.assertNotIn("TOPN", text)
            self.assertIn(config["semantic_model_id"], root.find(".//r:ConnectString", ns).text)
            for name, value in [("ad_month", "'2026-10'"), ("ad_scenario", "'Plan'")]:
                v = read(output / "ClientAnalytics.Report" / "definition" / "pages" / "advisors"
                         / "visuals" / name / "visual.json")
                f = v["visual"]["objects"]["general"][0]["properties"]["filter"]["filter"]
                self.assertEqual(f["Where"][0]["Condition"]["In"]["Values"], [[{"Literal": {"Value": value}}]])
            report = read(output / "interactive.create.json")
            self.assertNotIn("semanticModelDiagramLayout.json", {p["path"] for p in report["definition"]["parts"]})

    def test_notebooks_bind_only_configured_targets(self):
        import nbformat
        config = environment()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            run("notebooks", config, output)
            for name, layer in [("nb_ca_bronze_to_silver", "silver"), ("nb_ca_silver_to_gold", "gold")]:
                book = nbformat.read(output / (name + ".ipynb"), as_version=4)
                nbformat.validate(book)
                self.assertEqual(book.metadata.dependencies.lakehouse.default_lakehouse,
                                 config["lakehouses"]["lh_ca_" + layer])
                params = next(c for c in book.cells if "parameters" in c.metadata.get("tags", []))
                scope = {}
                exec(params.source, {}, scope)
                settings = json.loads(scope["config_json"])
                self.assertEqual(set(settings["tables"]), set(BRONZE))
                self.assertEqual(settings["snapshot_baseline"]["latest_aum_cad"], "11816392773.18")
                self.assertEqual(scope["layer"], layer)


if __name__ == "__main__":
    unittest.main()
