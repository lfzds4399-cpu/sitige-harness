# sitige-harness

> [harness-engineering](https://github.com/lfzds4399-cpu/harness-engineering) pattern 的一个 runtime 实现 — async Python，FastAPI，APScheduler，Alembic。agents / validators / pipelines 三层组合，CLI 驱动，全自动可观测。
> 从一个生产中的电竞业务自动化系统抽出来开源。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Status](https://img.shields.io/badge/status-beta-orange)

[English README](README.md)

## sitige-harness 跟 harness-engineering 什么区别

[harness-engineering](https://github.com/lfzds4399-cpu/harness-engineering) 是 pattern 文档（架构说明，不可 install）。`sitige-harness` 是这个 pattern 的一个可装 Python package 实现 — `pip install -e .` 就有 `sitige` CLI、FastAPI 接口、APScheduler 调度、Alembic 迁移、Prometheus 指标，加 5 条 reference pipeline 全接线。想懂"为什么这么写"读 pattern 文档；想要可跑的 starter 直接 fork 本仓库。

## 这是什么

一个三层 harness，用来稳定地把"业务流水线"工程化：

```
agents/      ← LLM 驱动的行为（合规审、内容产、招募触达……）
validators/  ← 纯函数门（敏感词、定价规则、schema 校验……）
pipelines/   ← 编排 stage，自带重试 / DLQ / 幂等 / 观测
```

一条 pipeline 在 YAML manifest 里声明 — 列 stage、它们的 validator、超时。CLI 跑它，持久化产物，把 `/status` `/runs` `/manifest` 经 FastAPI 暴露出去。

## 为什么

业务自动化项目崩盘的常见原因：每个脚本各自滚一份重试 / 日志 / 配置 / 指标缠在一起的代码。这个 harness 把这些公共件给你，**你只写真正的 agent 或 validator**。

## 特性

- **CLI 驱动** — `sitige run <pipeline>`、`sitige status`、`sitige replay <run>`
- **Async-native** — pipeline / agent / validator 全 `async`
- **可观测** — Prometheus 指标、OpenTelemetry trace、health probe、alerter（钉钉 / 企微）
- **调度** — APScheduler、幂等 key、死信队列（DLQ）
- **存储抽象** — SQLAlchemy + Alembic 迁移、Redis 缓存、可插拔产物存储（本地 / 七牛 / 阿里 OSS / 腾讯 COS）
- **质量门** — pyproject 自带 ruff + mypy + bandit + pytest 配置，覆盖率底线
- **HTTP API** — FastAPI 服务把 pipeline / run / manifest 经 WebSocket + REST 暴露

## 快速开始

```bash
git clone https://github.com/lfzds4399-cpu/sitige-harness.git
cd sitige-harness
pip install -e ".[dev,api,observability,scheduling,storage]"

cp .env.example .env
# 至少填一个 LLM provider（推荐 DEEPSEEK_API_KEY，性价比高）

sitige --help
sitige run content --dry-run
```

## 内置 pipeline

参考 pipeline 来自原电竞业务用例：

| Pipeline | 作用 |
|---|---|
| `content`    | 选题 → 脚本 → AIGC prompt → 合规审 → 发布 brief |
| `compliance` | LLM 驱动内容合规审核（allow / warn / block） |
| `recruit`    | 渠道扫描 → 触达 → KYC → 押金 → 签约 |
| `crm`        | 客户生命周期 + 留存探针 |
| `match`      | 服务匹配评分 + 排序 |

每条 pipeline 在 `src/tetra_harness/pipelines/` 下，配 `configs/` 里的 YAML manifest。你可以照搬、fork 或自己写新的 — framework 不关心你做的是什么业务。

## 项目结构

```
src/tetra_harness/
├── agents/         # LLM 驱动行为
├── validators/     # 确定性门
├── pipelines/      # Stage 编排
├── api/            # FastAPI 服务（REST + WebSocket）
├── scheduling/     # APScheduler + DLQ + 幂等
├── observability/  # 指标 / trace / 健康 / 告警
├── storage/        # DB / 缓存 / 产物 / 凭证
├── manifest.py     # YAML 驱动 pipeline 声明
├── cli.py          # `sitige` 入口
└── config.py       # env-aware 配置

alembic/            # DB 迁移
configs/            # Pipeline YAML 配置
docs/               # API / OBSERVABILITY / PIPELINES / SCHEDULING / STORAGE
tests/              # pytest 套件
```

## 文档

- [Pipelines](docs/PIPELINES.md) — stage / agent / validator 怎么组合
- [API](docs/API.md) — FastAPI 接口
- [Observability](docs/OBSERVABILITY.md) — 指标、trace、告警
- [Scheduling](docs/SCHEDULING.md) — APScheduler、幂等、DLQ
- [Storage](docs/STORAGE.md) — DB / 缓存 / 产物

## 状态

**Beta**。harness 已在一个真实业务里跑了几个月 — 但公共面（CLI 参数、manifest schema）在 1.0 前可能还会变。如要在上面建系统，请锁定 minor 版本。

## 贡献

欢迎 PR。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题见 [SECURITY.md](SECURITY.md)。

## License

MIT — 见 [LICENSE](LICENSE)。
