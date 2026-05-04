# Changelog

All notable changes to this project are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-05-04

### Added

- Initial public release.
- Three-layer harness: `agents/`, `validators/`, `pipelines/`.
- CLI (`sitige`) for run / status / replay.
- FastAPI server with REST + WebSocket surface.
- APScheduler-backed scheduling with idempotency keys and dead-letter queue.
- Observability: Prometheus metrics, OpenTelemetry traces, health probes, DingTalk / WeCom alerter.
- Storage abstraction over SQLAlchemy + Alembic; pluggable artifact store (local / Qiniu / Aliyun OSS / Tencent COS).
- Reference pipelines: `content`, `compliance`, `recruit`, `crm`, `match`.
- Quality gates: ruff, mypy, bandit, pytest with coverage floor.
- Bilingual README (English + 中文).

### Notes

Extracted from a private production codebase. The internal harness predates this release; v0.1.0 corresponds to the first public-facing snapshot.
