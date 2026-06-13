from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_DIR = ROOT / "src" / "llm_gateway" / "registry_data"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_models_registry_has_required_provider_coverage():
    payload = _load_yaml(REGISTRY_DIR / "models.yaml")
    models = payload["models"]
    counts = Counter(item["provider"] for item in models)

    assert len(models) >= 10
    assert len(counts) >= 3
    assert all(count >= 2 for count in counts.values())


def test_models_registry_entries_have_phase4_required_fields():
    payload = _load_yaml(REGISTRY_DIR / "models.yaml")

    for model in payload["models"]:
        assert {"provider", "model_id", "context", "cost", "latency"} <= model.keys()
        assert {"input_per_1k", "output_per_1k"} <= model["cost"].keys()


def test_role_routes_reference_known_models():
    models = _load_yaml(REGISTRY_DIR / "models.yaml")["models"]
    known = {f"{item['provider']}/{item['model_id']}" for item in models}
    routes = _load_yaml(REGISTRY_DIR / "role_routes.yaml")["routes"]

    assert {"planner", "researcher", "reviewer", "operator", "critic"} <= routes.keys()
    for route in routes.values():
        refs = list(route.get("primary_models", [])) + list(route.get("fallback_models", []))
        assert refs
        assert set(refs) <= known
