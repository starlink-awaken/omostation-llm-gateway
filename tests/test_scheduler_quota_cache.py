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
from llm_gateway import quota_ledger
from llm_gateway.provider import record_llm_cost
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
    ledger_log = tmp_path / "runtime" / "data" / "llm_quota_ledger.jsonl"
    summary_path = tmp_path / "runtime" / "data" / "llm_quota_summary.json"
    monkeypatch.setattr(quota_ledger, "LEDGER_LOG", ledger_log)
    monkeypatch.setattr(quota_ledger, "SUMMARY_PATH", summary_path)
    quota_path.write_text(
        json.dumps(
            {
                "rates": {"model-a": {"input": 0.25, "output": 0.75}},
                "quota": {"remaining": 4, "limit": 100, "remaining_budget_usd": 9.5},
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
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["remaining_budget_usd"] == 9.5


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


def test_quota_ledger_summary_tracks_estimated_spend(tmp_path):
    ledger_log = tmp_path / "llm_quota_ledger.jsonl"
    quota_ledger.append_quota_ledger_event(
        model="dummy/model-a",
        input_tokens=1200,
        output_tokens=300,
        estimated_cost_usd=0.42,
        ledger_log=ledger_log,
    )
    quota_ledger.append_quota_ledger_event(
        model="dummy/model-b",
        input_tokens=800,
        output_tokens=100,
        estimated_cost_usd=0.18,
        ledger_log=ledger_log,
    )

    summary = quota_ledger.summarize_quota_ledger(
        {"remaining_budget_usd": 10.0, "remaining_pct": 40},
        ledger_log=ledger_log,
    )

    assert summary["entry_count"] == 2
    assert summary["total_estimated_cost_usd"] == 0.6
    assert summary["total_input_tokens"] == 2000
    assert summary["effective_remaining_budget_usd"] == 9.4
    assert summary["remaining_ratio"] == 0.4


def test_record_llm_cost_appends_estimated_quota_usage(tmp_path, monkeypatch):
    cost_log = tmp_path / "runtime" / "data" / "llm_cost.jsonl"
    ledger_log = tmp_path / "runtime" / "data" / "llm_quota_ledger.jsonl"
    monkeypatch.setattr("llm_gateway.provider._COST_LOG", cost_log)
    monkeypatch.setattr("llm_gateway.registry_data_loader.estimate_model_cost", lambda *_args, **_kwargs: 0.33)
    monkeypatch.setattr("llm_gateway.provider.append_quota_ledger_event", quota_ledger.append_quota_ledger_event)
    monkeypatch.setattr(quota_ledger, "LEDGER_LOG", ledger_log)

    record_llm_cost("dummy/model-a", 1000, 200)

    cost_payload = json.loads(cost_log.read_text(encoding="utf-8").strip())
    ledger_payload = json.loads(ledger_log.read_text(encoding="utf-8").strip())
    assert cost_payload["estimated_cost_usd"] == 0.33
    assert ledger_payload["estimated_cost_usd"] == 0.33
    assert ledger_payload["input_tokens"] == 1000
