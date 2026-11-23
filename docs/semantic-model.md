# Semantic model and report construction

[Home](../README.md) | [Architecture](architecture.md) | [Deployment](deployment.md)

## How the original model was configured

1. Read the existing eight-table Gold model with Fabric `getDefinition`.
2. Preserve the original Direct Lake shared expression and its entity sources.
3. Add six tables with explicit M partitions:
   SQL Clients/Advisors and Databricks Transactions in DirectQuery;
   PostgreSQL Opportunities and Excel Campaigns/Targets in Import.
4. Add friendly column names, formats, measures, relationships, hierarchies,
   perspectives and an illustrative RLS role.
5. Deploy `model.bim`/`definition.pbism` with `updateDefinition`.
6. Configure source credentials and mappings separately in the Fabric Service.
7. Refresh and run targeted cross-source DAX queries, then render report exports.

The portable builder constructs the same kind of pristine eight-table definition
locally, then extends it. This avoids needing the original tenant's model backup.
It does **not** export credentials or recreate gateway objects.

## Direct Lake partitions

Conceptual model.bim structure:

```json
{
  "name": "Account Monthly",
  "partitions": [{
    "name": "fact_account_monthly",
    "mode": "directLake",
    "source": {
      "type": "entity",
      "schemaName": "dbo",
      "entityName": "fact_account_monthly",
      "expressionSource": "DirectLake - Gold"
    }
  }]
}
```

The shared M expression is a real OneLake source:

```powerquery
AzureStorage.DataLake(
    "https://onelake.dfs.fabric.microsoft.com/<workspace-guid>/<gold-lakehouse-guid>",
    [HierarchicalNavigation=true]
)
```

The working expression was preserved during the live repair. Do not change a
Direct Lake table into an arbitrary M-query partition. Also do not generalize
that URL parameters are unsupported: official Direct Lake documentation supports
parameterization; source recognition must be verified for the exact definition.

## DirectQuery partitions

SQL Server:

```powerquery
let
    Source = Sql.Database(SqlServer, SqlDatabase, [CreateNavigationProperties=false]),
    Data = Source{[Schema="ca_demo", Item="dim_client"]}[Data]
in
    Data
```

Databricks:

```powerquery
let
    Source = Databricks.Catalogs(DatabricksHost, DatabricksHttpPath,
        [Catalog=null, Database=null, Implementation="2.0"]),
    Catalog = Source{[Name=DatabricksCatalog, Kind="Database"]}[Data],
    Schema = Catalog{[Name="ca_dq", Kind="Schema"]}[Data],
    Data = Schema{[Name="fact_transaction", Kind="Table"]}[Data]
in
    Data
```

The builder also selects/types the exact contract columns. The null connector
options followed by explicit navigation fixed the original empty-catalog
navigation failure. Do not replace this with `Databricks.Query`: the connector
documentation does not support that entry point for semantic-model DirectQuery.

## Import partitions

PostgreSQL uses `PostgreSQL.Database` followed by `ca_demo.fact_opportunity`
navigation. Excel enumerates OneLake files with `HierarchicalNavigation=false`,
selects exactly `Files/planning/Client_Analytics_Planning.xlsx`, then imports the
two named tables with `Excel.Workbook`.

The OneLake expression used for Direct Lake and the file-enumeration expression
used by Excel are intentionally different. A successful Direct Lake query does
not prove OAuth credentials for Excel Import refresh are configured.

## Connection bindings

| Model source | Connection type | Route | Identity configuration |
|---|---|---|---|
| Gold OneLake + planning file access | ADLS Gen2/OneLake cloud connection | Cloud, unless a separately supported security design applies | Explicit organizational-account OAuth in the tested demo |
| SQL host/database | SQL Server | Standard on-premises gateway | Windows account in the original demo; approved read identity in yours |
| Databricks host/warehouse path | Azure Databricks | Cloud in original demo; VNet gateway in private option | Approved Entra/OAuth or service identity |
| PostgreSQL host:port/database | PostgreSQL | Standard on-premises gateway in original demo | Read-only Basic account; TLS in customer deployment |

