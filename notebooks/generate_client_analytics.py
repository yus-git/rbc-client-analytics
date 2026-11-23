# %% Parameters
client_count = 10000
account_count = 20000
transaction_count = 1000000
interaction_count = 100000
opportunity_count = 15000
seed = 20261115
start_date = "2024-01-01"
end_date = "2026-10-31"
reset_synthetic_tables = False
export_source_kits = True

# %% Runtime and data contract
import json
import logging
from datetime import date, datetime, timezone

from pyspark.sql import functions as F

logger = logging.getLogger("client_analytics")
logger.setLevel(logging.INFO)
run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
generator_version = "1.0"
start = date.fromisoformat(start_date)
end = date.fromisoformat(end_date)
if not (
    100 <= client_count <= 50000
    and client_count % 2 == 0
    and client_count <= account_count <= 100000
    and 1000 <= transaction_count <= 5000000
    and 100 <= interaction_count <= 1000000
    and 100 <= opportunity_count <= 100000
    and start == date(2024, 1, 1)
    and end == date(2026, 10, 31)
):
    raise ValueError("Unsupported demo profile; use even client counts and the documented bounds/dates.")
if not isinstance(reset_synthetic_tables, bool) or not isinstance(export_source_kits, bool):
    raise TypeError("Boolean notebook parameters must be booleans, not strings.")
day_count = (end - start).days + 1
month_count = (end.year - start.year) * 12 + end.month - start.month + 1
advisor_count = 100
context = notebookutils.runtime.context
if not context.get("defaultLakehouseId"):
    raise RuntimeError("Attach the schema-enabled demo Lakehouse before running.")
spark.conf.set("spark.sql.session.timeZone", "UTC")
spark.conf.set("spark.sql.shuffle.partitions", "16")
spark.conf.set("spark.sql.adaptive.enabled", "true")
spark.sql("CREATE SCHEMA IF NOT EXISTS gold")
spark.sql("CREATE SCHEMA IF NOT EXISTS ops")

contracts = {}
checks = []


def hashed(expression: str, salt: str, modulus: int) -> str:
    return f"pmod(xxhash64({expression}, {seed}, '{salt}'), {modulus})"


def client_key(client_id: str, at_date: str) -> str:
    return (
        f"CAST({client_id} + CASE WHEN pmod({client_id}, 10) = 0 "
        f"AND {at_date} >= DATE'2025-07-01' THEN {client_count} ELSE 0 END AS INT)"
    )


def advisor_key(client_id: str) -> str:
    return f"CAST(pmod({client_id} - 1, {advisor_count}) + 1 AS INT)"


def product_key(account_id: str) -> str:
    return f"CAST({hashed(account_id, 'product', 8)} + 1 AS INT)"


def date_key(expression: str) -> str:
    return f"CAST(date_format({expression}, 'yyyyMMdd') AS INT)"


def materialize(
    name: str,
    sql: str,
    grain: str,
    primary_key: list[str],
    intended_source: str,
    expected_rows: int,
    references: dict[str, str] | None = None,
    inactive: list[str] | None = None,
) -> None:
    full_name = f"gold.{name}"
    if spark.catalog.tableExists(full_name):
        properties = {
            row.key: row.value
            for row in spark.sql(f"SHOW TBLPROPERTIES {full_name}").collect()
        }
        if not reset_synthetic_tables or properties.get("demo.generator") != "client_analytics":
            raise RuntimeError(
                f"Refusing to replace {full_name}. Reset is permitted only for tagged synthetic tables."
            )
    frame = spark.sql(sql).withColumn("IsSynthetic", F.lit(True))
    frame.write.format("delta").mode(
        "overwrite" if reset_synthetic_tables else "errorifexists"
    ).saveAsTable(full_name)
    spark.sql(f"ALTER TABLE {full_name} SET TBLPROPERTIES ('demo.generator'='client_analytics')")
    spark.table(full_name).createOrReplaceTempView(name)
    contracts[name] = {
        "grain": grain,
        "primary_key": primary_key,
        "intended_source": intended_source,
        "actual_source": "Fabric synthetic generator",
        "expected_rows": expected_rows,
        "references": references or {},
        "inactive_relationship_columns": inactive or [],
        "columns": [
            {"name": field.name, "type": field.dataType.simpleString()}
            for field in frame.schema
        ],
    }
    logger.info("Persisted %s", full_name)
    print(f"Persisted {full_name}", flush=True)


