ALTER TABLE ca_demo.[bridge_account_owner] ADD FOREIGN KEY ([OwnerKey]) REFERENCES ca_demo.[dim_account_owner] ([OwnerKey]);
