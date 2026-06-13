from __future__ import annotations

from llm_gateway.cli import main


def test_cli_list_registry_data_prints_seed_models(capsys):
    assert main(["list", "--registry-data"]) == 0
    output = capsys.readouterr().out
    assert "registry_data" in output
    assert "openai/gpt-4.1-mini" in output


def test_cli_route_prints_selected_model(capsys):
    assert main(["route", "--role", "reviewer", "--capability", "reasoning"]) == 0
    output = capsys.readouterr().out
    assert "role=reviewer" in output
    assert "model=anthropic/claude-sonnet-4" in output