def check(name: str, violation_sql: str) -> None:
    failures = int(spark.sql(violation_sql).first()[0])
    checks.append((run_id, name, failures, failures == 0))
    print(f"{'PASS' if failures == 0 else 'FAIL'} {name}: {failures}", flush=True)


# %% Conformed dimensions
materialize(
    "dim_date",
    """
    SELECT CAST(date_format(d, 'yyyyMMdd') AS INT) DateKey, d Date,
           year(d) CalendarYear, quarter(d) CalendarQuarter, month(d) MonthNumber,
           date_format(d, 'MMMM') MonthName, date_format(d, 'yyyy-MM') YearMonth,
           CAST(date_format(trunc(d, 'MM'), 'yyyyMMdd') AS INT) MonthStartDateKey,
           CAST(date_format(last_day(d), 'yyyyMMdd') AS INT) MonthEndDateKey,
           dayofmonth(d) DayOfMonth, date_format(d, 'EEEE') DayName,
           dayofweek(d) IN (1, 7) IsWeekend,
           year(add_months(d, 2)) FiscalYear,
           quarter(add_months(d, 2)) FiscalQuarter
    FROM (SELECT explode(sequence(DATE'2024-01-01', DATE'2027-12-31', INTERVAL 1 DAY)) d)
    """,
    "One row per calendar date; illustrative fiscal year starts November 1",
    ["DateKey"], "Lakehouse", 1461,
)
materialize(
    "dim_client",
    f"""
    WITH clients AS (
        SELECT CAST(id + 1 AS INT) ClientId FROM range({client_count})
    ), versions AS (
        SELECT ClientId, 1 Version FROM clients
        UNION ALL SELECT ClientId, 2 Version FROM clients WHERE pmod(ClientId, 10) = 0
    )
    SELECT CAST(ClientId + CASE WHEN Version = 2 THEN {client_count} ELSE 0 END AS INT) ClientKey,
           ClientId, concat('Synthetic Client ', lpad(CAST(ClientId AS STRING), 6, '0')) ClientName,
           CAST(floor((ClientId - 1) / 2) + 1 AS INT) HouseholdId,
           concat('Synthetic Household ', CAST(floor((ClientId - 1) / 2) + 1 AS INT)) HouseholdName,
           element_at(array('Ontario', 'Quebec', 'British Columbia', 'Alberta', 'Atlantic'),
                      CAST(pmod(ClientId - 1, 5) + 1 AS INT)) Region,
           element_at(array('Mass Market', 'Affluent', 'High Net Worth'),
                      CAST(pmod(ClientId + Version - 2, 3) + 1 AS INT)) Segment,
           element_at(array('Low', 'Moderate', 'High'),
                      CAST(pmod(ClientId + Version - 2, 3) + 1 AS INT)) RiskBand,
           CAST(25 + {hashed('ClientId', 'age', 55)} AS INT) AgeAtBaseline,
           element_at(array('Branch', 'Digital', 'Advisor'),
                      CAST({hashed('ClientId', 'preference', 3)} + 1 AS INT)) PreferredChannel,
           date_sub(DATE'2024-01-01', CAST(365 + {hashed('ClientId', 'onboard', 3650)} AS INT)) OnboardDate,
           CASE WHEN Version = 1 THEN DATE'2024-01-01' ELSE DATE'2025-07-01' END EffectiveFrom,
           CASE WHEN Version = 1 AND pmod(ClientId, 10) = 0
                THEN DATE'2025-07-01' ELSE DATE'9999-12-31' END EffectiveToExclusive,
           (Version = 2 OR pmod(ClientId, 10) <> 0) IsCurrent
    FROM versions
    """,
    "One row per client SCD type 2 version; fact dates resolve to half-open validity intervals",
    ["ClientKey"], "PostgreSQL", client_count + client_count // 10,
)
materialize(
    "dim_account_owner",
    """
    SELECT ClientId OwnerKey, ClientName OwnerName, HouseholdId, HouseholdName, Region, Segment
    FROM dim_client WHERE IsCurrent
    """,
    "One row per current account owner; distinct analytical role from historical economic client",
    ["OwnerKey"], "PostgreSQL", client_count,
)
materialize(
    "dim_account",
    f"""
    SELECT CAST(id + 1 AS INT) AccountKey,
           concat('SYN-ACC-', lpad(CAST(id + 1 AS STRING), 8, '0')) AccountNumber,
           element_at(array('Investment', 'Savings', 'Retirement', 'Managed Portfolio'),
                      CAST({hashed('id + 1', 'accounttype', 4)} + 1 AS INT)) AccountType,
           'CAD' CurrencyCode, DATE'2023-01-01' OpenDate, 'Active' AccountStatus
    FROM range({account_count})
    """,
    "One row per synthetic account; all accounts open before the observation window",
    ["AccountKey"], "PostgreSQL", account_count,
)
materialize(
    "dim_advisor",
    f"""
    SELECT CAST(id + 1 AS INT) AdvisorKey,
           concat('Synthetic Advisor ', lpad(CAST(id + 1 AS STRING), 3, '0')) AdvisorName,
           concat('Team ', CAST(floor(id / 10) + 1 AS INT)) TeamName,
           concat('Branch ', CAST(floor(id / 5) + 1 AS INT)) BranchName,
           element_at(array('Ontario', 'Quebec', 'British Columbia', 'Alberta', 'Atlantic'),
                      CAST(pmod(id, 5) + 1 AS INT)) AdvisorRegion
    FROM range({advisor_count})
    """,
    "One row per advisor; team and branch attributes denormalized into the dimension",
    ["AdvisorKey"], "PostgreSQL", advisor_count,
)
materialize(
    "dim_product",
    """
    SELECT CAST(id + 1 AS INT) ProductKey,
           element_at(array('Cash Reserve', 'Bond Fund', 'Equity Fund', 'Balanced Fund',
                            'Growth Portfolio', 'Income Portfolio', 'Retirement Fund', 'Index Fund'),
                      CAST(id + 1 AS INT)) ProductName,
           element_at(array('Cash', 'Fixed Income', 'Equity', 'Multi Asset',
                            'Multi Asset', 'Fixed Income', 'Multi Asset', 'Equity'),
                      CAST(id + 1 AS INT)) ProductFamily
    FROM range(8)
    """,
    "One row per analytical product; not a production product catalogue",
    ["ProductKey"], "Snowflake", 8,
)
materialize(
    "dim_channel",
    """
    SELECT CAST(id + 1 AS INT) ChannelKey,
           element_at(array('Branch', 'Mobile', 'Web', 'Contact Centre', 'Advisor'),
                      CAST(id + 1 AS INT)) ChannelName
    FROM range(5)
    """,
    "One row per engagement or transaction channel",
    ["ChannelKey"], "Lakehouse", 5,
)
materialize(
    "dim_campaign",
    """
    SELECT CAST(id AS INT) CampaignKey,
           CASE WHEN id = 0 THEN 'No campaign'
                ELSE concat('Synthetic Campaign ', CAST(id AS STRING)) END CampaignName,
           CASE WHEN id = 0 THEN 'Not applicable'
                ELSE element_at(array('Acquisition', 'Retention', 'Cross Sell'),
                                CAST(pmod(id, 3) + 1 AS INT)) END Objective
    FROM range(13)
    """,
    "One row per campaign, including key 0 for no campaign",
    ["CampaignKey"], "Excel", 13,
)
materialize(
    "bridge_account_owner",
    f"""
    WITH owners AS (
        SELECT AccountKey, CAST(pmod(AccountKey - 1, {client_count}) + 1 AS INT) OwnerKey
        FROM dim_account
    )
    SELECT AccountKey, OwnerKey, 'Primary' OwnerRole,
           CAST(CASE WHEN pmod(AccountKey, 5) = 0 THEN 0.5 ELSE 1 END AS DECIMAL(5,4)) OwnershipWeight
    FROM owners
    UNION ALL
    SELECT AccountKey, CAST(CASE WHEN pmod(OwnerKey, 2) = 1 THEN OwnerKey + 1 ELSE OwnerKey - 1 END AS INT),
           'Joint', CAST(0.5 AS DECIMAL(5,4))
    FROM owners WHERE pmod(AccountKey, 5) = 0
    """,
    "One row per account/current owner; weights sum to one; not historical ownership",
    ["AccountKey", "OwnerKey"], "PostgreSQL", account_count + account_count // 5,
    {"AccountKey": "dim_account.AccountKey", "OwnerKey": "dim_account_owner.OwnerKey"},
)

