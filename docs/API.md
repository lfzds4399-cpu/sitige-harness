# Tetra Harness API

sitige-harness REST + WebSocket API. FastAPI, default port 8002.

## 启动

```bash
cd harness
uvicorn tetra_harness.api.server:app --port 8002 --reload
```

OpenAPI 自动文档: <http://localhost:8002/docs>.

## 鉴权

- 单 admin token (env `TETRA_ADMIN_TOKEN`).
- 客户端 header: `Authorization: Bearer <token>` 或 `X-Admin-Token: <token>`.
- env 未配置时为 DEV 模式, 全部放行 (whoami 返 `mode=dev`).
- POST `/api/auth/login` body `{token}` → 200.

## REST

### Pipelines

| Method | Path | 说明 |
| --- | --- | --- |
| GET  | /api/pipelines/ | 列全部 pipeline (name/description/stages) |
| GET  | /api/pipelines/{name} | 单 pipeline 元信息 |
| POST | /api/pipelines/{name}/run | 跑 pipeline (默认 async, 立返 run_id) |
| GET  | /api/pipelines/{name}/runs?limit= | 该 pipeline 历史 runs |
| POST | /api/pipelines/{name}/runs/{run_id}/cancel | 取消 |

```bash
curl -X POST http://localhost:8002/api/pipelines/content/run \
  -H "Authorization: Bearer $TETRA_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"config": {}, "async_mode": true}'
```

### Validators

| Method | Path | 说明 |
| --- | --- | --- |
| GET  | /api/validators/ | 列 9 validator |
| GET  | /api/validators/{name} | 元信息 |
| POST | /api/validators/{name}/run | 立刻跑 (返 ValidationResult) |
| GET  | /api/validators/findings?severity=&validator=&limit= | finding 查询 (内存环) |

```bash
curl -X POST http://localhost:8002/api/validators/secret_scanner/run \
  -H "Authorization: Bearer $TETRA_ADMIN_TOKEN" \
  -H "Content-Type: application/json" -d '{}'
```

### Manifest

| Method | Path | 说明 |
| --- | --- | --- |
| GET | /api/manifest/ | 列 data/ 下 artifact |
| GET | /api/manifest/{artifact} | 单 artifact manifest 全文 |

### Runs (全局)

| Method | Path | 说明 |
| --- | --- | --- |
| GET | /api/runs/?pipeline=&status=&limit= | 全 pipeline run 列表 |
| GET | /api/runs/{run_id} | 单 run 详情 |

### Auth

| Method | Path | 说明 |
| --- | --- | --- |
| POST | /api/auth/login | body `{token}` |
| GET  | /api/auth/whoami | 当前角色 + 模式 (dev/prod) |

### Observability (跨 agent)

由 `tetra_harness.observability.health.router` 挂载在 `/_obs/*`. import 失败时 graceful fallback (api 仍可起).

## WebSocket

实时 pipeline 进度推送:

```
ws://localhost:8002/ws/pipelines/{name}/runs/{run_id}
```

事件 JSON:

```json
{
  "ts": 1714368000.123,
  "run_id": "content-1714368000-abc123",
  "pipeline": "content",
  "stage": "select_topic",
  "status": "running",
  "log": "stage select_topic ok",
  "elapsed_ms": 1234.5,
  "error": null
}
```

- 客户端连上后, 自动 replay 最近 200 条历史事件.
- 客户端可发 `ping` 心跳 (服务端回 `pong`).
- 进程内 broadcast (无 redis); 多 worker 部署需自行接 pub/sub.

## CORS

默认放行 `localhost:3000/3001`. 扩展用 `TETRA_API_CORS=https://x.com,https://y.com`.

## 部署 Dashboard

见 `harness/dashboard/README.md`. 开发 `npm run dev` (3001), 生产 Docker.

## 国产硬约束

- 不引入 cloudflare workers / vercel analytics / GA / Mixpanel / Datadog.
- recharts (轻量, 中性) — 不用 chart.js / d3 / Plotly 海外重型.
- 字体走中科大镜像 fonts.font.im, 不连 Google Fonts.
