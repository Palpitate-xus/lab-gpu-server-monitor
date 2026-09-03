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
