# 四面体 · Harness 调度 SOP

> 模块路径: `harness/src/tetra_harness/scheduling/`
> 配置: `harness/configs/schedule.yaml`
> 状态库: `data/scheduler.db` (APScheduler) · `data/dlq.sqlite` · `data/idempotency.sqlite`

## 1. 架构总览

| 组件 | 责任 | 持久化 |
|------|------|--------|
| `scheduler.TetraScheduler` | APScheduler AsyncIO 包装 | `data/scheduler.db` (SQLAlchemyJobStore) |
| `jobs` | 6 内置 cron 任务 | manifest + cost_tracker |
| `dlq.DLQ` | 失败任务持久化 + 5 次指数退避 | `data/dlq.sqlite` + `data/dlq.jsonl` (审计) |
| `idempotency.IdempotencyStore` | 幂等键 (Redis 优先, SQLite 兜底) | Redis or `data/idempotency.sqlite` |

## 2. 启动

### 2.1 单机
```python
import asyncio
from tetra_harness.scheduling.scheduler import load_from_yaml
from tetra_harness.scheduling.jobs import dlq_retry_worker

async def main():
    s = load_from_yaml("harness/configs/schedule.yaml")
    s.add_interval_job(dlq_retry_worker, seconds=60, job_id="dlq_retry")
    await s.start()
    # 让 event loop 跑下去 (生产用 systemd 或 Docker entry)
    while True:
        await asyncio.sleep(3600)

asyncio.run(main())
```

### 2.2 分布式 (多节点)
APScheduler 不天然支持多 master, 推荐:
- **方案 A**: 单 leader 节点 (推荐) — 跑 SQLAlchemyJobStore 持久化, 故障转移用 systemd auto-restart
- **方案 B**: 接 Celery beat — `add_pipeline_job` 改成 enqueue Celery task

## 3. cron 表达式

支持 5 段 (兼容标准 cron) 或 6 段 (秒级):

```
m h dom mon dow            # 5 段
s m h dom dow              # 6 段 (秒在最前)
```

| 表达式 | 含义 |
|--------|------|
| `30 23 * * *` | 每天 23:30 |
| `0 * * * *` | 每小时整点 |
| `*/30 * * * *` | 每 30 分钟 |
| `0 9 * * 1` | 每周一 09:00 |
| `0 0 1 * *` | 每月 1 号 0 点 |
| `*/15 9-18 * * 1-5` | 工作日 9-18 点 每 15 分钟 |
| `0 0 9 * * *` | 6 段, 每天 09:00:00 |

时区默认 `Asia/Shanghai` (UTC+8).

## 4. 6 个内置 job

| job_id | cron | 做啥 |
|--------|------|------|
| `daily_intel_collect` | `30 23 * * *` | 跑 content pipeline → select_topic 阶段 (社媒选题数据收集) |
| `hourly_compliance_scan` | `0 * * * *` | compliance validator (USDT/Fair Work/Stripe 红线) |
| `hourly_secret_scan` | `5 * * * *` | secret_scanner validator (API key/私钥泄漏) |
| `daily_cost_report` | `0 9 * * *` | 昨日 LLM 成本报告 → 钉钉推送 |
| `weekly_audit_report` | `0 9 * * 1` | 每周一全量 audit + JSON 报告 |
| `half_hour_orphan_settle` | `*/30 * * * *` | 扫超时未结算订单 (默认关, 上线手开) |

## 5. 失败重试 + DLQ

每个 job 失败时:
1. 走 `alerter.send` 钉钉/飞书告警
2. 入 `dlq.DLQ` (job_name + payload + error)
3. `dlq_retry_worker` 每分钟扫到期重试

退避梯度 (分钟):
```
1 → 5 → 30 → 120 → 1440
```
共 5 次, 之后 `mark_dead` 进永久失败队列, 等人工介入.

dashboard 看死信:
```python
from tetra_harness.scheduling.dlq import DLQ
print(DLQ().count())                     # {"total": ..., "pending": ..., "dead": ...}
for it in DLQ().list_dead():             # 永久失败列表
    print(it.id, it.job_name, it.error)
```

## 6. 幂等

订单结算 / 短信 / 外部回调入口必须用:
```python
from tetra_harness.scheduling.idempotency import IdempotencyStore

store = IdempotencyStore()    # 读 REDIS_URL, 没就 SQLite

if store.check_and_set(f"settle:order:{order_id}", ttl=86400):
    do_settle(order_id)
else:
    log.info("订单 %s 24h 内已结算, skip", order_id)
```

## 7. pre-commit SOP

### 装
```bash
pip install pre-commit
pre-commit install            # 装 .git/hooks/pre-commit
pre-commit install -t pre-push   # 同时装 pre-push 钩子 (跑 pytest)
```

### 跳过 (慎用)
```bash
SKIP=tetra-pytest git commit -m "wip"          # 跳单条
git commit --no-verify -m "emergency"          # 全跳过 (PR 评审会拦)
```

### 钩子清单
| hook | 触发时机 | 责任 |
|------|----------|------|
| trailing-whitespace / end-of-file-fixer / check-yaml/json/toml | pre-commit | 基础卫生 |
| check-added-large-files (2MB) | pre-commit | 防大文件 |
| detect-private-key | pre-commit | 防私钥泄漏 |
| ruff (--fix) + ruff-format | pre-commit | Python lint+format |
| mypy (harness/src/) | pre-commit | 静态类型 |
| bandit (harness/src/) | pre-commit | Python 安全扫描 |
| **tetra-audit** | pre-commit | `python harness/audit.py` 必须 145✓ |
| **tetra-pytest** | pre-push | `pytest -x` 必须全过 |

## 8. CI 扩展

Coding CI (`ops/deploy/coding-cicd.yml`) 已加 `audit` 阶段:
```
lint → audit → test → build → deploy → notify
```

`audit-harness` 跑:
- `tetra audit --report`
- `tetra doctor`
- `harness/audit.py --strict`

`test-harness` 跑:
- `pytest --cov=tetra_harness --cov-report=xml`
- 上传 cobertura coverage 报告 + htmlcov artifacts

不接 GitHub Actions / Travis (国外不稳, 国内被墙). 备选:
- Gitee Go (`.workflow/main.yml`)
- 极狐 GitLab CI (`.gitlab-ci.yml`)
- 阿里云云效流水线

## 9. 观测

每个 job 完成时自动:
- `metrics.incr("scheduler_pipeline_ok_total", labels={"pipeline": ...})`
- `manifest.update("scheduled", "done"|"failed", ...)`
- 失败走 `alerter.send` 钉钉

dashboard 集成 (后续接):
- Prometheus 抓 `/metrics` (observability.health 暴露)
- Grafana 面板看 job 成功率/耗时分布

## 10. 故障排查

| 现象 | 排查 |
|------|------|
| job 没跑 | `s.list_jobs()` 看 next_run_time / `data/scheduler.db` 是否存在 |
| 重复跑 | 检查 `max_instances` (默认 1) + idempotency key |
| DLQ 堆积 | `DLQ().list_pending()` + `list_dead()` 看 error 字段 |
| pre-commit 卡住 | `SKIP=tetra-pytest` 跳 pytest 钩子 |
| Redis 不可达 | IdempotencyStore 自动降级 SQLite, log 一行 warning |
