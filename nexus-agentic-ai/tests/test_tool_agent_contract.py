"""Integration Tests Demonstrating Agent-to-Tool Contract Protocols.

Demonstrates and verifies:
1. Every tool is invoked via `tool_registry.execute(tool_name, input_data)`
2. Structured ToolResult fields provide full observability for agent reasoning:
   - success / failure boolean
   - typed output model
   - error / error_code
   - simulation status & is_simulation flag
   - execution metadata (latency, risk level, timestamps)
3. Approval token enforcement strictly blocks unauthenticated medium/high-risk tool calls
4. Supplying a valid commander approval token authorizes execution
5. Input validation errors are captured cleanly without unhandled exceptions
6. No live emergency action can be triggered
"""

import pytest

from tools.registry import ToolResult, default_tool_registry
from tools.synthetic_environment import simulated_fleet_service, synthetic_road_network


@pytest.fixture(autouse=True)
def reset_synthetic_environment():
    """Ensure baseline simulation state for all contract tests."""
    synthetic_road_network.reset()
    simulated_fleet_service.reset()
    yield
    synthetic_road_network.reset()
    simulated_fleet_service.reset()


# -----------------------------------------------------------------------------
# 1. Agent Calling Every Tool Via tool_registry.execute()
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_agent_calls_all_11_tools_consistently():
    """Verify an agent can call all 11 tools uniformly via tool_registry.execute()."""

    # 1. Weather
    w_res: ToolResult = await default_tool_registry.execute(
        "weather",
        {"latitude": 8.5241, "longitude": 76.9366},
    )
    assert w_res.success is True
    assert w_res.status == "success"
    assert w_res.output is not None
    assert w_res.output.flood_level == "HIGH"
    assert w_res.simulation_status == "simulation/mock environment"
    assert w_res.is_simulation is True
    assert "execution_time_ms" in w_res.execution_metadata

    # 2. Incident Reports
    ir_res = await default_tool_registry.execute(
        "incident_reports",
        {"latitude": 8.5241, "longitude": 76.9366, "radius_km": 5.0},
    )
    assert ir_res.success is True
    assert ir_res.output.total_reports >= 2
    assert ir_res.is_simulation is True

    # 3. Image Analysis
    img_res = await default_tool_registry.execute(
        "image_analysis",
        {"image_url": "https://synthetic.cctv/bay01.jpg"},
    )
    assert img_res.success is True
    assert img_res.output.water_depth_estimate_inches > 10.0
    assert img_res.is_simulation is True

    # 4. Geolocation
    geo_res = await default_tool_registry.execute(
        "geolocation",
        {"query_address_or_landmark": "City Hospital"},
    )
    assert geo_res.success is True
    assert geo_res.output.latitude == 8.5280
    assert geo_res.is_simulation is True

    # 5. Routing
    rt_res = await default_tool_registry.execute(
        "routing",
        {"origin": "DEPOT", "destination": "CITY-HOSPITAL", "avoid_routes": ["ROUTE-A"]},
    )
    assert rt_res.success is True
    assert rt_res.output.selected_route_id in ["ROUTE-B", "ROUTE-C"]
    assert rt_res.is_simulation is True

    # 6. Resource Search
    rs_res = await default_tool_registry.execute(
        "resource_search",
        {"resource_type": "AMBULANCE", "required_clearance_inches": 30.0},
    )
    assert rs_res.success is True
    assert rs_res.output.selected_recommendation == "AMB-01"
    assert rs_res.is_simulation is True

    # 7. Hospital Status
    hs_res = await default_tool_registry.execute(
        "hospital_status",
        {"hospital_id": "CITY-HOSPITAL"},
    )
    assert hs_res.success is True
    assert hs_res.output.hospital_id == "CITY-HOSPITAL"
    assert hs_res.is_simulation is True

    # 8. Notifications (Internal Simulated Feed)
    notif_res = await default_tool_registry.execute(
        "notifications",
        {
            "channel": "HOSPITAL_ALERT_FEED",
            "recipient": "ER-BAY-1",
            "title": "Inbound Patient",
            "message": "Medic-Rescue 01 en route.",
            "priority": "HIGH",
        },
    )
    assert notif_res.success is True
    assert notif_res.output.status == "SENT_SIMULATED"
    assert notif_res.is_simulation is True

    # 9. Ambulance Reservation (With Commander Approval Token)
    amb_res = await default_tool_registry.execute(
        "ambulance_reservation",
        {
            "unit_id": "AMB-01",
            "incident_id": "inc-contract-test",
            "destination": "CITY-HOSPITAL",
        },
        approval_token="tok-commander-authorized-123",
    )
    assert amb_res.success is True
    assert amb_res.output.status == "RESERVED"
    assert amb_res.is_simulation is True

    # 10. Incident Status Update
    upd_res = await default_tool_registry.execute(
        "incident_status_update",
        {
            "incident_id": "inc-contract-test",
            "new_status": "ROUTED",
            "commentary": "Route B selected.",
        },
    )
    assert upd_res.success is True
    assert upd_res.output.current_status == "ROUTED"
    assert upd_res.is_simulation is True

    # 11. Audit Logging
    audit_res = await default_tool_registry.execute(
        "audit_logging",
        {
            "incident_id": "inc-contract-test",
            "event_type": "route.selected",
            "actor": "ROUTING_AGENT",
            "summary": "Selected Route B.",
        },
    )
    assert audit_res.success is True
    assert len(audit_res.output.cryptographic_digest) == 16
    assert audit_res.is_simulation is True


