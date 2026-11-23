# Operations, governance and automation

[Home](../README.md) | [Validation](validation.md) | [Solution guide](solution-guide.md)

## Refresh is a dependency graph, not one button

```text
Source extracts / SQL ownership Copy Job / source Delta updates
    -> Bronze read validation
    -> Silver notebook PASSED
    -> Gold notebook PASSED
    -> Semantic model refresh / Direct Lake framing + Import refresh
    -> DirectQuery smoke queries
    -> Report export or subscription delivery
```

DirectQuery tables are queried at report time and are not populated by the
Import refresh. Databricks SQL warehouse startup and SQL gateway liveness still
matter after a successful model refresh. Query caches can affect visible latency.

The fixed seed loaders are not recurring ETL jobs. For production, implement
incremental source extraction, replay/idempotency, watermarks, deletions and
schema-evolution contracts explicitly.

### Source liveness

- Run the on-premises gateway on managed, always-on infrastructure with recovery
  and maintenance ownership; do not depend on an interactive user session.
- Install PostgreSQL as a managed service or use an approved managed database.
  A previously successful connectivity check is not a current health guarantee.
- Monitor warehouse auto-stop/start latency, concurrency and spend.
- Monitor OAuth/identity expiry, gateway updates, source certificates and DNS.
- Alert on failed notebook quality gates; do not refresh/export partial Gold data.

## Tenant, capacity, workspace and folders

| Fabric/Power BI concept | Practical meaning | Tableau comparison (approximate) |
|---|---|---|
| Entra/Fabric tenant | Organization-wide identity and policy boundary | Not a one-to-one mapping to a Tableau site |
| Capacity | Shared compute/memory budget and workload isolation | Not a Tableau project; infrastructure/capacity concern |
| Workspace | Collaboration, roles, item lifecycle and deployment unit | Closest to a governed project/work area, with different permission semantics |
| Workspace folder | Organization/navigation | Not a separate permission/security boundary |
| Semantic model | Shared measures, relationships and governance | Published shared analytical data asset, not merely a connection string |
| Power BI app | Curated distribution to audiences | Consumer-facing content distribution |

Recommended folders: `01 Sources`, `02 Engineering`, `03 Semantic Models`,
`04 Reports`, `05 Operations`. Folder names are illustrative, not an automated
security design. Use separate Dev/Test/Prod workspaces for lifecycle isolation.

## Groups and least privilege

| Group | Suggested workspace/app role | Other access |
|---|---|---|
| Platform admins | Small Admin group | Capacity/gateway/network administration separately governed |
| Data engineers | Contributor in engineering workspace | Source read/write only as needed |
| BI developers | Contributor in development workspace | Build on shared model; reviewed deployment privileges |
| Business authors | Prefer Build on approved shared models | No unnecessary source credentials or production workspace edit rights |
| Consumers | App audience / Viewer | Read and appropriate RLS membership |

Use Entra groups rather than individually maintained user assignments.
Separate source reader, source loader and deployment identities. Apply sensitivity
labels, endorsement/certification, audit logging, ownership and retention. Review
how Build/export permissions interact with your data-protection requirements.

The illustrative RLS role is not a complete identity-to-advisor solution.
Design dynamic entitlements, test permitted/denied cases, and validate export
and embedded effective identity behavior before production.

## Version control and deployment pipelines

Git contains **code, schema, synthetic seed and parameter templates**, not live
credentials or environment-specific item definitions. PBIR/RDL/model.bim are
generated into a gitignored directory for each environment.

Recommended process:

1. Pull request with unit/data checks and documented semantic changes.
2. Deploy to Development with environment-specific configuration.
3. Verify measures, RLS, model modes, report interactions and export fidelity.
4. Promote supported Fabric/Power BI items through deployment pipelines.
5. Apply target rules/parameters and bind target connections; verify credentials,
   model/report dependencies and gateway mapping in every stage.
