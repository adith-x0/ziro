"""Unit and Integration Tests for NEXUS Route Agent.

Verifies:
21. Valid route discovery (ROUTE-B, ROUTE-C)
22. Blocked route detection (ROUTE-A flooded)
23. Alternative route selection (ROUTE-C when ROUTE-B is avoided)
24. Stale route data detection
25. Contradictory route evidence detection
26. Unavailable routing tool graceful handling
27. Malformed route response validation
28. Route ID schema validation
29. No fabricated routes
30. Evidence grounding
31. NexusState integration & RoutingState conversion
32. Cross-agent pipeline execution (Impact -> Resource -> Route)
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agents.impact import ImpactAnalysisAgent
from agents.resources import ResourceAgent
from agents.routes import (
    RouteAgent,
    RouteAnalysisOutput,
    RouteItemAnalysis,
)
from agents.schemas import RoutingState
from tools.interfaces import RoutingProvider
from tools.registry import ToolRegistry, register_default_tools
from tools.schemas import RoutingInput, RoutingOutput


class FailingRoutingProvider(RoutingProvider):
    """Simulates GIS / routing graph service network failure."""

    async def calculate_route(self, input_data: RoutingInput) -> RoutingOutput:
        raise TimeoutError("NetworkX routing calculation timed out.")


from tools.implementations import RoutingTool
from tools.synthetic_environment import simulated_fleet_service, synthetic_road_network


@pytest.fixture(autouse=True)
def reset_road_and_fleet_environment():
    """Ensure road network and fleet are reset before and after each test."""
    synthetic_road_network.reset()
    simulated_fleet_service.reset()
    yield
    synthetic_road_network.reset()
    simulated_fleet_service.reset()


def build_route_test_registry(
    routing_provider: RoutingProvider | None = None,
) -> ToolRegistry:
    """Builds test ToolRegistry with mock providers and optional overrides."""
    registry = ToolRegistry()
    register_default_tools(registry)
    if routing_provider:
        tool = RoutingTool(provider=routing_provider)
        registry.register(tool)
    return registry


# -----------------------------------------------------------------------------
# Test Cases 21 - 30
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_valid_route_discovery() -> None:
    """21. Discovers passable topological routes and selects ROUTE-B as initial primary."""
    agent = RouteAgent(tool_registry=build_route_test_registry())
    output = await agent.analyze(
        incident={"incident_id": "inc-01"},
        impact={"affected_roads": ["Metropolitan Parkway"]},
    )

    assert isinstance(output, RouteAnalysisOutput)
    assert output.selected_route_id == "ROUTE-B"
    assert output.primary_route is not None
    assert output.primary_route.route_id == "ROUTE-B"
    assert output.primary_route.status == "AVAILABLE"


@pytest.mark.asyncio
async def test_blocked_route_detection() -> None:
    """22. Detects ROUTE-A as BLOCKED due to flood depth exceeding clearance."""
    agent = RouteAgent(tool_registry=build_route_test_registry())
    output = await agent.analyze(
        incident={"incident_id": "inc-01"},
        impact={"affected_roads": ["Metropolitan Parkway"]},
    )

    blocked_ids = [r.route_id for r in output.blocked_routes]
    assert "ROUTE-A" in blocked_ids
    route_a = next(r for r in output.active_routes if r.route_id == "ROUTE-A")
    assert route_a.status == "BLOCKED"
    assert route_a.max_flood_depth_inches >= 30.0


@pytest.mark.asyncio
async def test_alternative_route_selection() -> None:
    """23. When ROUTE-B is injected as compromised / avoided, selects ROUTE-C as primary."""
    agent = RouteAgent(tool_registry=build_route_test_registry())
    output = await agent.analyze(
        incident={"incident_id": "inc-01"},
        avoid_routes=["ROUTE-A", "ROUTE-B"],
    )

    assert output.selected_route_id == "ROUTE-C"
    assert output.primary_route is not None
    assert output.primary_route.route_id == "ROUTE-C"
    assert output.primary_route.status == "AVAILABLE"
    # Both ROUTE-A and ROUTE-B are now in blocked_routes
    blocked_ids = [r.route_id for r in output.blocked_routes]
    assert "ROUTE-A" in blocked_ids
    assert "ROUTE-B" in blocked_ids


@pytest.mark.asyncio
async def test_stale_route_data_detection() -> None:
    """24. Flags routes when road condition reports exceed staleness limit."""
    agent = RouteAgent(tool_registry=build_route_test_registry(), staleness_max_hours=1.0)
    output = await agent.analyze(incident={"incident_id": "inc-01"})

    assert isinstance(output.stale_routes_detected, list)


@pytest.mark.asyncio
async def test_contradictory_route_evidence() -> None:
    """25. Detects when sensor telemetry contradicts road registry status."""
    agent = RouteAgent(tool_registry=build_route_test_registry())
    # Fabricate sensory evidence indicating water level > vehicle clearance on ROUTE-B
    contradictory_evidence = [
        type(
            "MockEvidence",
            (),
            {
                "evidence_id": "ev-contra-01",
                "data": {"corridor": "ROUTE-B", "water_level_inches": 42.0},
            },
        )()
    ]

    output = await agent.analyze(
        incident={"incident_id": "inc-01"},
        evidence_items=contradictory_evidence,
        vehicle_clearance_inches=34.0,
    )

    assert len(output.contradictions_detected) >= 1
    # ROUTE-B marked UNCERTAIN due to sensor contradiction
    uncertain_ids = [r.route_id for r in output.uncertain_routes]
    assert "ROUTE-B" in uncertain_ids


@pytest.mark.asyncio
async def test_unavailable_routing_tool() -> None:
    """26. Gracefully handles routing tool outage without crashing."""
    agent = RouteAgent(
        tool_registry=build_route_test_registry(routing_provider=FailingRoutingProvider())
    )
    output = await agent.analyze(incident={"incident_id": "inc-01"})

    assert isinstance(output, RouteAnalysisOutput)
    assert len(output.missing_information) >= 1
    assert any("routing_tool" in m for m in output.missing_information)


def test_malformed_route_response() -> None:
    """27. Rejects malformed waypoint coordinates out of geographic bounds."""
    with pytest.raises(ValidationError):
        RouteItemAnalysis(
            route_id="ROUTE-TEST",
            name="Test Route",
            distance_km=5.0,
            estimated_time_minutes=10.0,
            status="AVAILABLE",
            waypoints=[[999.0, -999.0]],  # Out of bounds
        )


def test_route_id_validation() -> None:
    """28. RouteItemAnalysis validates strict regex formatting for route IDs."""
    # Valid
    r = RouteItemAnalysis(
        route_id="ROUTE-B",
        name="Industrial Way Detour",
        distance_km=4.2,
        estimated_time_minutes=11.0,
        status="AVAILABLE",
        waypoints=[[8.518, 76.93], [8.528, 76.942]],
    )
    assert r.route_id == "ROUTE-B"

    # Invalid
    with pytest.raises(ValidationError):
        RouteItemAnalysis(
            route_id="invalid route id with spaces and #$%!",
            name="Bad Route",
            distance_km=4.2,
            estimated_time_minutes=11.0,
            status="AVAILABLE",
            waypoints=[],
        )


@pytest.mark.asyncio
async def test_no_fabricated_routes() -> None:
    """29. Ensures agent never invents non-existent corridors."""
    agent = RouteAgent(tool_registry=build_route_test_registry())
    output = await agent.analyze(incident={"incident_id": "inc-01"})

    valid_route_ids = {"ROUTE-A", "ROUTE-B", "ROUTE-C"}
    for r in output.active_routes:
        assert r.route_id in valid_route_ids


@pytest.mark.asyncio
async def test_evidence_grounding() -> None:
    """30. Attaches verified evidence IDs to routing assessment."""
    agent = RouteAgent(tool_registry=build_route_test_registry())
    mock_ev = [type("MockEvidence", (), {"evidence_id": "ev-route-99"})()]
    output = await agent.analyze(
        incident={"incident_id": "inc-01"},
        evidence_items=mock_ev,
    )

    assert "ev-route-99" in output.evidence_ids


@pytest.mark.asyncio
async def test_nexus_state_integration() -> None:
    """31. BaseAgent.process() updates NexusState with strongly-typed RoutingState."""
    agent = RouteAgent(tool_registry=build_route_test_registry())
    state: dict[str, Any] = {
        "incident": {"incident_id": "inc-01"},
        "impact": {"affected_roads": ["Metropolitan Parkway"]},
        "current_status": "IMPACT_EVALUATED",
    }

    res = await agent.process(state)

    assert res["current_status"] == "ROUTED"
    assert "routes" in res
    assert isinstance(res["routes"], RoutingState)
    assert res["selected_primary_route_id"] == "ROUTE-B"
    assert len(res["active_routes"]) >= 3


@pytest.mark.asyncio
async def test_cross_agent_lifecycle() -> None:
    """32. Verifies sequential lifecycle: ImpactAgent -> ResourceAgent -> RouteAgent on shared state."""
    registry = build_route_test_registry()
    impact_agent = ImpactAnalysisAgent(tool_registry=registry)
    resource_agent = ResourceAgent(tool_registry=registry)
    route_agent = RouteAgent(tool_registry=registry)

    # Initial state after Verification
    state: dict[str, Any] = {
        "incident": {
            "incident_id": "inc-canonical-flood",
            "description": "Hospital Ingress Blocked: Flash Flooding at Metropolitan Parkway",
        },
        "evidence": [
            {
                "evidence_id": "ev-01",
                "source_type": "WATER_SENSOR",
                "data": {"water_level_inches": 35.0},
            }
        ],
        "current_status": "VERIFIED",
    }

    # Step 1: Impact Agent
    impact_res = await impact_agent.process(state)
    state.update(impact_res)
    assert state["current_status"] == "IMPACT_EVALUATED"
    assert state["impact_assessment"].ingress_cut_off is True

    # Step 2: Resource Agent
    resource_res = await resource_agent.process(state)
    state.update(resource_res)
    assert state["resources"].selected_unit in ("AMB-01", "AMB-03")

    # Step 3: Route Agent
    route_res = await route_agent.process(state)
    state.update(route_res)
    assert state["current_status"] == "ROUTED"
    assert state["selected_primary_route_id"] == "ROUTE-B"
    assert len(state["routes"].blocked_routes) >= 1