# -----------------------------------------------------------------------------
# 2. Approval-Token Enforcement Cannot Be Bypassed
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ambulance_reservation_strictly_requires_approval_token():
    """Assert an agent cannot execute ambulance_reservation without an approval token."""

    # Attempt 1: Direct call via registry without approval_token
    denied_res = await default_tool_registry.execute(
        "ambulance_reservation",
        {
            "unit_id": "AMB-01",
            "incident_id": "inc-unauthorized-attempt",
            "destination": "CITY-HOSPITAL",
        },
    )
    assert denied_res.success is False
    assert denied_res.status == "error"
    assert denied_res.error_code == "APPROVAL_TOKEN_REQUIRED"
    assert denied_res.error is not None
    assert denied_res.error.error_code == "APPROVAL_TOKEN_REQUIRED"
    assert denied_res.error.retryable is False
    assert "strictly requires a validated commander approval token" in denied_res.error.message
    assert denied_res.output is None

    # Verify unit AMB-01 was NOT reserved in fleet inventory
    unit = simulated_fleet_service._fleet["AMB-01"]
    assert unit.status == "AVAILABLE"

    # Attempt 2: Direct call with empty token
    denied_res_empty = await default_tool_registry.execute(
        "ambulance_reservation",
        {
            "unit_id": "AMB-01",
            "incident_id": "inc-unauthorized-attempt",
            "destination": "CITY-HOSPITAL",
        },
        approval_token="   ",  # Blank whitespace
    )
    assert denied_res_empty.success is False
    assert denied_res_empty.error_code == "APPROVAL_TOKEN_REQUIRED"
    assert simulated_fleet_service._fleet["AMB-01"].status == "AVAILABLE"

    # Attempt 3: Authorized call with valid commander token succeeds
    allowed_res = await default_tool_registry.execute(
        "ambulance_reservation",
        {
            "unit_id": "AMB-01",
            "incident_id": "inc-authorized-attempt",
            "destination": "CITY-HOSPITAL",
        },
        approval_token="tok-eoc-watch-commander-789",
    )
    assert allowed_res.success is True
    assert allowed_res.output.status == "RESERVED"
    assert simulated_fleet_service._fleet["AMB-01"].status == "RESERVED"


# -----------------------------------------------------------------------------
# 3. Agent Reasoning on Structured Errors (Validation & Timeouts)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_agent_handles_validation_error_gracefully():
    """Assert invalid input returns structured VALIDATION_ERROR without crashing the agent."""
    res = await default_tool_registry.execute(
        "weather",
        {"latitude": -999.0, "longitude": 76.9366},  # Invalid latitude
    )
    assert res.success is False
    assert res.status == "error"
    assert res.error_code == "VALIDATION_ERROR"
    assert res.error.retryable is False
    assert res.output is None
    assert "validation_errors" in res.error.details
    assert res.execution_metadata["risk_level"] == "LOW"


# -----------------------------------------------------------------------------
# 4. Strict Safety Guardrail: No Real-World Actions
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_all_outputs_contain_simulation_attribution():
    """Verify that every successful output is explicitly flagged as synthetic/simulated."""
    tools_to_check = [
        ("weather", {"latitude": 8.5241, "longitude": 76.9366}),
        ("geolocation", {"query_address_or_landmark": "Depot"}),
        ("hospital_status", {"hospital_id": "CITY-HOSPITAL"}),
    ]

    for name, payload in tools_to_check:
        res = await default_tool_registry.execute(name, payload)
        assert res.success is True
        assert res.simulation_status == "simulation/mock environment"
        assert res.is_simulation is True
        assert res.output.is_simulation is True
        assert res.output.environment == "simulation/mock environment"
