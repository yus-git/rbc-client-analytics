# Data dictionary

[Home](../README.md) | [Source/storage inventory](architecture.md)

Generated from the sanitized seed contract with `python tools/build_dictionary.py`.
Names below are physical source columns; the semantic model uses friendly display names.
All financial amounts suffixed CAD are in Canadian dollars. All records are synthetic.

The `IsSynthetic` field is a required data-quality flag, not an access-control mechanism.

## dim_date

**Grain:** One row per calendar date; illustrative fiscal year starts November 1.
**Rows:** 1,461.
**Primary key:** `DateKey`.

| Column | Source type | Relationship role |
|---|---|---|
| `DateKey` | `int` | Primary key |
| `Date` | `date` |  |
| `CalendarYear` | `int` |  |
| `CalendarQuarter` | `int` |  |
| `MonthNumber` | `int` |  |
| `MonthName` | `string` |  |
| `YearMonth` | `string` |  |
| `MonthStartDateKey` | `int` |  |
| `MonthEndDateKey` | `int` |  |
| `DayOfMonth` | `int` |  |
| `DayName` | `string` |  |
| `IsWeekend` | `boolean` |  |
| `FiscalYear` | `int` |  |
| `FiscalQuarter` | `int` |  |
| `IsSynthetic` | `boolean` |  |

## dim_client

**Grain:** One row per client SCD type 2 version; fact dates resolve to half-open validity intervals.
**Rows:** 11,000.
**Primary key:** `ClientKey`.

| Column | Source type | Relationship role |
|---|---|---|
| `ClientKey` | `int` | Primary key |
| `ClientId` | `int` |  |
| `ClientName` | `string` |  |
| `HouseholdId` | `int` |  |
| `HouseholdName` | `string` |  |
| `Region` | `string` |  |
| `Segment` | `string` |  |
| `RiskBand` | `string` |  |
| `AgeAtBaseline` | `int` |  |
| `PreferredChannel` | `string` |  |
| `OnboardDate` | `date` |  |
| `EffectiveFrom` | `date` |  |
| `EffectiveToExclusive` | `date` |  |
| `IsCurrent` | `boolean` |  |
| `IsSynthetic` | `boolean` |  |

## dim_account_owner

**Grain:** One row per current account owner; distinct analytical role from historical economic client.
**Rows:** 10,000.
**Primary key:** `OwnerKey`.

| Column | Source type | Relationship role |
|---|---|---|
| `OwnerKey` | `int` | Primary key |
| `OwnerName` | `string` |  |
| `HouseholdId` | `int` |  |
| `HouseholdName` | `string` |  |
| `Region` | `string` |  |
| `Segment` | `string` |  |
| `IsSynthetic` | `boolean` |  |

## dim_account

**Grain:** One row per synthetic account; all accounts open before the observation window.
**Rows:** 20,000.
**Primary key:** `AccountKey`.

| Column | Source type | Relationship role |
|---|---|---|
| `AccountKey` | `int` | Primary key |
| `AccountNumber` | `string` |  |
| `AccountType` | `string` |  |
| `CurrencyCode` | `string` |  |
| `OpenDate` | `date` |  |
| `AccountStatus` | `string` |  |
| `IsSynthetic` | `boolean` |  |

## dim_advisor

**Grain:** One row per advisor; team and branch attributes denormalized into the dimension.
**Rows:** 100.
**Primary key:** `AdvisorKey`.

| Column | Source type | Relationship role |
|---|---|---|
| `AdvisorKey` | `int` | Primary key |
| `AdvisorName` | `string` |  |
| `TeamName` | `string` |  |
| `BranchName` | `string` |  |
| `AdvisorRegion` | `string` |  |
| `IsSynthetic` | `boolean` |  |

## dim_product

**Grain:** One row per analytical product; not a production product catalogue.
**Rows:** 8.
**Primary key:** `ProductKey`.

| Column | Source type | Relationship role |
|---|---|---|
| `ProductKey` | `int` | Primary key |
| `ProductName` | `string` |  |
| `ProductFamily` | `string` |  |
| `IsSynthetic` | `boolean` |  |

## dim_channel

**Grain:** One row per engagement or transaction channel.
**Rows:** 5.
**Primary key:** `ChannelKey`.

| Column | Source type | Relationship role |
|---|---|---|
| `ChannelKey` | `int` | Primary key |
| `ChannelName` | `string` |  |
| `IsSynthetic` | `boolean` |  |

## dim_campaign

**Grain:** One row per campaign, including key 0 for no campaign.
**Rows:** 13.
**Primary key:** `CampaignKey`.

| Column | Source type | Relationship role |
|---|---|---|
| `CampaignKey` | `int` | Primary key |
| `CampaignName` | `string` |  |
| `Objective` | `string` |  |
| `IsSynthetic` | `boolean` |  |

## bridge_account_owner

**Grain:** One row per account/current owner; weights sum to one; not historical ownership.
**Rows:** 24,000.
**Primary key:** `AccountKey`, `OwnerKey`.

