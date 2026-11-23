# Source configuration

[Home](../README.md) | [Deployment](deployment.md) | [Inventory](architecture.md)

Use the supplied data unchanged for the documented count/financial acceptance
checks. All source loaders are first-load tools, not scheduled refresh jobs.

## SQL Server

**Reference configuration:** a local named instance, Windows authentication and a
standard on-premises gateway on the same machine. The private instance name and
credentials are intentionally not distributed. Use your own host/instance.

1. Create a new empty database named `ClientAnalytics` (or configure another
   database name).
2. Install Microsoft ODBC Driver 18 and `python -m pip install pyodbc` in the
   loader environment.
3. Set `RBCCA_SQL_CONNECTION_STRING` using your approved local secret mechanism.
   A Windows-authenticated example, containing no password:

   ```powershell
   $env:RBCCA_SQL_CONNECTION_STRING = 'Driver={ODBC Driver 18 for SQL Server};Server=<host\instance>;Database=ClientAnalytics;Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=no'
   python data\sql_onprem\load_sqlserver.py
   Remove-Item Env:\RBCCA_SQL_CONNECTION_STRING
   ```

4. The loader creates `ca_demo` and four new tables, inserts all rows, validates
   counts, creates the local bridge-to-owner foreign key, and commits together.
5. Grant the gateway identity **SELECT only** on the required source tables.
   Use a different identity for schema creation/loading.

| Table | Rows | Consumption |
|---|---:|---|
| `dim_client` | 11,000 | Semantic DirectQuery |
| `dim_advisor` | 100 | Semantic DirectQuery |
| `dim_account_owner` | 10,000 | Copy to Bronze |
| `bridge_account_owner` | 24,000 | Copy to Bronze |

Configure a **SQL Server** gateway connection matching server and database
exactly. `localhost` only works when SQL and the gateway are on the same host;
it is not a remote/cloud hostname. For an Azure SQL replacement, use the proper
cloud connection/network route rather than assuming the on-premises mapping.

Use a trusted server certificate with matching names for deployed environments.
The local reference environment used a certificate-trust exception; that
exception is not included in the deployment defaults.

## Azure Databricks: two separate paths

### A. Create the source data

1. Provision an Azure Databricks workspace with Unity Catalog and an approved
   ADLS Gen2 managed storage location/access connector.
2. Create an isolated catalog (example `ca_catalog`), schemas `ca_uc`, `ca_dq`
   and a landing schema/volume. Bind an isolated catalog to the intended
   workspace. Catalog creation, storage credentials and workspace binding are
   administrator actions, not performed by the loaders.
3. Upload the complete `data/databricks_uc` directory and
   `data/databricks_dq/fact_transaction.parquet` into a UC volume.
4. Import the supplied Python files as Databricks notebooks and set widgets:

| Loader | Widget | Value |
|---|---|---|
| `data/databricks_uc/load_uc_tables.py` | `catalog` | Your catalog |
| | `schema` | `ca_uc` |
| | `source_folder` | `/Volumes/<catalog>/<landing-schema>/<volume>/databricks_uc` |
| | `external_base_location` | Blank for managed tables; otherwise approved unused ABFSS location |
| `data/databricks_dq/load_databricks.py` | `catalog` | Your catalog |
| | `schema` | `ca_dq` |
| | `source_file` | `/Volumes/<catalog>/<landing-schema>/<volume>/databricks_dq/fact_transaction.parquet` |
| | `external_table_location` | Blank for managed tables |

Run once on compatible Databricks compute. Loaders validate schema, count and
keys, and refuse existing destination tables. The UC loader also compares
persisted values. It uses Spark Connect-compatible fail-if-exists mode `error`.

### B. DirectQuery Transactions

1. Create/start a SQL warehouse. The reference deployment used a **serverless SQL
   warehouse**; it was not classic compute inside a customer-injected VNet.
2. From warehouse **Connection details**, copy the server hostname and HTTP path.
3. Give the connection identity warehouse **CAN USE**, `USE CATALOG`,
   `USE SCHEMA` on `ca_dq`, and `SELECT` on `fact_transaction`.
4. In Fabric **Manage connections and gateways**, create an **Azure Databricks**
   connection for the **hostname + warehouse HTTP path**. Authenticate using
   an approved Entra/OAuth or service identity method.
5. Map the semantic model's Databricks source to it.

Validate in the warehouse:

```sql
SELECT COUNT(*) AS rows,
       SUM(SignedAmountCAD) AS net_contributions,
       SUM(FeeCAD) AS fees
FROM ca_catalog.ca_dq.fact_transaction;
```

Expected: **1,000,000**, **-1,438,757.40**, **500,220.78**.

### C. Mirrored catalog and UC shortcuts

This is a different connector: **Azure Databricks workspace**, using the
workspace URL, not a SQL warehouse HTTP path.

