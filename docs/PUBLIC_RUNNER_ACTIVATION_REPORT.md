# Public Runner Activation Report

Date: 2026-11-22

The repository is separate and public. Its contents remain data-agnostic Python, tests, configuration, workflows, and documentation. No private transaction exports, VIN-linked records, credentials, private Drive files, proprietary notes, or production artifacts are included. CSV and spreadsheet files remain ignored.

Activation status: VERIFIED for unattended Google Sheets execution through GitHub Actions.

Verified auth-test:
- Run: https://github.com/nycguy/collector-car-intelligence-runner/actions/runs/45027018459
- Workload Identity Federation, service-account impersonation, and Google Sheets access: passed
- Input: 28,058 rows
- Schema: 43 columns
- Test publication: `Sprint 25 Auth Test`
- Test publication rows: 16
- Test readback: verified
- Input SHA-256: `21c5458f814bc8ea05450ea27394d056070fa0eee72ce56341bfccd31e470d98`

Verified production:
- Run: https://github.com/nycguy/collector-car-intelligence-runner/actions/runs/45027134608
- Publication sheet: `Sprint 25 Runner Output`
- Publication rows: 38
- Production readback: verified
- Input SHA-256: `21c5458f814bc8ea05450ea27394d056070fa0eee72ce56341bfccd31e470d98`
- Commit executed: `aa78848ce3a59d77be3c003b9b77844572cf61ef`

The workflow is restricted to `refs/heads/main`. The production analytical result remains exploratory: analytical acceptance is false because condition/specification adjustment, verified variant crosswalk, and five-year forecast validation remain incomplete. No claim of qualified investment opportunities is made.
