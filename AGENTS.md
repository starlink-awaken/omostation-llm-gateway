# AGENTS.md — LLM Gateway

> eCOS v5 LLM 网关 · 模型路由 + 负载均衡 + 降级 + 计费

## Quick Commands

```bash
cd projects/llm-gateway
uv run pytest tests/ -q
uv run ruff check src/
```

## Architecture

LLM 请求的统一入口层，正在往 AetherForge 收敛：

```
aetherforge/           ── 目标归宿（蜂群引擎网关）
llm-gateway/          ── 现状（本仓，待迁移）
```

### 能力

- **模型路由** — 按模型/供应商/优先级分发请求
- **负载均衡** — 多实例、多 API Key 轮询
- **降级策略** — 主模型不可用时 fallback
- **计费审计** — 用量统计和成本核算

## Dependencies

- Python >=3.10, uv
- httpx 作为 HTTP 客户端

## Testing

```bash
uv run pytest tests/ -q
```


## Bus foundation (跨仓依赖)

本项目通过 `llm_gateway/bus_adapter.py` 接入 [bus-foundation](https://github.com/starlink-awaken/omostation/tree/main/projects/bus-foundation) (R66 独立仓):

```python
from bus_foundation import publish, subscribe, schedule, BusEnvelope
```

- **Public API**: `publish` / `subscribe` / `schedule` / `BusEnvelope` / `EventType`
- **零 agora 依赖**: bus-foundation 是 standalone Python package
- **公共 API 冻结 6 月** (从 2026-06-12 起)
- **L0 协议层提升**: 评估 R70-R72, 决策 **Path C: Defer Indefinitely** (见 `projects/bus-foundation/docs/ADR-0003-no-l0-promotion.md`)
- **修改 bus-foundation**: 提 PR 到 `projects/bus-foundation/`, 改完跑该项目的 `uv run pytest -q` 验证

> 不要直接 import `agora.bus` (那是 backward-compat shim)。新代码用 `from bus_foundation import ...`。
