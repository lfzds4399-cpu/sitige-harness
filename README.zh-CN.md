# sitige-harness

业务自动化流水线的 Python runtime。用 `sitige` CLI 跑 YAML 声明的
pipeline，把产物落盘并写入 Postgres，把 run 状态从 FastAPI 暴露。
从一个真实的电竞业务系统（选手招募 + AIGC 内容合规审核）抽出来开源，
原系统在生产里跑了 5 条 pipeline 几个月。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Status](https://img.shields.io/badge/status-beta-orange)

[English README](README.md)

## sitige-harness 跟 harness-engineering 什么区别

[harness-engineering](https://github.com/lfzds4399-cpu/harness-engineering)
是写下来的 pattern。它是一份架构文档，没东西可装。本仓库是这个 pattern
的一个 runtime 实现，作为 Python 包发布。`pip install -e .` 装完就有
`sitige` CLI、FastAPI 接口、APScheduler 调度、Alembic 迁移、Prometheus
指标，加 5 条 reference pipeline 全部按 layout 接好线。

想懂"为什么这么写"读 pattern 文档；想要可跑可 fork 的代码 clone 本仓库。

## 分层

runtime 分三个目录：

```text
agents/       调外部服务或产业务输出
validators/   确定性检查：敏感词、定价、schema、合规、文件
pipelines/    编排 stage，带重试、幂等、产物、状态
```

每条 pipeline 在 `configs/` 下用 YAML 声明，stage 按名字引用 agent 和
validator。CLI 跑 pipeline，把产物存到 `var/`，把 run 状态从 FastAPI
端点报出去。

## 特性

- CLI 跑 pipeline、查状态、回放。`sitige run / status / replay`。
- pipeline、agent、validator 全部 async。
- Prometheus 指标、OpenTelemetry trace、health probe、告警 hook。
- APScheduler 调度，幂等 key，死信队列。
- SQLAlchemy 加 Alembic 迁移。Redis 缓存。可插拔的产物存储
  （本地、七牛、阿里 OSS、腾讯 COS）。
- pyproject 里带 ruff、mypy、bandit、pytest 配置。
- FastAPI 把 pipeline、run、manifest 经 REST 加 WebSocket 暴露。

## 快速开始

```bash
git clone https://github.com/lfzds4399-cpu/sitige-harness.git
cd sitige-harness
pip install -e ".[dev,api,observability,scheduling,storage]"

cp .env.example .env
sitige --help
sitige run content --dry-run
```

只给你真的要跑的 pipeline 填 key 就行。`content` 和 `compliance`
要 `DEEPSEEK_API_KEY`（或其它 LLM provider）。`recruit`、`crm`、
`match` 不用 LLM 凭证。

## 内置 pipeline

5 条 reference pipeline 来自原电竞业务用例：选手招募、AIGC 营销
内容审核、客户跟服务的匹配。

| Pipeline | 作用 |
|---|---|
| `content` | 选题、脚本草稿、AIGC prompt 草稿、合规审、发布 brief。 |
| `compliance` | 内容合规审，返回 allow、warn 或 block。 |
| `recruit` | 渠道扫描、触达、KYC、押金、签约。 |
| `crm` | 客户生命周期阶段 + 留存探针。 |
| `match` | 服务匹配评分 + 排序。 |

每条 pipeline 放在 `src/tetra_harness/pipelines/` 下，配 `configs/`
里的 YAML manifest。你可以照搬、fork 或写自己的 — framework 不关心
你做的是什么业务。

## 项目结构

```text
src/tetra_harness/
  agents/         调外部服务或跑 LLM 的行为
  validators/     确定性门
  pipelines/      stage 编排
  api/            FastAPI 服务，REST 加 WebSocket
  scheduling/     APScheduler、幂等、死信队列
  observability/  指标、trace、健康、告警
  storage/        DB、缓存、产物、凭证
  manifest.py     YAML 驱动 pipeline 声明
  cli.py          sitige 入口
  config.py       env-aware 配置

alembic/          DB 迁移
configs/          pipeline 配置
docs/             API、observability、pipelines、scheduling、storage
tests/            pytest 套件
```

## 文档

- [Pipelines](docs/PIPELINES.md)
- [API](docs/API.md)
- [Observability](docs/OBSERVABILITY.md)
- [Scheduling](docs/SCHEDULING.md)
- [Storage](docs/STORAGE.md)

## 状态

Beta。harness 已经在电竞业务里跑了几个月。公共面（CLI 参数和
manifest schema）在 1.0 前可能还会变。要在上面建系统的话锁定
minor 版本。

## 贡献

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题见 [SECURITY.md](SECURITY.md)。

## License

MIT。见 [LICENSE](LICENSE)。
