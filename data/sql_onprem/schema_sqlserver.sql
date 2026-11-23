SET XACT_ABORT ON;

IF SCHEMA_ID(N'ca_demo') IS NULL EXEC(N'CREATE SCHEMA ca_demo');

CREATE TABLE ca_demo.[dim_client] (
    [ClientKey] int NOT NULL,
    [ClientId] int NOT NULL,
    [ClientName] nvarchar(256) NOT NULL,
    [HouseholdId] int NOT NULL,
    [HouseholdName] nvarchar(256) NOT NULL,
    [Region] nvarchar(256) NOT NULL,
    [Segment] nvarchar(256) NOT NULL,
    [RiskBand] nvarchar(256) NOT NULL,
    [AgeAtBaseline] int NOT NULL,
    [PreferredChannel] nvarchar(256) NOT NULL,
    [OnboardDate] date NOT NULL,
    [EffectiveFrom] date NOT NULL,
    [EffectiveToExclusive] date NOT NULL,
    [IsCurrent] bit NOT NULL,
    [IsSynthetic] bit NOT NULL,
    PRIMARY KEY ([ClientKey])
);

CREATE TABLE ca_demo.[dim_account_owner] (
    [OwnerKey] int NOT NULL,
    [OwnerName] nvarchar(256) NOT NULL,
    [HouseholdId] int NOT NULL,
    [HouseholdName] nvarchar(256) NOT NULL,
    [Region] nvarchar(256) NOT NULL,
    [Segment] nvarchar(256) NOT NULL,
    [IsSynthetic] bit NOT NULL,
    PRIMARY KEY ([OwnerKey])
);

CREATE TABLE ca_demo.[dim_advisor] (
    [AdvisorKey] int NOT NULL,
    [AdvisorName] nvarchar(256) NOT NULL,
    [TeamName] nvarchar(256) NOT NULL,
    [BranchName] nvarchar(256) NOT NULL,
    [AdvisorRegion] nvarchar(256) NOT NULL,
    [IsSynthetic] bit NOT NULL,
    PRIMARY KEY ([AdvisorKey])
);

CREATE TABLE ca_demo.[bridge_account_owner] (
    [AccountKey] int NOT NULL,
    [OwnerKey] int NOT NULL,
    [OwnerRole] nvarchar(256) NOT NULL,
    [OwnershipWeight] decimal(5,4) NOT NULL,
    [IsSynthetic] bit NOT NULL,
    PRIMARY KEY ([AccountKey], [OwnerKey])
);
