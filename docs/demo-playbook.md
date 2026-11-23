# Customer demonstration playbook

[Home](../README.md) | [Architecture](architecture.md) | [Validation](validation.md)

## Opening message

> "This is one governed semantic model over five business processes: monthly
> account performance, transactions, interactions, opportunities and targets.
> Some data stays in external systems, some is curated in OneLake, and smaller
> datasets are imported. The business user sees consistent measures and filters,
> not separate reports for each database."

Do not start by explaining every line in the model diagram. Begin with a business
question, show an answer, then trace the relevant data path.

## Suggested 30-minute flow

| Time | Show | Explain |
|---|---|---|
| 0-3 min | Architecture diagram | Three access paths, one model; synthetic data only |
| 3-8 min | Executive overview | Latest-snapshot AUM, revenue and regional comparisons |
| 8-13 min | Client explorer / drill-through | Filter context; transaction detail from Databricks DQ |
| 13-18 min | Advisor performance | SQL Advisors + Gold actuals + Excel targets; October 2026 / Plan |
| 18-22 min | Paginated advisor pack | Same model, parameterized detail, real page breaks and repeat headers |
| 22-26 min | Model/storage modes and lineage | Show the three partition types and intentional date roles |
| 26-30 min | Governance / delivery discussion | Access, lifecycle, private connectivity and next-step acceptance |

## Concrete business stories

### 1. Actuals versus plan

Set **2026-10** and **Plan** on Advisor performance:

- Revenue: **CAD 5,291,993.74**
- Target: **CAD 12,961,660.00**
- Attainment: **40.8%** at the report's one-decimal display precision

Explain: actual revenue comes from curated Gold Delta, targets from the Excel
workbook, advisor slicing from SQL Server DirectQuery. No manual Excel join is
needed each time an analyst builds a visual.

### 2. Client activity and transactions

Choose a client in the explorer and drill through to Client Detail. Explain
booking date versus settlement date using the corresponding measures. Clear the
context before returning to population-level counts: the unfiltered source has
one million transactions; a drilled client should not show that global count.

### 3. Ownership versus economic-client history

Use owner-linked and allocated AUM to explain joint accounts. Historical Clients
is SCD2, while Account Owners expresses current ownership. Allocated AUM divides
assets by weights; linked AUM cannot be summed across owners without duplication.

### 4. From interactive analysis to a distributed pack

Open the paginated report, select October 2026 / All / Plan, and export PDF.
Scroll through the final page: **45 pages and 800 advisor/product detail rows**
were verified in the original deployment. Change to September 2026 / Ontario /
Stretch and export CSV: expected **160 rows**.

## Feature matrix: be explicit about evidence

**Verified** = executed in the original Service deployment.
**Authored** = generated into report/model metadata but needs UI/user acceptance.
**Guide** = documented platform configuration, not enabled by this package.
**Optional** = not part of the implemented source/model path.

