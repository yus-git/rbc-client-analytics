# Analytical workflows and solution capabilities

[Home](../README.md) | [Architecture](architecture.md) | [Validation](validation.md)

## Solution overview

Client Analytics brings five business processes into one governed semantic
model: account performance, transactions, interactions, opportunities and
planning targets. Shared dimensions and measures provide consistent analysis
across external systems, curated OneLake data and imported operational snapshots.

| Analytical area | Report experience | Data and semantic considerations |
|---|---|---|
| Executive performance | AUM, revenue and regional comparisons | Latest-snapshot balances and additive financial measures |
| Client activity | Client filtering and detail drill-through | External transaction queries and explicit date roles |
| Advisor performance | Actual-versus-target comparison | SQL advisor dimensions, Gold actuals and Excel planning data |
| Pipeline and campaigns | Opportunity and interaction analysis | Imported opportunity snapshots and campaign attribution |
| Distributed reporting | Parameterized advisor pack | Complete detail, repeated headers and controlled exports |

## Analytical workflows

### Actuals versus plan

On Advisor Performance, select **2026-10** and **Plan**. The validated reference
dataset returns:

- Revenue: **CAD 5,291,993.74**
- Target: **CAD 12,961,660.00**
- Attainment: **40.8%**, using the report's one-decimal display precision

Actual revenue comes from curated Gold Delta tables, targets from the planning
workbook and advisor slicing from SQL Server DirectQuery. The semantic model
applies the shared relationships and measure definitions.

### Client activity and transactions

Select a client and drill through to Client Detail. The booking-date and
settlement-date measures apply distinct date relationships. Client-level counts
must reflect the selected client; the unfiltered transaction table contains one
million records.

### Ownership and client history

Historical Clients uses SCD2 version keys, while Account Owners captures current
ownership. Allocated AUM applies ownership weights. Owner-linked assets are
non-additive across joint owners and must not be summed without allocation.

### Parameterized distribution

The paginated report supports Month, Region and Scenario parameters.
October 2026 / All / Plan produced **800 advisor/product detail rows across
45 PDF pages**. September 2026 / Ontario / Stretch produced **160 CSV rows**.
These are reference validation results, not a service availability guarantee.

## Capability and validation matrix

**Verified:** exercised in the reference Service deployment.
**Authored:** included in model/report metadata; requires user-interface acceptance.
**Configuration guidance:** documented but not provisioned by this package.
**Optional extension:** outside the implemented source/model paths.

