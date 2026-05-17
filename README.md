# sitige-harness

Python runtime for business-automation pipelines. It runs YAML-declared
pipelines from a `sitige` CLI, persists artifacts to disk and Postgres, and
exposes run status over FastAPI. Extracted from an e-sports player-recruit
and content-review system that runs five pipelines in production.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Status](https://img.shields.io/badge/status-beta-orange)

[Chinese README](README.zh-CN.md)

## sitige-harness vs harness-engineering

[harness-engineering](https://github.com/lfzds4399-cpu/harness-engineering) is
a written-down pattern. It is an architecture doc — there is nothing to
install. This repo is one runtime that implements the pattern as a Python
package. `pip install -e .` gives you the `sitige` CLI, a FastAPI surface,
APScheduler scheduling, Alembic migrations, Prometheus counters, and five
reference pipelines already wired up against the layout.

Read the pattern doc when you want to know why the runtime looks this way.
Clone this repo when you want code you can fork and run.

## Layers

The runtime is organized into three directories:

```text
agents/       call external services or generate business output
validators/   deterministic checks: secrets, pricing, schema, policy, files
pipelines/    ordered stages with retries, idempotency, artifacts, status
```

A pipeline is declared in YAML under `configs/`. Stages reference agents
and validators by name. The CLI runs the pipeline, persists artifacts under
`var/`, and reports run state through FastAPI endpoints.

## Features

- CLI commands for running pipelines, checking status, and replaying runs.
- Async agents, validators, and pipeline stages.
- Prometheus metrics, OpenTelemetry traces, health probes, alert hooks.
- APScheduler jobs, idempotency keys, dead-letter queue.
- SQLAlchemy with Alembic migrations. Redis cache. Pluggable artifact
  storage (local, Qiniu, Aliyun OSS, Tencent COS).
- Ruff, mypy, bandit, and pytest configuration in `pyproject.toml`.
- FastAPI surface for pipelines, runs, manifests, REST plus WebSocket.

## Quick start

```bash
git clone https://github.com/lfzds4399-cpu/sitige-harness.git
cd sitige-harness
pip install -e ".[dev,api,observability,scheduling,storage]"

cp .env.example .env
sitige --help
sitige run content --dry-run
```

Fill provider keys only for the pipelines you actually run. The
`content` and `compliance` pipelines need `DEEPSEEK_API_KEY` (or another
LLM provider). `recruit`, `crm`, and `match` run without LLM credentials.

## Included pipelines

The five reference pipelines come from the original e-sports use case:
recruiting players, reviewing AIGC marketing content, and matching
customers to services.

| Pipeline | Purpose |
|---|---|
| `content` | Topic, script draft, AIGC prompt draft, compliance review, publish brief. |
| `compliance` | Content audit returning allow, warn, or block. |
| `recruit` | Channel scan, outreach, KYC, deposit, contract. |
| `crm` | Customer lifecycle stages and retention probes. |
| `match` | Service matching and ranking. |

Each pipeline lives in `src/tetra_harness/pipelines/` with a YAML manifest
in `configs/`. Pipelines are domain-agnostic — fork them, replace them, or
add new ones for any business workflow.

## Project layout

```text
src/tetra_harness/
  agents/         actions that hit external services or run an LLM call
  validators/     deterministic gates
  pipelines/      stage orchestration
  api/            FastAPI server, REST plus WebSocket
  scheduling/     APScheduler, idempotency, dead-letter queue
  observability/  metrics, tracing, health, alerts
  storage/        DB, cache, artifacts, secrets
  manifest.py     YAML pipeline declaration
  cli.py          sitige entry point
  config.py       environment-aware settings

alembic/          DB migrations
configs/          pipeline manifests
docs/             API, observability, pipelines, scheduling, storage
tests/            pytest suite
```

## Documentation

- [Pipelines](docs/PIPELINES.md)
- [API](docs/API.md)
- [Observability](docs/OBSERVABILITY.md)
- [Scheduling](docs/SCHEDULING.md)
- [Storage](docs/STORAGE.md)

## Status

Beta. The harness has been running the e-sports pipelines for months. The
public surface — CLI flags and manifest schema — may still shift before
1.0. Pin a minor version if you build on top of it.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). For security issues, see
[SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