# %% Transaction fact: atomic event grain and role-playing dates
materialize(
    "fact_transaction",
    f"""
    WITH events AS (
        SELECT id + 1 TransactionKey,
               CAST({hashed('id', 'account', account_count)} + 1 AS INT) AccountKey,
               date_add(DATE'{start_date}', CAST({hashed('id', 'bookdate', day_count)} AS INT)) BookingDate,
               CAST({hashed('id', 'channel', 5)} + 1 AS INT) ChannelKey,
               CAST(({hashed('id', 'amount', 200001)} - 100000) / 100.0 AS DECIMAL(18,2)) SignedAmountCAD
        FROM range({transaction_count})
    ), clients AS (
        SELECT *, CAST(pmod(AccountKey - 1, {client_count}) + 1 AS INT) ClientId FROM events
    )
    SELECT TransactionKey, {date_key('BookingDate')} BookingDateKey,
           {date_key('date_add(BookingDate, 2)')} SettlementDateKey,
           {client_key('ClientId', 'BookingDate')} ClientKey, AccountKey,
           {advisor_key('ClientId')} AdvisorKey, {product_key('AccountKey')} ProductKey,
           ChannelKey, SignedAmountCAD,
           CAST(abs(SignedAmountCAD) * 0.001 AS DECIMAL(18,2)) FeeCAD,
           CASE WHEN SignedAmountCAD >= 0 THEN 'Contribution' ELSE 'Withdrawal' END TransactionType
    FROM clients
    """,
    "One row per booked account transaction; ClientKey is the historical primary economic client",
    ["TransactionKey"], "Databricks", transaction_count,
    {
        "BookingDateKey": "dim_date.DateKey", "SettlementDateKey": "dim_date.DateKey",
        "ClientKey": "dim_client.ClientKey", "AccountKey": "dim_account.AccountKey",
        "AdvisorKey": "dim_advisor.AdvisorKey", "ProductKey": "dim_product.ProductKey",
        "ChannelKey": "dim_channel.ChannelKey",
    },
    ["SettlementDateKey"],
)

