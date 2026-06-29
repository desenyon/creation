# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.6.x   | Yes       |

## Reporting a vulnerability

Please report security issues **privately** via [GitHub Security Advisories](https://github.com/desenyon/creation/security/advisories/new) rather than opening a public issue.

Include:

- Description of the vulnerability
- Steps to reproduce
- Impact assessment
- Suggested fix (if any)

We aim to acknowledge reports within 72 hours.

## Scope

Creation runs locally. Sensitive data (Account credentials, Relay tokens, Prism memory) is stored under `~/.creation/`. Do not commit `.env` files or API keys.
