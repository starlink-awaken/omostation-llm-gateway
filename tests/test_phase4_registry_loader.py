from __future__ import annotations

from llm_gateway.registry_data_loader import build_static_registry, load_role_routes, route_role_request


def test_build_static_registry_loads_all_seed_models():
    registry, seeded = build_static_registry()
    models = registry.list_models()

    assert seeded >= 10
    assert len(models) == seeded
    assert any(model.id == "openai/gpt-4.1-mini" for model in models)
    assert any(model.id == "ollama/qwen3:32b" for model in models)


def test_route_role_request_uses_role_route_priorities():
    routes = load_role_routes()
    selection = route_role_request("planner", required_capabilities=["tool_use"], routes=routes)

    assert selection is not None
    assert selection.model.id == "openai/gpt-4.1-mini"
    assert selection.provider_name == "openai"


def test_route_role_request_respects_capability_filter():
    selection = route_role_request("operator", required_capabilities=["coding"])

    assert selection is not None
    assert "coding" in selection.model.capabilities
