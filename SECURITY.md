# Security Policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Email: **lfzds4399@gmail.com** with subject prefix `[security] sitige-harness:`.

Include: vulnerable version, repro steps, impact assessment, and your contact preference.

## Response targets

- Acknowledgement: within **72 hours**
- Triage + severity assessment: within **7 days**
- Fix or mitigation plan: within **30 days** for high-severity

## Supported versions

The latest minor version receives security fixes. Older minors are best-effort.

## Hardening checklist for users

- Never commit `.env` — the repo's `.gitignore` excludes it; verify locally with `git check-ignore .env`.
- Rotate LLM API keys quarterly.
- Run `bandit -r src` before deploying custom agents/validators.
- The harness ships with `validators/secret_scanner.py` — wire it into your pipelines that touch external content.
- For production, use Postgres (not SQLite) and put Redis behind auth.
