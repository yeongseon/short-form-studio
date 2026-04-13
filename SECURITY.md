# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Short Form Studio, please report it responsibly.

**DO NOT** open a public GitHub issue for security vulnerabilities.

### How to Report

1. Email: Send details to the repository maintainers via GitHub's private vulnerability reporting feature
2. Go to the **Security** tab of this repository and click **Report a vulnerability**

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 1 week
- **Fix timeline**: Depends on severity, typically within 30 days for critical issues

### Supported Versions

| Version | Supported |
|---|---|
| Latest on `main` | Yes |
| Older releases | No |

## Security Best Practices for Deployers

- **Always set `API_KEY`** in production — leaving it empty disables authentication
- **Never expose** the API port (8000) directly to the internet without a reverse proxy
- **Use HTTPS** in production via a reverse proxy (nginx, Caddy, etc.)
- **Restrict `CORS_ORIGINS`** to your frontend domain only
- **Keep dependencies updated** — run `pip install --upgrade` and `npm audit` regularly
- **Review `.env`** — never commit secrets to version control
