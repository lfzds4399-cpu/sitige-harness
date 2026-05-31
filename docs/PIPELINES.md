# sitige-harness · Pipelines overview

5 条业务流水线, 共 23 stage. 每条 pipeline 由 `pipelines/<name>_pipeline.py` 实现, 配置在 `configs/<name>.yaml`.

调用入口 (单 pipeline):

```python
import asyncio
from tetra_harness.config import load_config
from tetra_harness.manifest import manifest_for
from tetra_harness.pipelines import get_pipeline

async def main():
    cfg = load_config("content")
    pipe = get_pipeline("content")
    result = await pipe.run_all(cfg, manifest=manifest_for("content"))
    print(result.to_dict())

asyncio.run(main())
```

CLI:

```bash
python -m tetra_harness run content              # 跑全部 stage
python -m tetra_harness run content --stage select_topic
python -m tetra_harness run match --quiet        # CC 友好模式
```

---

## 1. content_pipeline · 内容生产 (5 stage)

```
 select_topic ─▶ generate_script ─▶ aigc_assets ─▶ compliance_review ─▶ publish_brief
   (DeepSeek)     (DeepSeek)        (DeepSeek)     (LLM + validator)    (聚合 brief.md)
```

**输入**: `configs/content.yaml` (品牌关键词 / 调性 / 平台周配额)
**输出**: `data/content/` 下 `topics.json` `script.json` `aigc_prompts.json` `compliance.json` `brief.md`

| stage | agent | 关键 config | 产物 |
|---|---|---|---|
| select_topic | content_agent.select_topic | candidates / platforms | topics.json |
| generate_script | content_agent.generate_script | temperature | script.json |
| aigc_assets | content_agent.aigc_prompt | temperature | aigc_prompts.json |
| compliance_review | compliance_agent.text_review | strictness | compliance.json |
| publish_brief | (聚合) | — | brief.md |

监控指标: 选题命中率 / 脚本通过率 / 合规 block 率 / 周内容达成 vs 配额.

---

## 2. recruit_pipeline · 工作室招募 (5 stage)

```
 scan_channels ─▶ outreach_draft ─▶ qualify ─▶ deposit ─▶ sign_offer
  (intel mock)    (4 套话术)       (KYC)      (押金阶梯)  (合同+SOP)
```

**输入**: `configs/recruit.yaml` (渠道 / KYC 字段 / 押金 base / 试运营天数)
**输出**: `data/recruit/` 下 `candidates.json` `outreach_drafts.json` `qualified.json` `deposits.json` `offers.json`

| stage | agent | 关键 config | 产物 |
|---|---|---|---|
| scan_channels | intel_agent.scan_channels | channels[] | candidates.json |
| outreach_draft | (规则模板) | max_drafts | outreach_drafts.json |
| qualify | screen_agent | kyc_fields[] | qualified.json |
| deposit | (规则) | tiers S/A/B/C | deposits.json |
| sign_offer | (规则) | contract_template | offers.json |

⚠️ scan_channels 当前为 mock, 真接需 dataos / 蝉妈妈 / 新榜 (付费).

---

## 3. match_pipeline · 派单 (6 stage)

```
 intake ─▶ screen ─▶ match ─▶ dispatch ─▶ track ─▶ settle
 (单进)   (KYC+黑)   (6因子)  (3栈推送)   (跟踪)    (结算)
```

**输入**: `configs/match.yaml` (server_url / 6 因子 weights / 超时 / 降级链)
**输出**: `data/match/` 下 `intake_*.json` `match_*.json` `dispatch_*.json` `settle_*.json`

| stage | agent | 关键 config | 产物 |
|---|---|---|---|
| intake | (server 推送) | mock_order | intake_*.json |
| screen | screen_agent | blacklist_path | (ctx) |
| match | match_agent | server_url + weights | match_*.json |
| dispatch | (KOOK/QQ/微信) | dispatch_channels | dispatch_*.json |
| track | (规则) | ack_timeout_min | (ctx) |
| settle | (规则 + 评价) | default_amount_rmb | settle_*.json |

server_url 留空时 match 走本地 mock, 方便离线开发.
match / dispatch 设 `skip_on_error=True`, server 抖动不会让 pipeline 整体卡死.

---

## 4. crm_pipeline · 客服 (4 stage)

```
 intake ─▶ route ─▶ auto_reply ─▶ human_handoff
 (工单)   (分类)    (RAG+LLM)     (置信度+敏感词)
```

**输入**: `configs/crm.yaml` (知识库路径 / 置信阈值 / 分类列表)
**知识库**: 默认加载 `legal/` `ops/客服话术库.md` `risk/平台关键词审核表.md`, 用 BM25-lite 检索.

| stage | agent | 关键 config | 产物 |
|---|---|---|---|
| intake | (入口) | mock_ticket | (ctx) |
| route | crm_agent.classify | categories[] | (ctx) |
| auto_reply | crm_agent.auto_reply (RAG) | top_k / threshold | reply_*.json |
| human_handoff | (规则) | sensitive_keywords | handoff_*.json |

监控指标: 自动回复率 / 人工 handoff 率 / 平均置信度 / 敏感词命中.

---

## 5. compliance_pipeline · 合规审核 (3 stage)

```
 text_scan ─▶ image_audit ─▶ final_gate
 (LLM+validator) (stub)      (综合评分)
```

**输入**: `configs/compliance.yaml` (平台 / 严格度 / 人工阈值)

| stage | agent | 关键 config | 产物 |
|---|---|---|---|
| text_scan | compliance_agent.text_review | strictness + validator | text_scan.json |
| image_audit | compliance_agent.image_audit (stub) | provider | image_audit.json |
| final_gate | compliance_agent.final_score | manual_review_threshold | final_gate.json |

⚠️ image_audit 当前 stub, 真接 万象 / 数美 / 网易易盾 (¥0.001-0.01/张).

---

## 调用范例

### 跑单条 pipeline (Python)

```python
import asyncio
from tetra_harness.config import load_config
from tetra_harness.pipelines import get_pipeline

cfg = load_config("crm")
result = asyncio.run(get_pipeline("crm").run_all(cfg))
print(f"crm pipeline ok={result.ok}, stages={[s.name for s in result.stages]}")
```

### 单 stage 重跑 (排错用)

```python
result = asyncio.run(
    get_pipeline("content").run_all(cfg, only_stage="compliance_review")
)
```

### 注入 ctx (test / 联调)

```python
ctx = {"order": {"order_id": "ORD-X-1", "user_id": "U-9", "user_segment": "vip"}}
result = asyncio.run(get_pipeline("match").run_all(cfg, ctx=ctx))
```

---

## 监控指标 (建议接入 prometheus)

| 指标 | 来源 | 阈值告警 |
|---|---|---|
| pipeline_run_total | manifest.json 数 | — |
| pipeline_failure_rate | result.ok=False / total | > 5% |
| stage_p95_latency_ms | StageResult.elapsed_ms | content > 60s, match > 5s |
| llm_cost_usd_daily | data/_costs/cost_log.jsonl | > $5/d |
| compliance_block_rate | text_scan verdict | > 10% (内容质量问题) |
| crm_handoff_rate | human_handoff true | > 30% (KB 不足) |

---

## SKILL 对齐

- E1 subprocess: 本层无 subprocess, 全 async httpx + LLMClient.
- E2 manifest 必写: `Pipeline.run_all` 每 stage 完成自动 `manifest.update`.
- E5 only_stage: 支持单 stage 重跑.
- E10 不抽 `_lib`: 每 pipeline 独立 import agent, 不抽公共 stage.
