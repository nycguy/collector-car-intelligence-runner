# Google Actions authorization status and contract

Status on 2026-11-21: BLOCKED. No Google Cloud project or identity has been
verified. Cloud Console was inaccessible from the available browser. Connected
GitHub access confirmed zero repository Actions variables and zero secrets.
The workbook has only the owner's permission; no runner identity is shared.

The workflow accepts repository variables (preferred) or existing secrets named
`GCP_WORKLOAD_IDENTITY_PROVIDER` and `GCP_SERVICE_ACCOUNT`. These are non-secret
identifiers, not private keys. Production runs are restricted to `main`.

When Cloud administration becomes available, inspect existing resources first.
The intended GitHub identity is repository ID `1466645605`, owner ID `8333082`,
repository `nycguy/collector-car-intelligence-runner`, ref `refs/heads/main`.
Require all identifiers and the exact ref in the provider condition, map
`google.subject=assertion.sub` and `attribute.repository_id=assertion.repository_id`,
and bind only that repository principal to the dedicated service account using
`roles/iam.workloadIdentityUser`. The issuer is
`https://token.actions.githubusercontent.com`.

Use Sheets, IAM Credentials and strictly necessary federation APIs. Do not enable
billing or assign project Owner/Editor to the service account. Grant Editor only
on the production spreadsheet, not the research folder. Do not create JSON keys.
A suitable short service-account ID, if no existing identity fits, is
`cci-production-runner`. No identity with that name has been created.

After resources and spreadsheet sharing are verified, configure the two repository
variables and dispatch `auth-test` from `main`. Review OIDC, Google impersonation,
full-range retrieval and exact output readback before dispatching `production`.
No authentication or production run was attempted with absent configuration.

An auth test is not valuation evidence. Even a successful current `production`
run remains exploratory because the legacy engine lacks full adjustments and
validated forecasts. Do not accept Sprint 25 or dispatch Sprint 26 on that basis.