1. Enable external data access on the Unity Catalog metastore as documented.
2. Approve the integration identity's required permissions, including
   `EXTERNAL USE SCHEMA`, and source table access.
3. Create a Mirrored Azure Databricks Catalog item in Fabric; select only
   `ca_uc.dim_account`, `ca_uc.dim_product`, `ca_uc.fact_interaction`.
4. Expose these tables in `lh_bronze_uc`, schema `dbo`, using OneLake shortcuts.
5. Verify Spark can read the table contents, not only browse catalog names.

**Governance boundary:** the integration accesses data with the configuring
identity and vended credentials. Do not claim that each Fabric viewer inherits
the source UC user's row/column policies. Review Fabric/OneLake and semantic
security explicitly. Views and tables with RLS/CLM policies are listed as
unsupported in the current mirror limitations.

For private endpoints, follow the **mirrored-catalog** branch of the
[VNet guide](databricks-vnet.md), not only the SQL DirectQuery branch.

## PostgreSQL

1. Provision an accessible PostgreSQL instance and create a fresh
   `client_analytics` database.
2. Run from the supplied loader directory so the `\cd data` command resolves:

   ```powershell
   Push-Location data\postgres
   psql -h <postgres-host> -p 5432 -U <loader-user> -d client_analytics -W -f load_postgres.psql
   Pop-Location
   ```

3. Require a successful commit and `SELECT count(*) FROM
   ca_demo.fact_opportunity` = **15,000**.
4. Create a PostgreSQL source connection accessible from the gateway, with a
   separate read-only account for model refresh. Match `host:port` and database.
5. Use TLS with trusted certificates in customer environments.

The reference configuration used an unencrypted loopback connection and a
manually started PostgreSQL process. Operational deployments require a managed
service lifecycle, recovery, TLS and monitoring.
If a connection is actively refused, check the listener and gateway route before
changing a password. Do not run the data loader as a server-restart remedy.

## Excel planning

Use [the supplied workbook](../data/excel/Client_Analytics_Planning.xlsx):

- `dim_campaign`: 13 rows, including Campaign Key 0 ("no campaign").
- `fact_target`: 54,400 rows, month/advisor/product/scenario grain.
- Scenarios: **Plan** and **Stretch**.

Upload it as:
`lh_ca_gold/Files/planning/Client_Analytics_Planning.xlsx`.
Keep the named tables and column names intact. Avoid placing duplicate matching
workbooks in that folder: the M query requires exactly one.

The model imports the workbook through a OneLake/ADLS Gen2 cloud connection using
Organizational account OAuth. A SharePoint/OneDrive-hosted variant is possible
but is **not this repository's implemented M path**; update the connector,
credentials, binding and tests if you choose it.

## Amazon S3 and native OneLake references

### S3

1. Keep the bucket private and enable Block Public Access.
2. Upload `data/s3/fact_account_monthly.parquet` to
   `client-analytics/account-monthly/`.
3. Create an Amazon S3 shortcut under
   `lh_bronze_s3/Files/s3/account-monthly` using scoped credentials managed in
   Fabric. Grant only required list/read access to that prefix.
4. With `lh_bronze_s3` as the default lakehouse, run:

   ```python
   source = spark.read.parquet("Files/s3/account-monthly/fact_account_monthly.parquet")
   assert source.count() == 680000
   source.write.format("delta").mode("error").saveAsTable("dbo.fact_account_monthly")
   ```

The Files shortcut points to standalone Parquet, not a Delta table. This explicit
conversion is required before the downstream Delta-reading notebook.

### Calendar and Channels

Upload `data/onelake_reference/*.parquet` to
`lh_bronze_channel/Files/reference`. With that lakehouse attached:

```python
for name in ("dim_date", "dim_channel"):
    frame = spark.read.parquet(f"Files/reference/{name}.parquet")
    frame.write.format("delta").mode("error").saveAsTable(f"dbo.{name}")
```

These are native reference data, not additional external source integrations.

## Optional regeneration

`notebooks/generate_client_analytics.py` contains the original deterministic
PySpark generator. It creates a **separate seed/staging** lakehouse's `gold` and
`ops` schemas and emits source extracts. It is not the final eight-table serving
layer. To reproduce the documented exact financial baselines, prefer the checked
seed files: hash behavior/runtime changes can change regenerated synthetic values.
A new scale/seed requires new acceptance baselines and workbook packaging.

**Official references:** [Azure Databricks connector](https://learn.microsoft.com/en-us/power-query/connectors/databricks-azure),
[Fabric/UC sharing](https://learn.microsoft.com/en-us/azure/databricks/partners/bi/fabric-mirror),
[mirror limitations](https://learn.microsoft.com/en-us/fabric/mirroring/azure-databricks-limitations),
[S3 shortcuts](https://learn.microsoft.com/en-us/fabric/onelake/create-s3-shortcut).
