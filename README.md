# sitige-harness

Python runtime for business automation pipelines. It provides async stages,
validators, manifests, scheduling, storage adapters, a FastAPI status API, and
observability hooks.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Status](https://img.shields.io/badge/status-beta-orange)

[Chinese README](README.zh-CN.md)

## What this is

The runtime is organized into three layers:

```text
agents/       actions that call external services or generate business output
validators/   deterministic checks for secrets, pricing, schema, policy, and files
pipelines/    ordered stages with retries, idempotency, artifacts, and status
```

A pipeline is declared in YAML. The CLI runs it, persists artifacts, and exposes
run status over FastAPI.

## Features

- CLI commands for running pipelines, checking status, and replaying runs.
- Async agents, validators, and pipeline stages.
- Prometheus metrics, OpenTelemetry traces, health probes, and alert hooks.
- APScheduler jobs, idempotency keys, and a dead-letter queue.
- SQLAlchemy, Alembic migrations, Redis cache, and pluggable artifact storage.
- Ruff, mypy, bandit, and pytest configuration.
- FastAPI surface for pipelines, runs, manifests, REST, and WebSocket updates.

## Quick start

```bash
git clone https://github.com/lfzds4399-cpu/sitige-harness.git
cd sitige-harness
pip install -e ".[dev,api,observability,scheduling,storage]"

cp .env.example .env
sitige --help
sitige run content --dry-run
```

Fill provider keys only for pipelines that need them.

## Included pipelines

| Pipeline | Purpose |
|---|---|
| `content` | Topic selection, script draft, prompt draft, compliance review, publish brief. |
| `compliance` | Content compliance audit with allow, warn, or block result. |
| `recruit` | Channel scan, outreach, KYC, deposit, and contract steps. |
| `crm` | Customer lifecycle stages and retention probes. |
| `match` | Service matching and ranking. |

## Project layout

```text
src/tetra_harness/
  agents/         external-service and business actions
  validators/     deterministic gates
  pipelines/      stage orchestration
  api/            FastAPI server
  scheduling/     APScheduler, idempotency, dead-letter queue
  observability/  metrics, tracing, health, alerts
  storage/        DB, cache, artifacts, secrets
  manifest.py     YAML pipeline declaration
  cli.py          sitige entry point
  config.py       environment-aware settings

alembic/          DB migrations
configs/          pipeline manifests
docs/             API, observability, pipeline, scheduling, storage docs
tests/            pytest suite
```

## Documentation

- [Pipelines](docs/PIPELINES.md)
- [API](docs/API.md)
- [Observability](docs/OBSERVABILITY.md)
- [Scheduling](docs/SCHEDULING.md)
- [Storage](docs/STORAGE.md)

## Status

Beta. CLI flags and manifest schema may still change before 1.0. Pin a minor
version if you build on top of it.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). For security issues, see [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
