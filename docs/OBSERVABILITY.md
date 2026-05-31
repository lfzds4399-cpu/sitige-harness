# sitige-harness · Observability SOP

Default stack: **Prometheus + Grafana + OpenTelemetry**. Alerting via webhook to any chat/email provider (DingTalk / WeCom / Slack / Lark / SMTP all supported).

## 0. 总览

| 层 | 工具 | 模块 |
|---|---|---|
| 指标 | Prometheus + Grafana | `observability/metrics.py` |
| 健康端点 | FastAPI APIRouter | `observability/health.py` |
| 链路追踪 | OpenTelemetry exporter (OTLP) | `observability/tracing.py` |
| 告警 | DingTalk / WeCom / Slack / SMTP | `observability/alerter.py` |

配置: `configs/observability.yaml`
Grafana dashboard: `configs/grafana-dashboard.json` (12 panel)

## 1. 装依赖

```bash
# 进 harness 目录
pip install prometheus-client fastapi uvicorn \
    opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc \
    opentelemetry-instrumentation-httpx
```

注: 这些是 **可选依赖**. 没装时 metrics/tracing/health 都退化为 noop, 不会报错.

## 2. 接入 — 给 api agent 挂 health router

```python
# api/main.py (api agent 维护, observability 不动)
from fastapi import FastAPI
from tetra_harness.observability.health import router as obs_router, register_check
from tetra_harness.observability.tracing import init_tracing

# 1) 启动时初始化 tracing
init_tracing(service_name="tetra-bot", exporter="otlp")

# 2) 注册 readiness 探活
async def check_redis() -> tuple[bool, str]:
    try:
        await redis.ping()
        return True, "ok"
    except Exception as e:
        return False, str(e)

register_check("redis", check_redis)
register_check("postgres", check_postgres)
register_check("llm:openai", check_openai)

# 3) 挂 router (前缀建议 /_obs 避免和业务路由冲突)
app = FastAPI()
app.include_router(obs_router, prefix="/_obs", tags=["observability"])
```

端点:
- `GET /_obs/healthz` — 200 = 进程在
- `GET /_obs/readyz`  — 200/503 = 依赖齐/不齐
- `GET /_obs/metrics` — Prometheus 文本
- `GET /_obs/info`    — 版本/构建/启动时间

## 3. 业务侧埋点

### 3.1 装饰器三件套

```python
from tetra_harness.observability.metrics import (
    track_pipeline, track_agent, track_validator,
)

@track_pipeline("content")
async def run_content_pipeline(ctx, cfg): ...

@track_agent("match")
async def call_match_agent(payload): ...

@track_validator("compliance")
def validate_compliance(root): ...
```

装饰器自动收集 runs / duration / failures, 不用手 inc.

### 3.2 LLM 客户端集成

```python
from tetra_harness.observability.metrics import record_llm_usage, record_llm_error

# 在 utils/llm_client.py 调用结束后
record_llm_usage(
    provider="openai", model="gpt-4o-mini",
    tokens_in=resp.usage.prompt_tokens,
    tokens_out=resp.usage.completion_tokens,
    cost_usd=cost,
)
# 出错
record_llm_error(provider="openai", code="5xx")
```

### 3.3 业务指标 (订单/活跃用户)

```python
from tetra_harness.observability.metrics import (
    record_order, record_match_latency, set_active_counts,
)

record_order("created")
record_order("matched")
record_match_latency(seconds=45.2)
set_active_counts(partners=12, masters=87)  # cron 每 5 分钟刷新一次
```

## 4. 装 Prometheus + Grafana (本地 docker-compose)

把下面追加到 `ops/deploy/docker-compose.yml` (ops agent 维护):

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    ports: ["9091:9090"]
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    ports: ["3000:3000"]
    environment:
      GF_SECURITY_ADMIN_PASSWORD: tetra2026
    volumes:
      - grafana_data:/var/lib/grafana
    restart: unless-stopped

volumes:
  grafana_data:
```

`prometheus.yml`:

```yaml
global: { scrape_interval: 15s }
scrape_configs:
  - job_name: tetra-harness
    metrics_path: /_obs/metrics
    static_configs:
      - targets: ["host.docker.internal:9090"]   # 改成 api agent 实际端口
```

启动:

```bash
docker compose up -d prometheus grafana
```

打开 `http://localhost:3000` (admin / tetra2026), 加 Prometheus 数据源 (URL `http://prometheus:9090`), 然后 Dashboard → Import → 上传 `harness/configs/grafana-dashboard.json`.

## 5. 链路追踪 — 阿里 ARMS / 腾讯 APM

### 5.1 阿里云 ARMS

1. 控制台 → 应用监控 → 接入应用 → Python OpenTelemetry
2. 拷接入点 (示例 `http://tracing-analysis-dc-hz.aliyuncs.com:8090`)
3. 设环境变量:

```bash
export OTEL_EXPORTER=otlp
export OTEL_OTLP_ENDPOINT=http://tracing-analysis-dc-hz.aliyuncs.com:8090
export OTEL_SERVICE_NAME=tetra-harness
export OTEL_SAMPLE_RATE=0.1
```

