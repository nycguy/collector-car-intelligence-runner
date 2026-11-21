# Google Actions authorization

The runner is designed for keyless GitHub OIDC authentication. Configure a Google Cloud Workload Identity Pool/provider for repository `nycguy/collector-car-intelligence-runner`, restricted to the approved branch or `main), and create a dedicated service account with only:

- `roles/iam.workloadIdentityUser` granted to the repository-bound principal
- access to the target spreadsheet as an Editor, not broad Drive access
- the Sheets API enabled

Store only these two non-credential configuration values as GitHub Actions secrets:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`: full provider resource name
- `GCP_SERVICE_ACCOUNT`: dedicated service-account email

Do not upload a JSON key. Do not put a private key, refresh token, or transaction export in GitHub. The workflow deletes the temporary credentials file after the job. The exact Google Cloud project and account must be selected by the owner because the connected Work identity cannot create or delegate a GitHub-trusted Google Cloud identity in this environment.