Catalog mirroring uses a **separate Azure Databricks workspace connection**,
outside these semantic-model source mappings.

Credentials, gateway ownership, connection sharing and connection binding are
four different things. A workspace role does not automatically grant use of a
shared source connection. Test the configured service identity, not just your
interactive administrator identity.

## Measures and relationships

The builder defines 34 measures across business folders: assets, flows, revenue,
ownership, activity, planning, opportunities and quality. Examples:

- `Assets Under Management`: last visible account-monthly snapshot, in CAD.
- `Revenue`: additive monthly revenue, in CAD.
- `Revenue Target`: returns blank unless exactly one scenario is selected.
- `Revenue Attainment`: revenue / target, formatted as a percentage.
- `Settled Net Contributions`: settlement-date relationship activated.
- `Owner Allocated Assets`: weighted bridge allocation through virtual filtering.

The exact expressions are in
[the shared measure definitions](../src/build_semantic_model.py) and
[hybrid model builder](../src/build_hybrid_model.py). Do not add a bidirectional
relationship to "fix" a blank target: first check scenario selection and grain.

Six hierarchies and three perspectives support discovery. Perspectives are not
security boundaries. One illustrative advisor-region RLS role is defined but
unassigned; do not ship it as a production entitlement model. Model restrictions
must be tested as a Viewer: Admin/Member/Contributor roles are not a substitute
for RLS verification.

## Interactive report

[The report builder](../src/build_demo_reports.py) produces PBIR for an executive
overview, client exploration, advisor performance, data delivery and a hidden
client drill-through page. It includes slicers, buttons, navigation, an external
documentation link, author bookmarks and explicit visual interaction metadata.

Two implementation details are covered by regression tests:

- Slicer defaults use the PBIR nested filter-value wrapper:
  `properties.filter = {"filter": {"Version": 2, ...}}`.
  Without it, the report can render "All" despite apparently valid JSON.
- Advisor performance defaults to **October 2026 / Plan**. Targets require a
  single scenario, so "All" intentionally produces a blank target measure.

Generated PBIR includes a `definition.pbir` connection to the target model ID.
Creating a report definition does not create credentials or grant Build.

Local semantic layout templates provide focused authoring views. Fabric web
model editing can discard imported layout metadata; this package does **not**
promise to rearrange the web canvas automatically.

## Paginated report

The RDL connects directly to the same semantic model via **PBIDATASET**.
Parameters: **Month**, **Region**, **Scenario**. The DAX query uses a selected
month, region and scenario and returns all advisor/product detail rows.

Critical binding convention:

```xml
<QueryParameter Name="Month">
  <Value>=Parameters!Month.Value</Value>
</QueryParameter>
```

DAX refers to **`@Month`**, but the RDL binding name is **`Month` without @**.
Adding @ to the binding caused the original undeclared-parameter error.

The report is landscape Letter, repeats column headers and includes page
numbering. Default parameters rendered 800 detail rows over 45 PDF pages in the
original environment. It is not a screenshot of a scrolling interactive table.

## Editing an existing deployment safely

1. Export current model/report definitions; keep the backup in restricted
   deployment storage, not this public-safe source tree.
2. Diff source modes, relationships, measures, parameters, connections and
   resource paths. Confirm there were no concurrent user edits.
3. Patch only reviewed definition parts; preserve lineage IDs and report IDs.
4. Use updateDefinition once; record the operation ID and monitor it.
5. Re-query affected measures and render affected pages.

For report updates, inspect actual static-resource part names: Fabric may
normalize a theme reference from `ClientAnalytics.json` to `ClientAnalytics`
without changing the physical part's name. Preserve a consistent reference.

The `src` modules are builder internals. Use `tools/build.py` as the supported
portable entry point, not the original standalone script mains.

**References:** [Direct Lake development](https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-develop),
[semantic model definitions](https://learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items/get-semantic-model-definition),
[update definitions](https://learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items/update-semantic-model-definition),
[PBIP report definitions](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report).
