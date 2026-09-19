# Delivery and deployment status

## Configured

The CI workflow verifies PRs and every `main` push. Only the trusted `main` publish job receives `packages: write`, and it runs after the same commit's aggregate `ci-gate`. It publishes API/admin images tagged with the full commit SHA and records digests in the Actions summary. PR builds never log in or push.

`deploy/compose.staging.yaml` is a mock-only blueprint that requires immutable image references and a staging-only database password. It has no host ports, domain, ingress, admin authentication, or production profile.

## BLOCKED: staging deployment

No staging host, domain/TLS, access-control design, secret store, backup target, or owner-provided credentials exist. Therefore no deploy job is enabled and no environment is claimed deployed. GHCR publication is artifact delivery only.

To unblock NSB-030 later, Nyan must choose/provide the staging target and secret mechanism. The release plan must then verify the exact image digest, add authenticated ingress, serialize deploys, run safe migrations, health-check, log the release, and document rollback. Production deployment remains out of scope.