# %% Monthly periodic snapshot: reconciled flows, semi-additive balances
materialize(
    "fact_account_monthly",
    f"""
    WITH monthly_flows AS (
        SELECT t.AccountKey, d.MonthEndDateKey DateKey, sum(t.SignedAmountCAD) NetFlowCAD,
               sum(t.FeeCAD) TransactionFeesCAD
        FROM fact_transaction t JOIN dim_date d ON t.BookingDateKey = d.DateKey
        GROUP BY t.AccountKey, d.MonthEndDateKey
    ), grid AS (
        SELECT a.AccountKey, d.DateKey, d.Date,
               CAST(pmod(a.AccountKey - 1, {client_count}) + 1 AS INT) ClientId,
               CAST(50000 + {hashed('a.AccountKey', 'opening', 950001)} AS DECIMAL(18,2)) InitialBalanceCAD
        FROM dim_account a CROSS JOIN dim_date d
        WHERE d.Date = last_day(d.Date) AND d.Date BETWEEN DATE'{start_date}' AND DATE'{end_date}'
    ), movements AS (
        SELECT g.*, CAST(coalesce(f.NetFlowCAD, 0) AS DECIMAL(18,2)) NetFlowCAD,
               CAST(coalesce(f.TransactionFeesCAD, 0) AS DECIMAL(18,2)) TransactionFeesCAD,
               CAST(g.InitialBalanceCAD * (
                    (CASE WHEN month(g.Date) IN (3, 9) THEN -0.008 ELSE 0.006 END)
                    + ({hashed('g.AccountKey + g.DateKey', 'market', 401)} - 200) / 100000.0
               ) AS DECIMAL(18,2)) MarketMovementCAD
        FROM grid g LEFT JOIN monthly_flows f ON g.AccountKey=f.AccountKey AND g.DateKey=f.DateKey
    ), balances AS (
        SELECT *,
               CAST(InitialBalanceCAD + sum(NetFlowCAD + MarketMovementCAD) OVER (
                    PARTITION BY AccountKey ORDER BY DateKey ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
               ) AS DECIMAL(18,2)) ClosingBalanceCAD
        FROM movements
    )
    SELECT AccountKey, DateKey, {client_key('ClientId', 'Date')} ClientKey,
           {advisor_key('ClientId')} AdvisorKey, {product_key('AccountKey')} ProductKey,
           CAST(ClosingBalanceCAD-NetFlowCAD-MarketMovementCAD AS DECIMAL(18,2)) OpeningBalanceCAD,
           NetFlowCAD, MarketMovementCAD, ClosingBalanceCAD, TransactionFeesCAD,
           CAST(InitialBalanceCAD * 0.0005 + TransactionFeesCAD AS DECIMAL(18,2)) RevenueCAD,
           CAST(InitialBalanceCAD * 0.0002 + 15 AS DECIMAL(18,2)) CostCAD
    FROM balances
    """,
    "One row per account/month-end; balances are additive across accounts, not across dates",
    ["AccountKey", "DateKey"], "Lakehouse", account_count * month_count,
    {
        "AccountKey": "dim_account.AccountKey", "DateKey": "dim_date.DateKey",
        "ClientKey": "dim_client.ClientKey", "AdvisorKey": "dim_advisor.AdvisorKey",
        "ProductKey": "dim_product.ProductKey",
    },
)
materialize(
    "fact_interaction",
    f"""
    WITH events AS (
        SELECT id+1 InteractionKey, CAST({hashed('id', 'client', client_count)} + 1 AS INT) ClientId,
               date_add(DATE'{start_date}', CAST({hashed('id', 'interactiondate', day_count)} AS INT)) EventDate,
               CAST({hashed('id', 'interactionchannel', 5)} + 1 AS INT) ChannelKey,
               CAST({hashed('id', 'campaign', 13)} AS INT) CampaignKey,
               CAST(1 + {hashed('id', 'duration', 60)} AS INT) DurationMinutes,
               CAST(1 + {hashed('id', 'satisfaction', 5)} AS INT) SatisfactionScore
        FROM range({interaction_count})
    )
    SELECT InteractionKey, {date_key('EventDate')} DateKey, {client_key('ClientId', 'EventDate')} ClientKey,
           {advisor_key('ClientId')} AdvisorKey, ChannelKey, CampaignKey, DurationMinutes, SatisfactionScore
    FROM events
    """,
    "One row per client interaction; not account or product grain",
    ["InteractionKey"], "PostgreSQL", interaction_count,
    {
        "DateKey": "dim_date.DateKey", "ClientKey": "dim_client.ClientKey",
        "AdvisorKey": "dim_advisor.AdvisorKey", "ChannelKey": "dim_channel.ChannelKey",
        "CampaignKey": "dim_campaign.CampaignKey",
    },
)
materialize(
    "fact_opportunity",
    f"""
    WITH base AS (
        SELECT id+1 OpportunityKey, CAST({hashed('id', 'oppclient', client_count)} + 1 AS INT) ClientId,
               date_add(DATE'{start_date}', CAST({hashed('id', 'oppdate', day_count)} AS INT)) CreatedDate,
               CAST({hashed('id', 'oppproduct', 8)} + 1 AS INT) ProductKey,
               CAST({hashed('id', 'oppcampaign', 13)} AS INT) CampaignKey,
               CAST(10000 + {hashed('id', 'oppvalue', 500000)} AS DECIMAL(18,2)) EstimatedValueCAD,
               CAST({hashed('id', 'outcome', 10)} AS INT) OutcomeCode
        FROM range({opportunity_count})
    ), stages AS (
        SELECT *, date_add(CreatedDate, 30) ExpectedCloseDate,
               CASE WHEN date_add(CreatedDate,30) > DATE'{end_date}' THEN 'Open'
                    WHEN OutcomeCode < 6 THEN 'Won' ELSE 'Lost' END Stage
        FROM base
    )
    SELECT OpportunityKey, {date_key('CreatedDate')} CreatedDateKey,
           {date_key('ExpectedCloseDate')} ExpectedCloseDateKey,
           CASE WHEN Stage <> 'Open' THEN {date_key('ExpectedCloseDate')} END ActualCloseDateKey,
           {client_key('ClientId', 'CreatedDate')} ClientKey, {advisor_key('ClientId')} AdvisorKey,
           ProductKey, CampaignKey, Stage, EstimatedValueCAD,
           CAST(CASE Stage WHEN 'Won' THEN 1.0 WHEN 'Lost' THEN 0.0 ELSE 0.4 END AS DECIMAL(4,3)) Probability
    FROM stages
    """,
    "One row per opportunity, accumulating snapshot as of end_date; client version at creation",
    ["OpportunityKey"], "PostgreSQL", opportunity_count,
    {
        "CreatedDateKey": "dim_date.DateKey", "ExpectedCloseDateKey": "dim_date.DateKey",
        "ActualCloseDateKey": "dim_date.DateKey", "ClientKey": "dim_client.ClientKey",
        "AdvisorKey": "dim_advisor.AdvisorKey", "ProductKey": "dim_product.ProductKey",
        "CampaignKey": "dim_campaign.CampaignKey",
    },
    ["ExpectedCloseDateKey", "ActualCloseDateKey"],
)
materialize(
    "fact_target",
    f"""
    SELECT d.DateKey, a.AdvisorKey, p.ProductKey, s.Scenario,
           CAST((10000 + {hashed('a.AdvisorKey + p.ProductKey + d.DateKey', 'target', 12000)})
                * CASE WHEN s.Scenario = 'Stretch' THEN 1.15 ELSE 1 END AS DECIMAL(18,2)) RevenueTargetCAD,
           CAST(2 + {hashed('a.AdvisorKey + p.ProductKey + d.DateKey', 'newclienttarget', 12)} AS INT) NewClientsTarget
    FROM dim_date d CROSS JOIN dim_advisor a CROSS JOIN dim_product p
    CROSS JOIN (SELECT explode(array('Plan','Stretch')) Scenario) s
    WHERE d.Date = last_day(d.Date) AND d.Date BETWEEN DATE'{start_date}' AND DATE'{end_date}'
    """,
    "One row per month/advisor/product/scenario; never allocate implicitly to clients/accounts",
    ["DateKey", "AdvisorKey", "ProductKey", "Scenario"], "Excel", month_count * advisor_count * 8 * 2,
    {"DateKey": "dim_date.DateKey", "AdvisorKey": "dim_advisor.AdvisorKey", "ProductKey": "dim_product.ProductKey"},
)