6. Approve Production promotion with a backup and rollback plan.

Git integration and deployment pipelines are complementary, not automatic backup
of source data, connection credentials, subscriptions or external infrastructure.
Support varies by item type: check current limitations for notebooks, semantic
models, reports, paginated reports, shortcuts and mirrored items rather than
assuming everything is promoted. Delta history is data history, not Git history.

The included GitHub workflow validates locally; it does **not** deploy to Fabric
or need cloud secrets.

## BMC Control-M integration pattern

The request refers to "BCM Control-M"; the scheduler is **BMC Control-M**.
Use its approved REST/HTTP job capability or a managed script job. This repository
provides an integration pattern, not a configured Control-M server or job export.

| Step | API/action | Success gate |
|---|---|---|
| Extract | Existing enterprise extract or Fabric orchestration | Source watermark/counts |
| Transform | Fabric pipeline/notebook job | Recorded job instance reaches Completed; quality markers PASSED |
| Refresh | Power BI semantic-model refresh | Refresh request/ID reaches Completed |
| Validate | DAX query / controlled XMLA test | Expected count/financial thresholds |
| Deliver | ExportToFile / approved subscription | Export job succeeds and approved recipients receive output |

Relevant endpoints:

```text
POST https://api.fabric.microsoft.com/v1/workspaces/{workspace}/items/{item}/jobs/instances?jobType={supportedJobType}
GET  https://api.fabric.microsoft.com/v1/workspaces/{workspace}/items/{item}/jobs/instances/{jobId}
POST https://api.powerbi.com/v1.0/myorg/groups/{workspace}/datasets/{model}/refreshes
GET  https://api.powerbi.com/v1.0/myorg/groups/{workspace}/datasets/{model}/refreshes
POST https://api.powerbi.com/v1.0/myorg/groups/{workspace}/reports/{report}/ExportTo
GET  https://api.powerbi.com/v1.0/myorg/groups/{workspace}/reports/{report}/exports/{exportId}
GET  https://api.powerbi.com/v1.0/myorg/groups/{workspace}/reports/{report}/exports/{exportId}/file
```

Determine the supported job type for each Fabric item rather than substituting
one string for all notebooks/pipelines. Before submitting, check for a recent
running job. Persist correlation/request IDs, respect Retry-After, poll with
bounded timeouts, and never blindly retry POST after an ambiguous timeout.
Power BI refresh and Fabric job status terms are different; normalize them in
the scheduler, not by treating any HTTP 202 as completion.

Tokens have different audiences:

- Fabric: `https://api.fabric.microsoft.com`
- Power BI: `https://analysis.windows.net/powerbi/api`
- OneLake: `https://storage.azure.com/`

For unattended operation, use an approved workload identity/secret store and
tenant settings appropriate to each API. Service-principal support and RLS/SSO
restrictions vary; do not assume an interactive Azure CLI login is production
scheduler authentication.

## Exports, subscriptions and alerts

- **Interactive report:** PDF/PowerPoint export captures pages, not every offscreen
  row in a scrolling visual. CSV/Excel export is a visual/data export, governed by
  tenant and report permissions; it is not a full report ExportToFile format.
- **Paginated:** PDF for fixed pages; XLSX for spreadsheet consumption; CSV for
  flat unformatted data. Excel does not preserve PDF page geometry exactly.
- **Subscriptions:** configure recipients, schedule, security and attachments
  through supported Service/Power Automate options. Validate licensing and
  output-size limits. No customer recipients were provisioned by this package.
- **Activator:** a separate event/rule/action item; not automatically created by
  a model measure. Approve thresholds, destination and capacity cost.
- **Power BI alerts:** classic dashboard tile alerts have visual/type limitations;
  do not promise an alert on every report visual.
- No generic "send subscription" REST endpoint is assumed. Use a supported
  delivery mechanism and verify its auth/licensing contract.

PNG/image export was disabled by policy in the validated environment.
PDF and paginated CSV were verified; XLSX remains an explicit acceptance test.

