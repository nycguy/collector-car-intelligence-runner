# Google Actions authorization status and contract

Status on 2026-11-22: VERIFIED. The existing Google Cloud Workload Identity Federation configuration is active for the public runner.

Verified configuration:
- Project: `collector-car-intelligence` (`485114889438`)
- Pool: `github-actions`
- Provider: `github`
- Issuer: `https://token.actions.githubusercontent.com`
- Mapping: `google.subject=assertion.sub`
- Mapping: `attribute.repository_id=assertion.repository_id`
- Provider condition restricts repository ID `1466645605` and `refs/heads/main`
- Service-account binding: repository principal only, role `roles/iam.workloadIdentityUser`
- Service account: `cci-production-runner@collector-car-intelligence.iam.gserviceaccount.com`

Verified auth-test:
- Run: https://github.com/nycguy/collector-car-intelligence-runner/actions/runs/45027018459
- Identity exchange and service-account impersonation: passed
- Source: Google Sheets
- Input rows: 28,058
- Publication sheet: `Sprint 25 Auth Test`
- Publication rows: 16
- Readback: verified
- Input SHA-256: `21c5458f814bc8ea05450ea27394d056070fa0eee72ce56341bfccd31e470d98`

The workflow uses repository variables `GCP_WORKLOAD_IDENTITY_PROVIDER` and `GCP_SERVICE_ACCOUNT`. Production runs remain restricted to `main`. No JSON keys, OAuth tokens, additional connectors, billing resources, or additional repositories were created.

An auth test is not valuation evidence. The production output remains exploratory because the legacy engine lacks full adjustments and validated forecasts. Do not accept Sprint 25 analytically or dispatch Sprint 26 on the basis of authentication alone.
