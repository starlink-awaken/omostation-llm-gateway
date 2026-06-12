import json

from llm_gateway.audit import LLMCallAuditRecord, record_llm_audit
from llm_gateway.registry_data_loader import estimate_model_cost, get_registry_model_record


# Fields P4-E4 closeout guarantees on every audit record (P4-E4 acceptance §1).
REQUIRED_FIELDS = (
    "task_id",
    "role",
    "provider",
    "model",
    "input_tokens",
    "output_tokens",
    "total_cost_usd",
    "latency_ms",
)


def test_estimate_model_cost_uses_registry_rates():
    record = get_registry_model_record("anthropic/claude-sonnet-4")
    assert record is not None

    cost = estimate_model_cost("anthropic/claude-sonnet-4", input_tokens=1000, output_tokens=1000)
    assert cost == 0.018


def test_record_llm_audit_writes_required_fields(tmp_path):
    audit_log = tmp_path / "llm_calls.jsonl"
    record_llm_audit(
        task_id="opc-p4-audit-demo",
        role="planner",
        provider="anthropic",
        model="claude-sonnet-4",
        input_tokens=120,
        output_tokens=40,
        total_cost_usd=0.02,
        latency_ms=12.5,
        route={"selection_mode": "registry_route"},
        metadata={"tool_count": 10},
        audit_log=audit_log,
    )

    payload = json.loads(audit_log.read_text(encoding="utf-8").strip())
    assert payload["task_id"] == "opc-p4-audit-demo"
    assert payload["role"] == "planner"
    assert payload["provider"] == "anthropic"
    assert payload["model"] == "claude-sonnet-4"
    assert payload["total_cost_usd"] == 0.02
    assert payload["latency_ms"] == 12.5
    assert payload["route"]["selection_mode"] == "registry_route"


def test_audit_record_schema_enforces_all_required_fields():
    """P4-E4 closeout: LLMCallAuditRecord must declare every governance field as required."""
    declared = set(LLMCallAuditRecord.model_fields.keys())
    missing = [f for f in REQUIRED_FIELDS if f not in declared]
    assert not missing, f"audit schema missing required fields: {missing}"


def test_audit_record_rejects_missing_task_id_or_role():
    """P4-E4 closeout: schema-level guards prevent silent field drops."""
    import pytest

    with pytest.raises(ValueError):
        LLMCallAuditRecord(
            ts="2026-06-12T00:00:00Z",
            task_id="",
            role="planner",
            provider="anthropic",
            model="claude-sonnet-4",
            input_tokens=10,
            output_tokens=5,
            total_cost_usd=0.001,
            latency_ms=1.0,
        )
    with pytest.raises(ValueError):
        LLMCallAuditRecord(
            ts="2026-06-12T00:00:00Z",
            task_id="t1",
            role="",
            provider="anthropic",
            model="claude-sonnet-4",
            input_tokens=10,
            output_tokens=5,
            total_cost_usd=0.001,
            latency_ms=1.0,
        )


def test_audit_jsonl_supports_cross_record_task_attribution(tmp_path):
    """P4-E4 closeout: audit trail must be consumable by downstream governance.

    omo audit-rollout and the cockpit traces both need to group records by
    task_id across calls. Verify that 3 calls (2 task A + 1 task B) produce a
    jsonl that yields a deterministic per-task summary.
    """
    audit_log = tmp_path / "llm_calls.jsonl"
    for i, (task_id, cost) in enumerate(
        [("opc-p4-task-A", 0.01), ("opc-p4-task-B", 0.05), ("opc-p4-task-A", 0.02)]
    ):
        record_llm_audit(
            task_id=task_id,
            role="planner" if i % 2 == 0 else "operator",
            provider="anthropic",
            model="claude-sonnet-4",
            input_tokens=100 + i,
            output_tokens=40,
            total_cost_usd=cost,
            latency_ms=2.5 + i,
            audit_log=audit_log,
        )

    lines = [
        json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(lines) == 3

    # every record carries the 8 governance fields
    for line in lines:
        for field in REQUIRED_FIELDS:
            assert field in line, f"record missing {field}: {line}"

    # per-task attribution (the cross-repo consumer contract)
    by_task: dict[str, dict] = {}
    for line in lines:
        agg = by_task.setdefault(
            line["task_id"], {"call_count": 0, "total_cost_usd": 0.0, "models": set(), "roles": set()}
        )
        agg["call_count"] += 1
        agg["total_cost_usd"] += line["total_cost_usd"]
        agg["models"].add(line["model"])
        agg["roles"].add(line["role"])

    assert by_task["opc-p4-task-A"]["call_count"] == 2
    assert abs(by_task["opc-p4-task-A"]["total_cost_usd"] - 0.03) < 1e-9
    assert by_task["opc-p4-task-B"]["call_count"] == 1
    assert abs(by_task["opc-p4-task-B"]["total_cost_usd"] - 0.05) < 1e-9
    assert by_task["opc-p4-task-A"]["models"] == {"claude-sonnet-4"}
    assert by_task["opc-p4-task-A"]["roles"] == {"planner"}
    assert by_task["opc-p4-task-B"]["roles"] == {"operator"}