# %% Data-quality gates against persisted Delta tables
for name, contract in contracts.items():
    keys = ", ".join(contract["primary_key"])
    null_keys = " OR ".join(f"{column} IS NULL" for column in contract["primary_key"])
    check(
        f"{name}: row count, key uniqueness and key nulls",
        f"SELECT abs(count(*) - {contract['expected_rows']}) "
        f"+ count(*) - count(DISTINCT struct({keys})) "
        f"+ coalesce(sum(CASE WHEN {null_keys} THEN 1 ELSE 0 END),0) FROM {name}",
    )
    for column, target in contract["references"].items():
        dimension, target_column = target.split(".")
        check(
            f"{name}.{column}: referential integrity",
            f"SELECT count(*) FROM {name} f LEFT ANTI JOIN {dimension} d "
            f"ON f.{column}=d.{target_column} WHERE f.{column} IS NOT NULL",
        )
    nullable_keys = {"ActualCloseDateKey"} if name == "fact_opportunity" else set()
    required_keys = [column for column in contract["references"] if column not in nullable_keys]
    if required_keys:
        check(
            f"{name}: required foreign keys",
            f"SELECT count(*) FROM {name} WHERE " + " OR ".join(f"{key} IS NULL" for key in required_keys),
        )

check("Client SCD: one current version", """
    SELECT count(*) FROM (
        SELECT ClientId FROM dim_client GROUP BY ClientId
        HAVING sum(CASE WHEN IsCurrent THEN 1 ELSE 0 END) <> 1
    )
""")
check("Client SCD: nonoverlapping contiguous intervals", """
    SELECT count(*) FROM (
        SELECT *, lag(EffectiveToExclusive) OVER (PARTITION BY ClientId ORDER BY EffectiveFrom) PreviousEnd
        FROM dim_client
    ) WHERE EffectiveFrom >= EffectiveToExclusive OR (PreviousEnd IS NOT NULL AND PreviousEnd <> EffectiveFrom)
""")
for fact, column in [
    ("fact_transaction", "BookingDateKey"), ("fact_account_monthly", "DateKey"),
    ("fact_interaction", "DateKey"), ("fact_opportunity", "CreatedDateKey"),
]:
    check(
        f"{fact}: historical client version",
        f"SELECT count(*) FROM {fact} f JOIN dim_client c ON f.ClientKey=c.ClientKey "
        f"JOIN dim_date d ON f.{column}=d.DateKey "
        "WHERE d.Date < c.EffectiveFrom OR d.Date >= c.EffectiveToExclusive",
    )