4. 启动后 5 分钟内, ARMS 就能看到 trace.

### 5.2 腾讯云 APM

1. 控制台 → 应用性能监控 APM → 接入指引 → OpenTelemetry / Python
2. 接入点 `http://apm.tencentcs.com:55681` + token (Header)
3. token 通过 `OTEL_EXPORTER_OTLP_HEADERS=Authentication=<token>` 注入

### 5.3 业务侧手动 span

```python
from tetra_harness.observability.tracing import start_span, traced

@traced("order.dispatch")
async def dispatch_order(order): ...

with start_span("custom.heavy_calc", order_id=order.id) as span:
    span.set_attribute("partner_count", n)
    do_work()
```

## 6. 告警通道

### 6.1 钉钉机器人

1. 企业群 → 设置 → 智能群助手 → 添加机器人 → 自定义
2. 安全设置 **必须勾"加签"** (单纯关键字过滤防垃圾)
3. 拿到 `webhook` 和 `secret`, 写入环境:

```bash
export DINGDING_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=xxx"
export DINGDING_SECRET="SECxxxxxxxxxxxxxxxxxxxxxxxx"
```

加签算法 (代码里已封装):

```
ts = millis()
str_to_sign = f"{ts}\n{secret}"
sign = urlencode(base64(HMAC-SHA256(secret, str_to_sign)))
url = f"{webhook}&timestamp={ts}&sign={sign}"
```

### 6.2 飞书机器人

1. 群设置 → 群机器人 → 添加机器人 → 自定义机器人
2. 安全设置勾"签名校验" (推荐), 拿 webhook + secret

```bash
export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
export FEISHU_SECRET="xxxxxxxxxxxxxxxxxxxxx"
```

### 6.3 阿里云邮件推送

1. 控制台 → 邮件推送 → 新建发信地址
2. 控制台 → SMTP 密码生成 (区别于阿里云账号密码)
3. 环境变量:

```bash
export ALIYUN_MAIL_HOST=smtpdm.aliyun.com
export ALIYUN_MAIL_PORT=465
export ALIYUN_MAIL_USER=alert@mail.example.com
export ALIYUN_MAIL_PASS=xxx
export ALIYUN_MAIL_SENDER=alert@mail.example.com
```

### 6.4 多通道触发

```python
import os
from tetra_harness.observability.alerter import (
    DingdingAlerter, FeishuAlerter, EmailAlerter, CompositeAlerter,
)

alerter = CompositeAlerter(channels=[
    DingdingAlerter(),                                    # 主
    FeishuAlerter(),                                      # 备
    EmailAlerter(to=["ops@example.com"]),                 # 邮件兜底
])

await alerter.send("error", "Pipeline 失败",
                   "content_pipeline @ stage=script · 详情见 /readyz")
```

### 6.5 阈值规则

| 指标 | 阈值 | level | 通道 |
|---|---|---|---|
| LLM 成本 1h | >$5 | warn | 飞书 |
| Pipeline 失败率 15m | >10% | error | 钉钉 |
| Validator error 单次 | >50 | critical | 钉钉@all |
| 订单堆积未派 | >100 | warn | 钉钉 |

阈值由 `configs/observability.yaml` 提供, 业务定时跑 `evaluate_thresholds()` 拿候选告警发出.

## 7. 排错

### 7.1 metrics 端点空白

- 检查 `prometheus_client` 是否装: `python -c "import prometheus_client"`
- 端点是否挂上: `curl http://localhost:9090/_obs/metrics | head`
- 装饰器是否生效: 手动跑一次 pipeline, 再看端点

### 7.2 tracing 不上报

- `OTEL_EXPORTER=otlp` 但端点不通 → 自动 fallback 到 console
- 检查 `OTEL_OTLP_ENDPOINT` 是否含 `http://` 前缀
- ARMS 默认要 5 分钟才能看到首条 trace
- 单测/CI 强制 `OTEL_EXPORTER=disable`

### 7.3 钉钉发不出来

- `errcode=310000` → secret 不匹配, 重新加签
- `errcode=310000 sign not match` → 时间戳与服务器差 >1h, 校时
- 关键字模式不要勾, 用加签更稳
- 同一机器人 1 分钟内最多 20 条, 告警高峰建议合并

### 7.4 飞书 StatusCode != 0

- `19021` → IP 白名单 / 加签失败
- 公司网络代理拦截外网 → 走内网代理或换钉钉

### 7.5 邮件发不出

- 阿里云邮件推送的密码 ≠ 阿里云登录密码, 是 SMTP 专用密码
- 默认要绑定域名解析 SPF/DKIM, 否则进垃圾箱
- 25 端口在阿里云被封, 必须用 465 (SSL) 或 587

## 8. 跑测试

```bash
cd harness
pip install pytest pytest-asyncio
pytest tests/test_observability.py -x -v
```

测试覆盖: stub fallback / 装饰器 / readiness / 钉钉加签 / 阈值判定.
