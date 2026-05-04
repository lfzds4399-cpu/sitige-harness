# 四面体电竞 · harness 存储层 (STORAGE)

`tetra_harness.storage` 提供统一的 db / cache / artifact / secrets 抽象, 业务层一律走它. 国产 cloud 优先, 不依赖 AWS / GCS.

## 模块速览

| 子模块 | 默认实现 | 生产推荐 |
|---|---|---|
| `storage.db` | SQLite (aiosqlite) | PostgreSQL 14+ (asyncpg) |
| `storage.cache` | InMemoryCache | Redis 7 |
| `storage.artifact` | LocalArtifactStore | Qiniu / Aliyun OSS / Tencent COS |
| `storage.secrets` | EnvSecret | SopsSecret / CompositeSecret |

任何上层依赖缺失都会 fallback (Redis 不通 → 内存; OSS 没 key → 本地; sops 没装 → env), 不会让主流程炸.

---

## 1. 数据库 (`storage.db` + `storage.models`)

### 选型
- **dev**: `sqlite+aiosqlite:///data/tetra.db` — 零部署, 单文件, `data/` 自动建.
- **prod**: 腾讯云 PostgreSQL 1C2G ¥40/月 (足够 1k runs/day) 或自建 docker.

环境变量 `TETRA_DB_URL` 覆盖默认.

### Model 关系
```
Run (一次 pipeline 执行)
 ├── Stage (有序阶段) ── Finding (validator 告警)
 │                    └── CostEntry (LLM 费用明细)
 ├── Finding (run 级 finding)
 └── CostEntry (run 级 cost)

User       — CLI / API token holder
AuditLog   — 谁在何时做了什么
```

### 用法
```python
from tetra_harness.storage.db import get_db
from tetra_harness.storage.models import Run

db = get_db()
await db.create_all()  # dev 快速建表

async with db.session() as s:
    run = Run(pipeline="content", status="running", triggered_by="cli")
    s.add(run)
    await s.commit()
```

### Alembic 迁移流程

```bash
cd harness/

# 1. 应用所有迁移 (生产)
alembic upgrade head

# 2. 修改 models.py 后自动生成迁移
alembic revision -m "add tier to users" --autogenerate

# 3. 看当前版本
alembic current

# 4. 回滚一步
alembic downgrade -1
```

`alembic/env.py` 是 async + 读 `TETRA_DB_URL`. 第一个版本 `0001_initial` 已包含全部 6 个 table.

---

## 2. 缓存 (`storage.cache`)

### 选型
- **dev / 单进程**: InMemoryCache (dict + ttl).
- **prod**: Redis 7. 推荐腾讯云 Redis 1G ¥40/月, 或本机 docker `docker run -p 6379:6379 redis:7-alpine`.

环境变量 `REDIS_URL` 有就用 Redis, 失败自动 fallback in-memory.

### 用法
```python
from tetra_harness.storage.cache import get_cache

cache = get_cache()
await cache.set("user:123", {"name": "lin"}, ttl=600)
v = await cache.get("user:123")
n = await cache.incr("rate:limit:lin", by=1)
```

JSON 透明序列化 (写 dict / list / int 都自动 dump+load).

---

## 3. 大对象 (`storage.artifact`)

### 三家国产对比 (1GB / 月成本, 2026-04 价)

| Provider | 价格 (标准存储) | 免费额度 | 适合场景 |
|---|---|---|---|
| **七牛云 Kodo** | ¥0.099/GB/月 | **10G/月免费** | 推荐 — 小项目零成本 |
| 阿里云 OSS | ¥0.12/GB/月 | 无 | 阿里生态深度集成 |
| 腾讯云 COS | ¥0.118/GB/月 | 50G 试用 6 个月 | 腾讯云生态 (已用 PG/Redis 时统一) |

