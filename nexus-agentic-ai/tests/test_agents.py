import pytest

from agents.impact import ImpactAssessmentAgent
from agents.ingestion import IncidentIngestionAgent
from agents.monitoring import MonitoringAgent
from agents.planner import PlanSynthesisAgent
from agents.resource_routing import ResourceRoutingAgent
from agents.verification import VerificationAgent


@pytest.mark.asyncio
async def test_agent_instantiation_and_process():
    """Verify all agents can be instantiated and execute basic process protocol."""
    agents = [
        IncidentIngestionAgent(),
        VerificationAgent(),
        ImpactAssessmentAgent(),
        ResourceRoutingAgent(),
        PlanSynthesisAgent(),
        MonitoringAgent(),
    ]

    state = {"incident_id": "inc-001"}
    for agent in agents:
        assert repr(agent).startswith("<Agent:")
        result = await agent.process(state)
        assert isinstance(result, dict)
        assert "current_status" in result