| Column | Source type | Relationship role |
|---|---|---|
| `AccountKey` | `int` | Primary key; References `dim_account.AccountKey` |
| `OwnerKey` | `int` | Primary key; References `dim_account_owner.OwnerKey` |
| `OwnerRole` | `string` |  |
| `OwnershipWeight` | `decimal(5,4)` |  |
| `IsSynthetic` | `boolean` |  |

## fact_transaction

**Grain:** One row per booked account transaction; ClientKey is the historical primary economic client.
**Rows:** 1,000,000.
**Primary key:** `TransactionKey`.

| Column | Source type | Relationship role |
|---|---|---|
| `TransactionKey` | `bigint` | Primary key |
| `BookingDateKey` | `int` | References `dim_date.DateKey` |
| `SettlementDateKey` | `int` | References `dim_date.DateKey`; Inactive date role |
| `ClientKey` | `int` | References `dim_client.ClientKey` |
| `AccountKey` | `int` | References `dim_account.AccountKey` |
| `AdvisorKey` | `int` | References `dim_advisor.AdvisorKey` |
| `ProductKey` | `int` | References `dim_product.ProductKey` |
| `ChannelKey` | `int` | References `dim_channel.ChannelKey` |
| `SignedAmountCAD` | `decimal(18,2)` |  |
| `FeeCAD` | `decimal(18,2)` |  |
| `TransactionType` | `string` |  |
| `IsSynthetic` | `boolean` |  |

## fact_account_monthly

**Grain:** One row per account/month-end; balances are additive across accounts, not across dates.
**Rows:** 680,000.
**Primary key:** `AccountKey`, `DateKey`.

| Column | Source type | Relationship role |
|---|---|---|
| `AccountKey` | `int` | Primary key; References `dim_account.AccountKey` |
| `DateKey` | `int` | Primary key; References `dim_date.DateKey` |
| `ClientKey` | `int` | References `dim_client.ClientKey` |
| `AdvisorKey` | `int` | References `dim_advisor.AdvisorKey` |
| `ProductKey` | `int` | References `dim_product.ProductKey` |
| `OpeningBalanceCAD` | `decimal(18,2)` |  |
| `NetFlowCAD` | `decimal(18,2)` |  |
| `MarketMovementCAD` | `decimal(18,2)` |  |
| `ClosingBalanceCAD` | `decimal(18,2)` |  |
| `TransactionFeesCAD` | `decimal(18,2)` |  |
| `RevenueCAD` | `decimal(18,2)` |  |
| `CostCAD` | `decimal(18,2)` |  |
| `IsSynthetic` | `boolean` |  |

## fact_interaction

**Grain:** One row per client interaction; not account or product grain.
**Rows:** 100,000.
**Primary key:** `InteractionKey`.

| Column | Source type | Relationship role |
|---|---|---|
| `InteractionKey` | `bigint` | Primary key |
| `DateKey` | `int` | References `dim_date.DateKey` |
| `ClientKey` | `int` | References `dim_client.ClientKey` |
| `AdvisorKey` | `int` | References `dim_advisor.AdvisorKey` |
| `ChannelKey` | `int` | References `dim_channel.ChannelKey` |
| `CampaignKey` | `int` | References `dim_campaign.CampaignKey` |
| `DurationMinutes` | `int` |  |
| `SatisfactionScore` | `int` |  |
| `IsSynthetic` | `boolean` |  |

## fact_opportunity

**Grain:** One row per opportunity, accumulating snapshot as of end_date; client version at creation.
**Rows:** 15,000.
**Primary key:** `OpportunityKey`.

| Column | Source type | Relationship role |
|---|---|---|
| `OpportunityKey` | `bigint` | Primary key |
| `CreatedDateKey` | `int` | References `dim_date.DateKey` |
| `ExpectedCloseDateKey` | `int` | References `dim_date.DateKey`; Inactive date role |
| `ActualCloseDateKey` | `int` | References `dim_date.DateKey`; Inactive date role |
| `ClientKey` | `int` | References `dim_client.ClientKey` |
| `AdvisorKey` | `int` | References `dim_advisor.AdvisorKey` |
| `ProductKey` | `int` | References `dim_product.ProductKey` |
| `CampaignKey` | `int` | References `dim_campaign.CampaignKey` |
| `Stage` | `string` |  |
| `EstimatedValueCAD` | `decimal(18,2)` |  |
| `Probability` | `decimal(4,3)` |  |
| `IsSynthetic` | `boolean` |  |

## fact_target

**Grain:** One row per month/advisor/product/scenario; never allocate implicitly to clients/accounts.
**Rows:** 54,400.
**Primary key:** `DateKey`, `AdvisorKey`, `ProductKey`, `Scenario`.

| Column | Source type | Relationship role |
|---|---|---|
| `DateKey` | `int` | Primary key; References `dim_date.DateKey` |
| `AdvisorKey` | `int` | Primary key; References `dim_advisor.AdvisorKey` |
| `ProductKey` | `int` | Primary key; References `dim_product.ProductKey` |
| `Scenario` | `string` | Primary key |
| `RevenueTargetCAD` | `decimal(18,2)` |  |
| `NewClientsTarget` | `int` |  |
| `IsSynthetic` | `boolean` |  |
