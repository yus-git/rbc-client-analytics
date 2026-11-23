# Validation, evidence and limitations

[Home](../README.md) | [Deployment](deployment.md) | [Operations](operations.md)

## Separate three kinds of evidence

| Evidence | What it proves | What it does not prove |
|---|---|---|
| Original Service checks, 17 November 2026 | The repaired model/report paths produced the results below | Current source liveness or every user's permission |
| Portable package local tests | Target IDs substitute correctly; seed/model/report contracts are preserved | A new tenant's credentials, network routes or capacity |
| Customer acceptance after deployment | Your environment's behavior for tested roles/workloads | Unmeasured production load or future service availability |

The repository includes a CI workflow that repeats local validation.
There are no automated changes to a customer's tenant in CI.

**GitHub-hosted validation:** the public repository's
[validation run](https://github.com/yus-git/rbc-client-analytics/actions/runs/45236084437)
passed on 23 November 2026 using Ubuntu and Python 3.12. It executed the unit
tests and complete seed/documentation checks in a clean checkout. This
complements local validation; it does not provision or validate a Fabric tenant.

## Original service evidence

| Check | Verified result |
|---|---|
| Direct Lake Channels query | 5 rows |
| Full semantic model refresh | Completed on 17 November 2026 |
| SQL and PostgreSQL gateway status | HTTP 200 at time of test |
| Transactions DQ | 1,000,000 rows |
| Net Contributions CAD | -1,438,757.40 |
| Transaction Fees CAD | 500,220.78 |
| Targets Import | 54,400 rows |
| All-date Plan target | CAD 435,735,118.00 |
| October 2026 / Plan advisor-product result | 800 combinations with populated targets/attainment |
| October AUM | CAD 11,816,392,773.18 |
| October Revenue | CAD 5,291,993.74 |
| October Plan target | CAD 12,961,660.00 |
| October variance | CAD -7,669,666.26 |
| Interactive advisor page PDF | October / Plan selected; attainment displayed as 40.8% |
| Paginated PDF with RDL defaults | 45 pages, 800 detail rows, repeated headers and complete page numbering |
| September / Ontario / Stretch CSV | 160 rows, all Ontario; financial sums matched independent DAX |

Alternate CSV totals:

| Measure | CAD |
|---|---:|
| AUM | 2,342,175,691.29 |
| Revenue | 1,054,328.89 |
| Target | 2,858,855.15 |
| Variance | -1,804,526.26 |

The [sample advisor pack](../samples/advisor-pack.pdf) preserves the verified
45-page PDF content with generic document metadata. It is historical synthetic
output, not a live connection to your environment.

## Local reproducibility

```powershell
python -B -m unittest discover -s tests -v
python -B tools\validate.py
```

Tests generate artifacts into temporary directories and check:

- 8 Direct Lake, 3 DirectQuery and 3 Import partitions.
- 29 single-direction relationships: 26 active, 3 inactive.
- 34 measures and exact contract-column mapping.
- Target SQL/PostgreSQL/Databricks/OneLake configuration.
- Rejection of placeholders, duplicate layer IDs and customized input models.
- Parameterized Silver/Gold notebooks with correct default lakehouse bindings.
- PBIDATASET bare parameter names and DAX references.
- Default slicer filter wrapper for October 2026 / Plan.

The seed validator checks all 14 row counts, exact columns, synthetic flags,
primary keys, foreign keys, transaction totals, seed SHA-256 checksums,
Python syntax and local documentation links. Row counts do not claim that
every possible business scenario is represented.

## New-environment acceptance queries

Execute as an approved model user using XMLA/DAX tooling or another supported
query path. REST executeQueries has identity/RLS/SSO restrictions; validate its
support for your model instead of assuming every service principal can query it.

### Storage-path counts

```dax
EVALUATE
ROW(
    "Channels_DL", COUNTROWS('Channels'),
    "Clients_DQ", COUNTROWS('Clients'),
    "Advisors_DQ", COUNTROWS('Advisors'),
    "Transactions_DQ", COUNTROWS('Transactions'),
    "Opportunities_Import", COUNTROWS('Opportunities'),
    "Campaigns_Import", COUNTROWS('Campaigns'),
    "Targets_Import", COUNTROWS('Targets')
)
```

Expected with the unrestricted reference dataset: **5, 11,000, 100, 1,000,000, 15,000, 13,
54,400** respectively.

### Cross-source advisor/product measures

```dax
EVALUATE
SUMMARIZECOLUMNS(
    TREATAS({"2026-10"}, 'Calendar'[Year Month]),
    TREATAS({"Plan"}, 'Targets'[Scenario]),
    "AUM", [Assets Under Management],
    "Revenue", [Revenue],
    "Target", [Revenue Target],
    "Attainment", [Revenue Attainment]
)
```

Compare to the October totals above. Compare currencies to the cent; compare
attainment using its full ratio, then separately verify the displayed 40.8%.
Do not filter by a single DateKey when comparing month-end snapshots with
first-of-month targets: use Year Month.

### Export acceptance

1. Render the interactive Advisor page and inspect actual displayed values, not
   only JSON schema validation.
2. Export paginated PDF with **no parameter overrides** to verify real defaults.
3. Verify 45 pages, all 800 advisor/product rows, repeat headers and last page.
4. Export September 2026 / Ontario / Stretch CSV; verify 160 rows and totals.
5. Export XLSX; compare numbers, column widths, merge behavior, row groups and
   print settings. XLSX remains an outstanding acceptance test.

### UI, access and performance acceptance

- Exercise every navigation/button and selection interaction in reading mode.
- Test drill-through with a selected client, then verify Back preserves context.
- Verify personal bookmarks for two users independently.
- Test allowed/denied RLS identities and app audiences.
- Record source trace + Power BI performance for representative queries,
  cold/warm caches and agreed concurrent users.
- For private deployment, complete [the VNet acceptance matrix](databricks-vnet.md).

## Known limitations / not claimed

- The model's example RLS role is unassigned. It is not production
  identity/entitlement management.
- Native web-model diagram rearrangement is not guaranteed by local layouts.
- Production SLAs, high availability, capacity sizing, accessibility, regulatory
  controls and disaster recovery require separate review and testing.