check("Ownership: allocation weights", """
    SELECT count(*) FROM (
        SELECT AccountKey FROM bridge_account_owner GROUP BY AccountKey
        HAVING sum(OwnershipWeight) <> 1 OR min(OwnershipWeight) <= 0
    )
""")
check("Ownership: every account covered", """
    SELECT count(*) FROM dim_account a LEFT ANTI JOIN bridge_account_owner b ON a.AccountKey=b.AccountKey
""")
check("Transactions: settlement follows booking", """
    SELECT count(*) FROM fact_transaction WHERE SettlementDateKey < BookingDateKey
""")
check("Balances: accounting equation", """
    SELECT count(*) FROM fact_account_monthly
    WHERE OpeningBalanceCAD + NetFlowCAD + MarketMovementCAD <> ClosingBalanceCAD
""")
check("Balances: continuity", """
    SELECT count(*) FROM (
        SELECT *, lag(ClosingBalanceCAD) OVER (PARTITION BY AccountKey ORDER BY DateKey) PreviousClose
        FROM fact_account_monthly
    ) WHERE PreviousClose IS NOT NULL AND PreviousClose <> OpeningBalanceCAD
""")
check("Balances: flows reconcile to transactions by account/month", """
    WITH tx AS (
        SELECT t.AccountKey, d.MonthEndDateKey DateKey, sum(t.SignedAmountCAD) Amount
        FROM fact_transaction t JOIN dim_date d ON t.BookingDateKey=d.DateKey
        GROUP BY t.AccountKey, d.MonthEndDateKey
    )
    SELECT count(*) FROM fact_account_monthly b FULL OUTER JOIN tx
    ON b.AccountKey=tx.AccountKey AND b.DateKey=tx.DateKey
    WHERE b.AccountKey IS NULL OR b.NetFlowCAD <> coalesce(tx.Amount, 0)
""")
check("Opportunities: stage and close date consistency", f"""
    SELECT count(*) FROM fact_opportunity
    WHERE (Stage='Open' AND ActualCloseDateKey IS NOT NULL)
       OR (Stage<>'Open' AND ActualCloseDateKey IS NULL)
       OR ActualCloseDateKey > {int(end.strftime('%Y%m%d'))}
       OR ActualCloseDateKey < CreatedDateKey
""")
check("Targets: positive values", """
    SELECT count(*) FROM fact_target WHERE RevenueTargetCAD <= 0 OR NewClientsTarget < 0
""")
check("Dimensions: continuous daily calendar", """
    SELECT count(*) - datediff(max(Date), min(Date)) - 1 FROM dim_date
""")
quality = spark.createDataFrame(
    checks, "RunId STRING, CheckName STRING, ViolationCount LONG, Passed BOOLEAN"
)
quality.write.format("delta").mode("append").saveAsTable("ops.data_quality_results")
manifest = {
    "run_id": run_id,
    "generator_version": generator_version,
    "seed": seed,
    "status": "FAILED" if any(row[2] for row in checks) else "PASSED",
    "as_of_date": end_date,
    "workspace_id": context["currentWorkspaceId"],
    "lakehouse_id": context["defaultLakehouseId"],
    "all_data_synthetic": True,
    "tables": contracts,
    "checks": [{"name": row[1], "violations": row[2], "passed": row[3]} for row in checks],
    "semantic_rules": [
        "Fact foreign keys are many-to-one with single-direction filters from dimensions.",
        "No direct fact-to-fact relationships or dimension-to-dimension relationships.",
        "Inactive date relationships require USERELATIONSHIP measures or separate role-playing date tables.",
        "Distinct clients means DISTINCTCOUNT(dim_client[ClientId]), not a count of SCD version keys.",
        "Closing balances are semi-additive: select last visible snapshot date, then sum accounts.",
        "Ownership bridge has two incoming single-direction relationships; use TREATAS for owner-to-account measures.",
        "Current ownership does not rewrite historical primary economic-client attribution.",
        "Select exactly one target scenario; targets are not meaningful at client/account grain.",
        "Illustrative CAD-only portfolios; market movements are synthetic, not real market returns.",
        "External sources in the contract are intended destinations; no external connectivity is claimed.",
    ],
}
artifact_path = f"Files/demo_runs/{run_id}"
notebookutils.fs.mkdirs(artifact_path)
notebookutils.fs.put(f"{artifact_path}/data_contract.json", json.dumps(manifest, indent=2), True)
if manifest["status"] != "PASSED":
    raise RuntimeError(f"Data-quality gate FAILED; see ops.data_quality_results for run {run_id}.")