| Capability | Status | Implementation and acceptance considerations |
|---|---|---|
| Databricks connectivity | Verified | Transaction warehouse DirectQuery and UC-backed Gold route |
| PostgreSQL | Verified at validation time | Opportunities Import; validate current server/gateway availability |
| SQL Server | Verified at validation time | Clients/Advisors DirectQuery and ownership ingestion |
| Excel planning | Verified | Campaigns and Targets from the workbook in Gold Files |
| S3 and lakehouse data | Verified | Parquet -> Delta -> Silver -> Gold |
| Snowflake shortcuts | Optional extension | Requires a separately configured supported integration |
| Composite model | Verified | Eight Direct Lake, three DirectQuery and three Import tables |
| Multiple date relationships | Verified metadata and selected queries | Booking/settlement and created/close roles |
| Cross-filtering | Authored | Verify selected region/product filters the intended visuals |
| Cross-highlighting | Authored | Verify supported charts retain the comparison context |
| Drill-down | Authored | Navigate configured hierarchy levels |
| Drill-through | Authored | Verify selected-client context and Back navigation |
| Filters and slicers | Verified rendering | Month/scenario defaults; test multi-selection and reset |
| Buttons, page navigation and external URLs | Authored | Validate reading-mode behavior and approved destinations |
| Author bookmarks | Authored | Two report bookmarks; verify display and data state |
| Personal saved views | Configuration guidance | User-specific Service bookmarks, separate from author bookmarks |
| Paginated reporting | Verified | Default PDF and alternate-parameter CSV |
| PDF export | Verified | Interactive rendering and 45-page paginated pack |
| Excel export | Acceptance pending | Validate spreadsheet layout separately from PDF pagination |
| CSV export | Verified for paginated output | Flat detail without presentation formatting |
| Automatic detail pagination | Verified in RDL | Interactive page export does not include offscreen scrolling rows |
| Email subscriptions | Configuration guidance | Recipient, schedule, licensing and security approval required |
| Image output | Tenant-dependent | PNG API export was policy-disabled in the validated environment |
| Activator and Power BI alerts | Configuration guidance | No active notification rules or recipients configured |
| Secure embedding and ClientFirst SSO | Configuration guidance | Host application and end-to-end SSO require implementation |
| Business-user report authoring | Configuration guidance | Build permission on governed models and thin reports |
| Agent-assisted artifact creation | Implemented | Model, M/DAX and PBIR/RDL builders with validation gates |
| Workspace folders and groups | Configuration guidance | Folder organization does not create a security boundary |
| Version control and deployment pipelines | Repository and guidance | Local validation and CI workflow included; cloud promotion not configured |
| BMC Control-M integration | Configuration guidance | REST orchestration pattern; scheduler jobs require implementation |
| APIs, skills and MCP | Builders and guidance | Authentication, permissions and endpoint support remain prerequisites |
| Scale and concurrency | Acceptance pending | Synthetic dataset size is not a production performance benchmark |
| Tableau and SSRS migration | Assessment guidance | Requires representative report conversion and reconciliation |

## Governed self-service

1. Publish an endorsed semantic model with clear measure descriptions.
2. Grant the business-author group **Build** on the model without unnecessary
   source credentials or production workspace editing rights.
3. Create thin reports against the shared model.
4. Reuse governed measures such as `Revenue` and `Revenue Target`.
5. Apply ownership, RLS, endorsement and lifecycle standards consistently.
6. Promote reports through an approved review process.

## Controlled agent-assisted authoring

Source contracts and explicit builder inputs constrain generated artifacts.
Schema checks, relationship validation, numeric reconciliation and rendered
report acceptance remain required before deployment. Agents do not assign
entitlements or establish source credentials.

Example authoring specification:

> Add an advisor performance page using the existing Revenue and Revenue Target
> measures. Default to October 2026 and Plan. Preserve storage modes,
> relationships and model identity. Provide a reviewed definition diff and
> regression validation before deployment.

Apply the same change-control process to agent-generated and manually authored
changes. API success alone does not establish analytical correctness.

## Migration and source extensions

### Tableau

Inventory workbooks, published sources, LOD expressions, table calculations,
filters/actions, entitlements and extracts. Map business semantics into the
shared model before rebuilding visuals. Evaluate representative complexity;
this repository does not establish lossless automated conversion.

### SSRS

Assess RDL data-source compatibility, custom code/assemblies, authentication,
rendering and subscription behavior. Reconcile source and migrated reports
side-by-side in PDF and Excel.

### Migration accelerator assessment

Evaluate simple, medium and complex reports. Record conversion effort,
unsupported features, numeric differences, rendering fidelity, security and
performance. Use measured outcomes to determine suitability.

### Snowflake

Select a connector or shortcut route against current supported table/storage
formats, network configuration and authentication. Generic Snowflake SQL tables
are not automatically OneLake shortcuts. Extend the data contract, security
assessment and acceptance tests before incorporating an additional source.

## Operational readiness checklist

- Capacity, source warehouse and gateways are available.
- PostgreSQL is running and all connection credentials are valid.
- Latest Gold run is PASSED and semantic refresh has completed.
- Transaction and target validation queries pass.
- Required report defaults and filter behavior are verified.
- Report access and sign-in work for the intended audience.
- Export behavior and delivery policies have been validated.
- Secrets and real customer data are excluded from the reference artifacts.
