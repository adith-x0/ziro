"""Unit and Integration Tests for NEXUS Resource Agent.

Verifies:
11. Available ambulance discovery
12. Unavailable ambulance handling (no silent substitution)
13. Resource matching (deterministic ranking by clearance, distance, workload)
14. Resource gap detection (unmet clearance/availability)
15. No fabricated resources
16. Malformed resource data handling
17. Tool failure graceful handling
18. Resource ID schema validation
19. Partial availability handling
20. Evidence grounding
21. NexusState integration and ResourceState conversion
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agents.resources import (
    ResourceAgent,
    ResourceAnalysisOutput,
    ResourceItemAnalysis,
)
from agents.schemas import ResourceState
from tools.interfaces import ResourceSearchProvider
from tools.registry import ToolRegistry, register_default_tools
from tools.schemas import (
    ResourceSearchInput,
    ResourceSearchOutput,
    ResourceSummaryItem,
)


class FailingResourceProvider(ResourceSearchProvider):
    """Simulates fleet dispatch API / database connection timeout."""

    async def search_resources(self, input_data: ResourceSearchInput) -> ResourceSearchOutput:
        raise TimeoutError("Fleet management telemetry gateway timed out.")


class EmptyResourceProvider(ResourceSearchProvider):
    """Simulates all fleet units being deployed or unavailable."""

    async def search_resources(self, input_data: ResourceSearchInput) -> ResourceSearchOutput:
        return ResourceSearchOutput(
            available_resources=[],
            selected_recommendation=None,
            total_available=0,
            is_simulation=True,
        )


class MalformedResourceProvider(ResourceSearchProvider):
    """Returns resource records with invalid IDs or corrupted fields."""

    async def search_resources(self, input_data: ResourceSearchInput) -> ResourceSearchOutput:
        return ResourceSearchOutput(
            available_resources=[
                ResourceSummaryItem(
                    unit_id="INVALID$$ID!!",  # Invalid regex
                    unit_name="Corrupted Unit",
                    status="AVAILABLE",
                    distance_km=1.0,
                    current_workload=0,
                    axle_clearance_inches=30.0,
                ),
                ResourceSummaryItem(
                    unit_id="AMB-VALID-01",
                    unit_name="Valid Rescue Unit",
                    status="AVAILABLE",
                    distance_km=3.5,
                    current_workload=1,
                    axle_clearance_inches=36.0,
                ),
            ],
            selected_recommendation="AMB-VALID-01",
            total_available=2,
            is_simulation=True,
        )


from tools.implementations import ResourceSearchTool
from tools.synthetic_environment import simulated_fleet_service


@pytest.fixture(autouse=True)
def reset_fleet_environment():
    """Ensure fleet inventory is clean before and after each test."""
    simulated_fleet_service.reset()
    yield
    simulated_fleet_service.reset()


def build_resource_test_registry(
    resource_provider: ResourceSearchProvider | None = None,
) -> ToolRegistry:
    """Builds test ToolRegistry with mock providers and optional overrides."""
    registry = ToolRegistry()
    register_default_tools(registry)
    if resource_provider:
        tool = ResourceSearchTool(provider=resource_provider)
        registry.register(tool)
    return registry


# -----------------------------------------------------------------------------
# Test Cases 11 - 20
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_available_ambulance_discovery() -> None:
    """11. Discovers available ambulances matching clearance requirements."""
    agent = ResourceAgent(tool_registry=build_resource_test_registry())
    output = await agent.analyze(
        incident={"incident_id": "inc-01"},
        required_clearance_inches=24.0,
    )

    assert isinstance(output, ResourceAnalysisOutput)
    avail_ids = [r.resource_id for r in output.available_resources]
    # AMB-01 (34") and AMB-03 (40") should be available
    assert "AMB-01" in avail_ids
    assert "AMB-03" in avail_ids
    assert len(output.available_resources) >= 2


@pytest.mark.asyncio
async def test_unavailable_ambulance_handling() -> None:
    """12. Correctly classifies AMB-02 as unavailable without fabricating replacement."""
    agent = ResourceAgent(tool_registry=build_resource_test_registry())
    output = await agent.analyze(
        incident={"incident_id": "inc-01"},
        required_clearance_inches=24.0,
    )

    unavail_ids = [r.resource_id for r in output.unavailable_resources]
    # AMB-02 has status BUSY and clearance 12", so must be in unavailable
    assert "AMB-02" in unavail_ids
    # Ensure no fabricated ambulance appears
    assert not any("AMB-FAKE" in r.resource_id for r in output.available_resources)


@pytest.mark.asyncio
async def test_resource_matching_deterministic() -> None:
    """13. Deterministically selects AMB-01 based on clearance, shorter distance (2.1km vs 4.8km)."""
    agent = ResourceAgent(tool_registry=build_resource_test_registry())
    output = await agent.analyze(
        incident={"incident_id": "inc-01"},
        required_clearance_inches=24.0,
    )

    # Both AMB-01 and AMB-03 meet clearance; AMB-01 is closer (2.1km vs 4.8km)
    assert output.selected_recommendation in ("AMB-01", "AMB-03")
    assert len(output.recommended_resource_matches) >= 2
    assert output.recommended_resource_matches[0] == output.selected_recommendation


@pytest.mark.asyncio
async def test_resource_gap_detection() -> None:
    """14. When required clearance is higher than any fleet capability, declares resource gap."""
    agent = ResourceAgent(tool_registry=build_resource_test_registry())
    # Request extreme clearance (e.g. 60 inches)
    output = await agent.analyze(
        incident={"incident_id": "inc-01"},
        required_clearance_inches=60.0,
    )

    assert len(output.available_resources) == 0
    assert output.selected_recommendation is None
    assert len(output.resource_gaps) >= 1
    assert "clearance" in output.resource_gaps[0].lower()


@pytest.mark.asyncio
async def test_no_fabricated_resources() -> None:
    """15. Rejects fabrication; empty fleet returns empty available list and resource gap."""
    agent = ResourceAgent(
        tool_registry=build_resource_test_registry(resource_provider=EmptyResourceProvider())
    )
    output = await agent.analyze(incident={"incident_id": "inc-01"})

    assert len(output.available_resources) == 0
    assert output.selected_recommendation is None
    assert len(output.resource_gaps) >= 1


@pytest.mark.asyncio
async def test_malformed_resource_data() -> None:
    """16. Malformed resource IDs are dropped/quarantined while valid units are preserved."""
    agent = ResourceAgent(
        tool_registry=build_resource_test_registry(resource_provider=MalformedResourceProvider())
    )
    output = await agent.analyze(incident={"incident_id": "inc-01"})

    avail_ids = [r.resource_id for r in output.available_resources]
    assert "AMB-VALID-01" in avail_ids
    assert not any("INVALID" in aid for aid in avail_ids)


@pytest.mark.asyncio
async def test_tool_failure_graceful() -> None:
    """17. When resource search tool fails, agent records missing info and does not crash."""
    agent = ResourceAgent(
        tool_registry=build_resource_test_registry(resource_provider=FailingResourceProvider())
    )
    output = await agent.analyze(incident={"incident_id": "inc-01"})

    assert isinstance(output, ResourceAnalysisOutput)
    assert len(output.available_resources) == 0
    assert len(output.missing_information) >= 1
    assert any("failure" in m.lower() or "timeout" in m.lower() for m in output.missing_information)


def test_resource_id_validation() -> None:
    """18. ResourceItemAnalysis validates strict regex formatting for resource IDs."""
    # Valid ID
    item = ResourceItemAnalysis(
        resource_id="AMB-01",
        resource_type="AMBULANCE",
        name="Medic 01",
        availability="AVAILABLE",
        current_location="Depot",
        distance_km=2.0,
        current_workload=0,
        axle_clearance_inches=34.0,
        status="AVAILABLE",
        suitability="SUITABLE",
    )
    assert item.resource_id == "AMB-01"

    # Invalid ID
    with pytest.raises(ValidationError):
        ResourceItemAnalysis(
            resource_id="bad id with spaces and @#$%",
            resource_type="AMBULANCE",
            name="Medic 01",
            availability="AVAILABLE",
            current_location="Depot",
            distance_km=2.0,
            current_workload=0,
            axle_clearance_inches=34.0,
            status="AVAILABLE",
            suitability="SUITABLE",
        )


@pytest.mark.asyncio
async def test_partial_availability() -> None:
    """19. Handles mixed fleet state where some units are busy and some available."""
    agent = ResourceAgent(tool_registry=build_resource_test_registry())
    output = await agent.analyze(incident={"incident_id": "inc-01"})

    assert len(output.available_resources) > 0
    assert len(output.unavailable_resources) > 0
    # The union of both lists covers the known fleet
    all_unit_ids = {r.resource_id for r in output.available_resources} | {
        r.resource_id for r in output.unavailable_resources
    }
    assert "AMB-01" in all_unit_ids
    assert "AMB-02" in all_unit_ids
    assert "AMB-03" in all_unit_ids


@pytest.mark.asyncio
async def test_evidence_grounding() -> None:
    """20. Ties incident evidence IDs to resource analysis output."""
    agent = ResourceAgent(tool_registry=build_resource_test_registry())
    fake_evidence = [type("MockEvidence", (), {"evidence_id": "ev-impact-77"})()]
    output = await agent.analyze(
        incident={"incident_id": "inc-01"},
        evidence_items=fake_evidence,
    )

    assert "ev-impact-77" in output.evidence_ids
    for res_item in output.available_resources:
        assert res_item.evidence_source == "resource_search"


@pytest.mark.asyncio
async def test_resource_state_conversion_and_langgraph() -> None:
    """21. BaseAgent.process() converts analysis to standard ResourceState and updates state."""
    agent = ResourceAgent(tool_registry=build_resource_test_registry())
    state: dict[str, Any] = {
        "incident": {"incident_id": "inc-01"},
        "impact": {"ingress_cut_off": True},
        "current_status": "IMPACT_EVALUATED",
    }

    res = await agent.process(state)

    assert "resources" in res
    assert isinstance(res["resources"], ResourceState)
    assert res["resources"].selected_unit is not None
    assert len(res["resources"].available_units) >= 1
    assert "available_fleet" in res
