# ruff: noqa: E402

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.modules.setdefault("yaml", types.SimpleNamespace(safe_load=lambda *_args, **_kwargs: {}))

from llm_gateway.registry import ModelRegistry
from llm_gateway.scheduler import ModelScheduler
from llm_gateway.types import ChatResult, ModelDescriptor, ModelRequest, SchedulerConfig
from llm_gateway.providers.base import BaseLLMProvider


class DummyProvider(BaseLLMProvider):
    @property
    def name(self) -> str:
        return "dummy"

    @property
    def provider_type(self) -> str:
        return "test"

    async def discover(self) -> list[ModelDescriptor]:
        return [
            ModelDescriptor(
                id="dummy/model-a",
                name="model-a",
                provider="dummy",
                capabilities=["chat"],
                cost_per_1k_tokens={"input": 1.0, "output": 2.0},
            )
        ]

    async def chat(self, model: str, messages: list[dict], options=None) -> ChatResult:
        return ChatResult(id="1", model=model, content="ok")


def _build_scheduler() -> ModelScheduler:
    registry = ModelRegistry()
    registry.register(DummyProvider())
    asyncio.run(registry.refresh())
    return ModelScheduler(registry)


def test_load_quota_rates_updates_model_prices_and_detects_low_quota(tmp_path, monkeypatch):
    cache_dir = tmp_path / ".runtime" / "cache"
    cache_dir.mkdir(parents=True)
    quota_path = cache_dir / "quota_rates.json"
    quota_path.write_text(
        json.dumps(
            {
                "rates": {"model-a": {"input": 0.25, "output": 0.75}},
                "quota": {"remaining": 4, "limit": 100},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    scheduler = _build_scheduler()
    updated = scheduler.load_quota_rates()

    assert updated == 1
    model = scheduler._registry.get("dummy/model-a")
    assert model is not None
    assert model.cost_per_1k_tokens == {"input": 0.25, "output": 0.75}
    assert scheduler._quota_low_mode is True


def test_select_model_reloads_quota_cache_when_low_quota(tmp_path, monkeypatch):
    cache_dir = tmp_path / ".runtime" / "cache"
    cache_dir.mkdir(parents=True)
    quota_path = cache_dir / "quota_rates.json"
    quota_path.write_text(
        json.dumps(
            {
                "rates": {"model-a": {"input": 0.25, "output": 0.75}},
                "quota": {"remaining": 1, "limit": 100},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    scheduler = _build_scheduler()
    scheduler.load_quota_rates()

    quota_path.write_text(
        json.dumps(
            {
                "rates": {"model-a": {"input": 0.5, "output": 1.5}},
                "quota": {"remaining": 1, "limit": 100},
            }
        ),
        encoding="utf-8",
    )

    selection = asyncio.run(scheduler.select_model(ModelRequest(task="t1", required_capabilities=["chat"])))

    assert selection is not None
    model = scheduler._registry.get("dummy/model-a")
    assert model is not None
    assert model.cost_per_1k_tokens == {"input": 0.5, "output": 1.5}


def test_start_auto_refresh_periodically_refreshes_quota_cache(tmp_path, monkeypatch):
    cache_dir = tmp_path / ".runtime" / "cache"
    cache_dir.mkdir(parents=True)
    quota_path = cache_dir / "quota_rates.json"
    quota_path.write_text(
        json.dumps(
            {
                "rates": {"model-a": {"input": 0.2, "output": 0.6}},
                "quota": {"remaining_pct": 12},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    scheduler = _build_scheduler()
    scheduler._last_quota_refresh_at = 0.0
    scheduler._config = SchedulerConfig(quota_cache_refresh_interval_ms=1)

    async def _run() -> None:
        dispose = scheduler.start_auto_refresh(interval_ms=5)
        try:
            await asyncio.sleep(0.02)
        finally:
            dispose()
            await asyncio.sleep(0)

    asyncio.run(_run())

    model = scheduler._registry.get("dummy/model-a")
    assert model is not None
    assert model.cost_per_1k_tokens == {"input": 0.2, "output": 0.6}
