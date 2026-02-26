# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| `main` (latest) | ✅ |
| Older pinned versions | ❌ — please upgrade |

## Reporting a Vulnerability

**Please do not report security vulnerabilities via public GitHub issues.**

To report a security issue, use [GitHub's private vulnerability reporting](https://github.com/yhyatt/DMAF/security/advisories/new).

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You'll receive a response within 48 hours. If the issue is confirmed, a fix will be prioritised and a security advisory published.

## Security Considerations

DMAF handles personal media (photos and videos of family members). A few things to be aware of:

- **Reference photos** (`known_people/`) should be stored in a **private** GCS bucket with IAM-controlled access — never committed to version control
- **OAuth tokens** (`token.json`, `client_secret.json`) are gitignored — never commit them
- **Config YAML** contains SMTP credentials — use Secret Manager for cloud deployments, never commit `config.yaml`
- **GCS bucket** containing WhatsApp media should be private with minimal IAM access
- **Firestore** dedup database stores file hashes and paths — ensure project IAM is locked down

## Dependency Security

Dependabot is enabled on this repository and will open PRs for dependency updates automatically.
