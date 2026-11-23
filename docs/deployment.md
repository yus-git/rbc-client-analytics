# Deploy in your own environment

[Home](../README.md) | [Source setup](sources.md) | [Model/report setup](semantic-model.md)

## What is automated, and what is not

| Stage | Provided automation | Human/environment prerequisite |
|---|---|---|
| Synthetic seed | Complete fixed seed plus integrity checker | Approve synthetic-data use and repository access |
| Source load | SQL, PostgreSQL and Databricks loaders | Provision databases/catalog/volume; authenticate securely |
| Fabric landing | Explicit paths and conversion examples | Create shortcuts, mirrored catalog, gateway and Copy Job |
| Silver/Gold | Config-bound notebook builder | Create schema-enabled lakehouses; import/run notebooks |
| Semantic model | Configurable TMSL definition builder and guarded create helper | Active capacity, tenant settings, source connections |
| Reports | PBIR/RDL builders and guarded create helper | Model ID, paginated report ID and Build/Read permissions |
| Private networking | Step-by-step design and acceptance checklist | Network/security team deployment and sign-off |

No command provisions a customer's VNet, changes a firewall, creates credentials
or grants access implicitly. Do not deploy into an existing production workspace.

## 0. Prerequisites and decision gate

- Fabric-enabled tenant and active Fabric capacity in a supported region.
  The reference deployment used **F32**; size the target capacity using measured workloads.
  Power BI user licensing still applies, especially for consumers on capacities
  below F64. Check the current [license guidance](https://learn.microsoft.com/en-us/fabric/enterprise/licenses).
- Workspace Contributor or higher for item creation; administrative permissions
  for capacity assignment, gateway setup and identity approvals as applicable.
- The publication helper also checks capacity state. Its operator needs capacity
  Contributor/Admin access (not just a workspace role); otherwise an authorized
  capacity operator must perform the publication or use the Service workflow.
- Azure Databricks with Unity Catalog, ADLS Gen2-backed tables, a SQL warehouse,
  and the appropriate Fabric integration privileges.
- SQL Server and PostgreSQL instances reachable from the gateway machine.
- An S3 bucket with private access and appropriately scoped Fabric credentials.
- Python 3.12+, dependencies from the root requirements file, Azure CLI, and
  PowerShell 7 for the provided publication/export scripts.
- ODBC Driver 18 + `pyodbc` for SQL loading; `psql` for PostgreSQL loading.
  These source-specific tools are not required by local package validation.

Choose the [public-connectivity architecture](sources.md) or
[private Databricks connectivity](databricks-vnet.md) **before creating resources**.
Schedule network changes through the organization's approved change-control process.

## 1. Clone, validate and configure

Clone the repository. From its root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -B -m unittest discover -s tests -v
python -B tools\validate.py
Copy-Item config\environment.example.json config\environment.local.json
az login --tenant <your-tenant-id>
```

The example deliberately contains invalid placeholders: the builder refuses
them instead of contacting an unintended environment. Never copy an old
deployment response, report ID or connection ID from another environment.

## 2. Create the workspace and lakehouses

In Fabric, create a new workspace such as **Client-Analytics-Dev** and assign it
to your active capacity. Create the following **schema-enabled** lakehouses,
using these names (the transformation notebook verifies target names):

| Lakehouse | Purpose |
|---|---|
| `lh_bronze_channel` | Native Calendar and Channels |
| `lh_bronze_uc` | Three UC shortcuts |
| `lh_bronze_sql_onprem` | SQL ownership copies in schema `ca_demo` |
| `lh_bronze_s3` | S3 Files shortcut and Delta landing |
| `lh_ca_silver` | Cleaned eight-table layer, schema `dbo` |
| `lh_ca_gold` | Serving eight-table layer, schema `dbo`; planning workbook in Files |

Record workspace and lakehouse item GUIDs in
`config/environment.local.json`. Use **lakehouse IDs**, not their SQL analytics
endpoint IDs. The IDs must be distinct for separate layer lakehouses.

REST equivalents, when organizational policy permits:

```text
POST /v1/workspaces
  {"displayName":"Client-Analytics-Dev"}
POST /v1/workspaces/{workspaceId}/assignToCapacity
  {"capacityId":"<capacity-guid>"}
POST /v1/workspaces/{workspaceId}/items
  {"displayName":"lh_ca_gold","type":"Lakehouse",
   "creationPayload":{"enableSchemas":true}}
```

Authenticate for `https://api.fabric.microsoft.com`. APIs may return 202:
record the operation ID, poll `/v1/operations/{id}`, then retrieve `/result`
where applicable. A timeout is not permission to repeat a create.

## 3. Provision and load the source systems

Complete [source configuration](sources.md) in this order:

1. SQL Server: create an empty database; load four source tables.
2. Databricks: configure catalog/volume, load three `ca_uc` tables and the one
   `ca_dq` transaction table; verify SQL warehouse access.
3. PostgreSQL: create an empty database; load opportunities.
4. S3: upload the one account-monthly Parquet to a private bucket prefix.
5. OneLake: upload native reference Parquet and the planning workbook.

Set the SQL/PostgreSQL server and database values and the Databricks hostname,
warehouse HTTP path and catalog in your local config. Schemas/table names are
fixed by the seed contract: `ca_demo`, `ca_uc`, `ca_dq`. Changing them requires
an intentional update to the source/model code, not just a display-name change.

**Do not rerun a loader over existing tables.** If a multi-table load partially
fails, inspect the committed state and choose a new isolated target or an
approved, targeted cleanup. Never drop a whole database to fix an import error.

## 4. Establish the Bronze paths

Follow the precise table/schema names in [the inventory](architecture.md).

- SQL Copy Job: map **only ownership dimension and bridge** to
  `lh_bronze_sql_onprem`, schema `ca_demo`. Preserve the PascalCase source
  columns and numeric types. Use full snapshot replacement for this immutable
  seed; do not append the same seed repeatedly. Preview destructive/truncate
  settings against the two destination tables before saving.
- UC: create a mirrored catalog and shortcuts to the three tables in
  `lh_bronze_uc.dbo`. Check external access and ADLS reachability.
- S3: create a Files shortcut to the prefix and convert the file into
  `lh_bronze_s3.dbo.fact_account_monthly` Delta.
- Reference data: load `dim_date` and `dim_channel` into
  `lh_bronze_channel.dbo`.

Run `SHOW TABLES` and row-count checks in each Bronze lakehouse. A shortcut
showing in Explorer does not prove Spark can read its Delta columns.

## 5. Build and run Silver/Gold

```powershell
python tools\build.py notebooks --config config\environment.local.json
```

Import the two `.generated/*.ipynb` notebooks into **the configured workspace**.
Confirm default lakehouse binding in the UI; do not assume import retained it.

1. Run `nb_ca_bronze_to_silver` with `lh_ca_silver`.
2. Inspect `lh_ca_silver/Files/medallion_runs/silver/latest.json`: require `PASSED`.
3. Run `nb_ca_silver_to_gold` with `lh_ca_gold`.
4. Inspect `lh_ca_gold/Files/medallion_runs/gold/latest.json`: require `PASSED`.

The notebooks validate expected counts, primary keys, internal foreign keys,
ownership allocation, financial reconciliation and run lineage. They refuse
wrong workspace/lakehouse contexts and replacement of unrelated tables. Writes
are not a cross-table transaction: a failed run is not a consumable dataset.

## 6. Create the semantic model

```powershell
python tools\build.py model --config config\environment.local.json
$config = Get-Content config\environment.local.json -Raw | ConvertFrom-Json
pwsh tools\publish_item.ps1 -Collection semanticModels `
  -WorkspaceId $config.workspace_id -RequestPath .generated\model\create.json `
  -ResultPath .generated\model-created.json
# Review the plan, then repeat the same command with -Apply.
```

Record the returned model ID as `semantic_model_id` in the local configuration.
This helper is for **new items only** and refuses name collisions. For an existing
model, use getDefinition/backup/diff/updateDefinition as described in the
[model guide](semantic-model.md); never replace a customized model blindly.

## 7. Bind and validate the sources

Open **sm_client_analytics > Settings > Gateway and cloud connections**.
Create and map each source as specified in [connection bindings](semantic-model.md#connection-bindings).
Supply OAuth/Windows/Basic credentials through the Service UI, not source code.

Run a full refresh; stop on credential errors. Then run the acceptance queries
in [validation](validation.md). A model refresh does not prove DirectQuery
tables work: query Transactions, Clients and Advisors separately.

## 8. Create paginated, then interactive reports

```powershell
python tools\build.py paginated --config config\environment.local.json
pwsh tools\publish_item.ps1 -Collection paginatedReports `
  -WorkspaceId $config.workspace_id -RequestPath .generated\paginated.create.json `
  -ResultPath .generated\paginated-created.json -Apply
```

Record its ID as `paginated_report_id`; then build the interactive report so the
Advisor Pack button points to the correct report:

```powershell
python tools\build.py interactive --config config\environment.local.json
pwsh tools\publish_item.ps1 -Collection reports `
  -WorkspaceId $config.workspace_id -RequestPath .generated\interactive.create.json `
  -ResultPath .generated\interactive-created.json -Apply
```

**Paginated API compatibility:** the validated environment rejected the explicit
`PaginatedReportDefinition` format. This package omits it for the default format.
If a create is still rejected, import the generated `.rdl` through the Power BI
Service upload experience, or open it in Report Builder and publish to the same
workspace. Verify whether an item exists before trying another method. Record
the actual resulting report ID; do not create duplicates.

## 9. Acceptance and handover

- Check all 14 model row counts and financial controls.
- Reset report filters; validate October 2026 / Plan target cards.
- Exercise cross-filtering, highlighting, drill-down, drill-through and bookmarks
  using an intended **Viewer**, not only an administrator.
- Export paginated PDF with default parameters and CSV with alternate parameters.
- Configure and test RLS membership, subscriptions and embedding only after
  security/recipient approval. They are not created by the deployment helper.
- Record region, capacity, gateway availability, owners, cost controls and
  restore/cleanup responsibilities in your internal deployment record.

For decommissioning, remove only approved solution item/resource IDs. Check dependencies
first. Do not delete shared gateways, capacities, VNets, catalog storage,
authentication workspaces or databases.
