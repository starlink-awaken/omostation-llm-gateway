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