### env 切换
```bash
export ARTIFACT_PROVIDER=qiniu       # qiniu / oss / cos / local

# 七牛
export QINIU_AK=xxx
export QINIU_SK=xxx
export QINIU_BUCKET=tetra-harness
export QINIU_DOMAIN=cdn.example.com
```

### 用法
```python
from tetra_harness.storage.artifact import get_artifact_store

store = get_artifact_store()
url = await store.put("runs/2026-04-30/log.txt", b"hello")
data = await store.get("runs/2026-04-30/log.txt")
signed = await store.presign_url("runs/2026-04-30/log.txt", expires_sec=600)
```

bytes / Path 都收, metadata dict 透传.

---

## 4. Secrets (`storage.secrets`)

### sops 安装 + age key 生成 (一次)
```bash
# 装 sops + age (Mac/Linux)
brew install sops age

# Windows: scoop install sops age  或下 release binary

# 1. 生成 age key
age-keygen -o ~/.config/sops/age/keys.txt
# 输出 public key, 复制下来

# 2. 加密 .env → secrets.enc.yaml
sops --encrypt --age <PUBLIC_KEY> --input-type yaml --output-type yaml \
     configs/secrets.yaml > configs/secrets.enc.yaml

# 3. 解密 (也是 SopsSecret 内部走的命令)
sops -d configs/secrets.enc.yaml
```

### 三种 provider
```bash
export SECRETS_PROVIDER=env           # 默认 — 从 os.environ 读
export SECRETS_PROVIDER=sops          # sops 文件
export SECRETS_PROVIDER=composite     # sops 优先, env 兜底
export SOPS_FILE=configs/secrets.enc.yaml
```

### 用法
```python
from tetra_harness.storage.secrets import get_secrets

s = get_secrets()
key = s.get("OPENAI_API_KEY")          # str | None
key = s.get("anthropic.api_key")       # 嵌套路径 (sops yaml)
```

`SopsSecret` 调 `sops -d` 走 `utils.subprocess_safe.safe_run` (timeout / GBK 安全 / 不抛). 解密失败 → 空 dict, 不炸主流程.

---

## 5. AuditLog 查询示例
```python
from datetime import datetime, timedelta
from sqlalchemy import select
from tetra_harness.storage.db import get_db
from tetra_harness.storage.models import AuditLog

db = get_db()
async with db.session() as s:
    stmt = (
        select(AuditLog)
        .where(AuditLog.actor == "lin")
        .where(AuditLog.occurred_at >= datetime.utcnow() - timedelta(days=7))
        .order_by(AuditLog.occurred_at.desc())
        .limit(100)
    )
    rows = (await s.execute(stmt)).scalars().all()
```

---

## 依赖安装 (运行期)

业务代码 import 时 storage 包是 lazy import, 没装也能 import. 真正用到才需要:

```bash
pip install sqlalchemy>=2.0 aiosqlite           # 必装 (sqlite dev)
pip install asyncpg                             # postgres prod
pip install redis>=5.0                          # Redis cache
pip install qiniu                               # 七牛
pip install oss2                                # 阿里
pip install cos-python-sdk-v5                   # 腾讯
pip install alembic                             # 迁移工具
```

未在 pyproject 里加 — 由 quality agent 决定何时正式声明.

---

## 设计要点 (踩坑预防)

1. **fallback 优先**: 任何外部依赖 (Redis/OSS/sops) init 失败必 fallback, 不让主流程炸.
2. **subprocess 走 safe_run**: `SopsSecret` 调 sops 必经 `utils.subprocess_safe`, 防 Windows GBK 解码炸.
3. **render_as_batch=sqlite**: alembic env.py 已开 sqlite 自动 batch mode, 否则 sqlite 改列会失败.
4. **token 不存明文**: `User.token_hash` 用 `models.hash_token()` 加 salt sha256.
5. **bucket id 拼写**: 腾讯 COS bucket 末尾必须带 `-<appid>`, 配置示例已含.