# %% Source-ready extracts and data dictionary
if export_source_kits:
    for name, contract in contracts.items():
        source = contract["intended_source"].lower()
        path = f"{artifact_path}/source_kits/{source}/{name}"
        data = spark.table(f"gold.{name}")
        if source in ("postgresql", "excel"):
            data.coalesce(1).write.mode("errorifexists").option("header", True).csv(path)
        else:
            data.write.mode("errorifexists").parquet(path)
    notebookutils.fs.put(
        f"{artifact_path}/source_kits/NOTICE.txt",
        "All files are synthetic extracts. They are not live Databricks/Snowflake/Postgres connections. "
        "Excel-designated data is supplied as CSV, ready for a real workbook import. "
        "Keep keys/types unchanged when loading external systems. No mirroring or shortcut is configured.",
        True,
    )
dictionary_rows = [
    (name, column["name"], column["type"], contract["grain"], contract["intended_source"])
    for name, contract in contracts.items()
    for column in contract["columns"]
]
spark.createDataFrame(
    dictionary_rows, "TableName STRING, ColumnName STRING, DataType STRING, Grain STRING, IntendedSource STRING"
).withColumn("RunId", F.lit(run_id)).write.format("delta").mode("append").saveAsTable("ops.data_dictionary")
summary = {
    "run_id": run_id, "status": "PASSED", "gold_tables": len(contracts),
    "gold_rows": sum(contract["expected_rows"] for contract in contracts.values()),
    "quality_checks_passed": len(checks), "data_contract": f"{artifact_path}/data_contract.json",
    "source_kits": f"{artifact_path}/source_kits" if export_source_kits else None,
}
notebookutils.fs.put("Files/demo_latest.json", json.dumps(summary, indent=2), True)
print(json.dumps(summary, indent=2), flush=True)
notebookutils.notebook.exit(json.dumps(summary))
