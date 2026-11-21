# Collector Car Intelligence Runner

Public, disclosure-reviewed execution surface. Private transaction rows, VINs,
credentials, and research files never enter its source or public artifacts.

The manually dispatched `campaign` workflow runs only from `main`, uses Google
OIDC, and defaults to `auth-test`. This reads and validates all 43 transaction
columns and the expected 28,058-row population, fingerprints the ephemeral CSV,
and writes aggregate evidence to `Sprint 25 Auth Test` with exact cell readback.

`production` invokes the existing Sprint 22 reconciliation and valuation functions
on eligible explicit mappings and publishes aggregate diagnostics to `Sprint 25
Runner Output`. The reused engine computes **unadjusted exploratory medians**.
It does not satisfy adjusted valuation, forecast, or backtesting requirements;
all supported investment counts remain unavailable and acceptance stays blocked.
There is no autonomous dispatch implementation in this runner.

Both modes delete the local input. Only two explicitly named aggregate JSON files
can be uploaded. Unit tests use synthetic observations, never production rows.

Run tests: `python -m unittest discover -s tests -v`.