Example paginated export after deployment:

```powershell
pwsh tools\export_report.ps1 -WorkspaceId <workspace-guid> `
  -ReportId <paginated-report-guid> -Format PDF -ReportType Paginated `
  -OutputBase .generated\exports\advisor-pack-001
```

Use a new OutputBase for a deliberate new request; inspect the recorded request
when a previous export is pending. The script does not email the result.

## Embedding and SSO

**Never use Publish to web for client analytics.**

For an internal ClientFirst-style host:

- Start with **embed for your organization** / secure embed.
- Users authenticate with Entra and need appropriate report/model permissions and
  licenses. Embedding in an iframe does not grant access or suppress MFA.
- For a custom seamless host, use the Power BI JavaScript SDK with approved Entra
  app registration, redirect URLs, delegated token acquisition and renewal,
  embedding domain/CSP policy, browser-cookie testing and RLS tests.
- For external/app-owns-data embedding, design a server-side token service,
  effective identities, capacity and tenant settings separately. Never put client
  secrets or an unrestricted embed-token minting endpoint in the browser.

This reference implementation includes embedding guidance. A ClientFirst host
application and end-to-end SSO integration require separate implementation
and acceptance testing.

## Large data: decide using measured workloads

| Mode | Good fit | Scale constraints to measure |
|---|---|---|
| Direct Lake | Curated Delta/OneLake data with suitable capacity | Resident-column memory, framing, file/row-group layout, SKU guardrails and concurrency |
| DirectQuery | Source-governed/fresh queries where copying is undesirable | Source scan cost, network latency, query folding, gateway/warehouse concurrency, intermediate result limits |
| Import | Fast in-memory analytics with acceptable refresh latency | Compressed model size, high-cardinality columns, refresh memory/time, SKU limits |

DirectQuery does not have a simple "maximum source-table rows" equal to its
intermediate-result limit. The often-cited default one-million intermediate-row
limit is a query-result constraint, not a ban on querying a million-row table.
Premium capacity can configure certain limits, but not remove source latency.

Avoid fixed universal GB promises: published upload limits, large-model storage
and resident/query memory are different. Evaluate current SKU limits, incremental
refresh, partitioning, source aggregations, column pruning, file optimization and
representative concurrent users. Cross-source DQ joins can dominate latency.

## Validated troubleshooting procedures

| Error | Verified remedy / diagnostic |
|---|---|
| Direct Lake requires SQL/OneLake source | Restore a correctly recognized OneLake expression and entity partition; preserve mode |
| PostgreSQL actively refused | Check process listener, correct host:port and gateway route; `localhost` needs a same-host gateway |
| Databricks catalog key not found, empty navigation | Null Catalog/Database options then explicit navigation; separately verify warehouse/table grants |
| Targets blank | Select exactly one scenario; ensure default slicer filter uses the PBIR wrapper |
| Premium_ASWL / no Excel Import credentials | Explicit OneLake cloud connection and successful refresh |
| Paginated undeclared parameter | RDL QueryParameter `Month`, DAX `@Month` |
| Paginated InvalidDefinitionFormat | Omit explicit format; use RDL upload fallback for create after checking no item was created |
| Report missing theme resource | Match theme reference to the actual resource part path |

**References:** [DirectQuery guidance](https://learn.microsoft.com/en-us/power-bi/connect-data/desktop-directquery-about),
[deployment pipelines](https://learn.microsoft.com/en-us/fabric/cicd/deployment-pipelines/intro-to-deployment-pipelines),
[Git integration](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/intro-to-git-integration),
[ExportToFile](https://learn.microsoft.com/en-us/power-bi/developer/embedded/export-to),
[secure embed](https://learn.microsoft.com/en-us/power-bi/collaborate-share/service-embed-secure),
[subscriptions](https://learn.microsoft.com/en-us/power-bi/collaborate-share/end-user-subscribe).