| Requested capability | Status | Demonstration / caveat |
|---|---|---|
| Databricks connectivity | Verified | Transactions warehouse DQ; UC-backed Gold route |
| PostgreSQL | Verified historically | Opportunities Import; recheck server/gateway liveness |
| SQL Server | Verified historically | Clients/Advisors DQ; ownership ingestion |
| Excel / CA planning | Verified | Campaigns and Targets in Gold Files workbook |
| S3 / lakehouse data | Verified | Snapshot Parquet -> Delta -> Silver -> Gold |
| Snowflake shortcuts | Optional | Not configured; see extension note below |
| Composite model / DL/DQ/Import | Verified | 8/3/3 partitions in one model |
| Multiple date relationships / DAX | Verified metadata + selected queries | Booking/settlement and created/close roles |
| Cross-filtering | Authored | Click region/product; validate intended visuals update |
| Cross-highlighting | Authored | Compare highlighted contribution to unselected total; verify supported chart behavior |
| Drill-down | Authored | Use a configured hierarchy's down/up controls |
| Drill-through | Authored | Right-click selected client, inspect Client Detail context, Back |
| Filters and slicers | Verified rendering | Month/scenario defaults; test multi-selection and reset |
| Buttons / page navigation / external URLs | Authored | Test in reading mode; keep external URLs approved |
| Author bookmarks | Authored | Two report bookmarks; verify display/data state |
| Personal saved views | Guide | Service personal bookmarks are per-user; not the same as author bookmarks |
| Paginated report | Verified | Default PDF + alternate CSV |
| Export PDF | Verified | Interactive rendering and 45-page paginated pack |
| Export Excel | Guide / acceptance pending | Paginated XLSX and visual export; Excel is not pixel-identical PDF |
| Export CSV | Verified paginated | Alternate parameter case; no formatting preserved |
| Automatic pagination of scrollable content | Verified for RDL detail | Not supported by interactive-page screenshot export |
| Email subscriptions / PDF attachments | Guide | Recipient, schedule, licensing and security approval required |
| Image subscriptions / PNG output | Tenant-dependent | Original tenant disabled PNG API export |
| Activator / Power BI alerts | Guide | No live rule/notification recipients configured |
| iframe / ClientFirst seamless SSO | Guide | No host app or end-to-end SSO deployed |
| Business-user report authoring | Guide | Give Build on certified model; create a thin report without source credentials |
| Agentic creation | Demonstrated artifact creation | Builders generated model, M/DAX and PBIR/RDL; not a claim every Copilot feature is enabled |
| Workspace folders / groups | Guide | Folders organize; permissions need explicit group assignment |
| Git / deployment pipelines | Local Git + guide | CI validates; cloud promotion not configured |
| Control-M integration | Guide | REST orchestration pattern, not a deployed Control-M job |
| API / skills / MCP | Builder/API workflow + guide | Auth, tenant policies and endpoint capabilities still apply |
| Scale / concurrency | Acceptance pending | Seed size is not a production performance benchmark |
| Tableau / SSRS migration | Guide | No universal automated converter or complex-report benchmark claimed |

## Self-service without sharing source passwords

1. Publish a governed/certified semantic model with clear measure descriptions.
2. Grant a business-author group **Build** on the model, not broad source-system
   access or production workspace editing.
3. Create a new thin Power BI report against that model.
4. Add `Revenue`, `Revenue Target`, Month, Advisor and Product.
5. Explain governed measure reuse, data ownership, RLS and endorsement.
6. Promote well-used reports through an agreed review process.

## Agentic creation: show the controlled process

Show the source contract, builder inputs and generated artifacts:

> "The agent writes a proposed definition. We validate schema, keys, relationship
> behavior, numeric results and actual report output. It does not invent source
> credentials or decide customer access."

An example safe authoring prompt:

> "Add an advisor performance page using existing Revenue and Revenue Target
> measures. Default to October 2026 and Plan. Preserve storage modes,
> relationships and model identity. Generate a reviewed definition diff and a
> regression test before deployment."

Do not run unreviewed prompts against Production during the customer meeting.
MCP/skills automate approved APIs; they do not bypass permissions or validate
correctness merely by returning success.

## Tableau, SSRS and optional Snowflake extensions

**Tableau:** inventory workbooks, published sources, calculations/LOD expressions,
table calculations, filters/actions, entitlements and extracts. Map business
semantics to a shared model before rebuilding visuals. Benchmark representative
complexity; there is no evidence here of a lossless one-click conversion.

**SSRS:** RDL is a useful starting point, but evaluate unsupported data sources,
custom code/assemblies, authentication, rendering and subscription behavior.
Test the original report and migrated RDL side-by-side in PDF and Excel.

**Migration accelerator evaluation:** choose one simple, one medium and one
complex report; record conversion effort, unsupported features, visual/pixel
differences, numeric reconciliation, RLS and performance. Record results rather
than assigning unsupported success rates.

**Tableau vs Power BI video:** use a current official/vendor-approved video
selected for the customer's licensing/version context. No unverified YouTube
comparison or benchmark has been presented as evidence in this package.

**Snowflake:** not an implemented source. A future Snowflake shortcut/Iceberg or
connector route must be selected against current supported table/storage formats,
networking and credentials. A generic Snowflake SQL table is not automatically
a OneLake shortcut. Add it as a labelled extension with its own table contract,
validation and cost/security assessment, not as a sixth "already working" source.

## Pre-demo checklist

- Capacity active; source warehouse and gateway healthy.
- PostgreSQL listening; all mapped credentials valid.
- Latest Gold run PASSED and semantic refresh completed.
- Transactions/Targets smoke queries pass.
- Advisor slicers reset to October 2026 / Plan.
- Reports open as intended audience; browser permits required sign-in flow.
- PDF/CSV sample available if export service is slow.
- No real customer data, live secrets or private environment IDs on screen.
