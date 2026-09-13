# Security Policy

## Supported version

Only the latest commit on `master` receives security fixes. Deployments must
also pass the repository security workflow against the exact image digest that
will be released.

## Reporting a vulnerability

Do not open a public issue containing credentials, host addresses, process
command lines, or exploit details. Contact the repository owner privately and
include:

- affected commit/image digest;
- reproduction steps using non-production data;
- impact and any known indicators of compromise;
- a secure way to contact the reporter.

Rotate exposed credentials immediately. If a credential-encryption key may be
compromised, retain the old key only long enough to re-encrypt stored SSH/BMC,
MFA, and Webhook values with the new primary key.

## Release security gates

- TLS is mandatory outside loopback; ports 8300 and 3306 must not be public.
- `pip-audit`, `pnpm audit`, Bandit, Ruff, tests, secret scan, and image scan pass.
- High/Critical image findings require remediation or a documented,
  time-bounded exception approved by the system owner.
- Backup restore and SSH host-key persistence are exercised in staging.

## Audit history

- `AUDIT_2026-09-13.md` — security and interaction audit: findings, dispositions,
  verification evidence, and the items intentionally left for a human decision.
- `CODE_REVIEW.md` — 2026-08-29 full-stack code review.

## Owner-approved exceptions (2026-09-13)

These deliberately relax the gates above; each is reversible in `.env` plus
`docker compose up -d`.

| Setting | Value | Consequence | Revert when |
|---|---|---|---|
| `ports` | `8300:8000` (all interfaces) | Lab users reach the console directly; source IPs are preserved, so `TRUSTED_PROXY_CIDRS=172.24.0.1/32` still keeps `X-Forwarded-For` unspoofable from the LAN | A TLS reverse proxy fronts the service |
| `ALLOW_INSECURE_HTTP` | `yes` | Login over plain HTTP is accepted; credentials cross the lab network unencrypted. With `no`, every `http://` Origin is rejected as cross-site and nobody can sign in | TLS is terminated in front of the app |
| `REQUIRE_ADMIN_MFA` | `no` | Admins are not forced to enrol TOTP, and admin endpoints no longer require a verified second factor | Any admin account is worth protecting with a second factor |
