"""Unit Tests for Shared NEXUS Agent State Model & Structured Output Schemas.

Tests:
- Valid state (all 14 structured fields fully populated)
- Invalid state (validation errors, bounds checks, forbidden fields, illegal literals)
- Partial state (incremental updates, LangGraph node merges, empty state baselines)
- Serialization / Deserialization (round-trip JSON preservation, checkpointer format)
"""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agents.schemas import (
    ActionExecutionReceipt,
    AgentErrorItem,
    ApprovalRecordData,
    EvidenceItem,
    ExecutionMetadata,
    ImpactAssessment,
    IncidentData,
    IncidentLocation,
    MemoryItem,
    MemoryState,
    MonitoringData,
    PlanActionItem,
    PlanData,
    ResourceItem,
    ResourceState,
    RiskAssessmentData,
    RouteOption,
    RoutingState,
    VerificationResult,
)
from agents.state import (
    NexusStateModel,
    create_empty_nexus_state,
    create_initial_nexus_state,
    deserialize_nexus_state,
    merge_nexus_state,
    serialize_nexus_state,
    validate_nexus_state,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------
@pytest.fixture
def sample_incident() -> IncidentData:
    return IncidentData(
        incident_id="inc-test-001",
        description="Flash flood blocking City Hospital trauma center entrance.",
        category="FLOODING",
        severity="SEVERE",
        location=IncidentLocation(
            latitude=8.5241, longitude=76.9366, address_reference="River Road & Hospital Way"
        ),
        reported_at=datetime.now(UTC),
        reporter_type="CITIZEN",
        affected_radius_meters=750.0,
    )


@pytest.fixture
def fully_populated_state_model(sample_incident: IncidentData) -> NexusStateModel:
    now = datetime.now(UTC)
    return NexusStateModel(
        incident=sample_incident,
        evidence=[
            EvidenceItem(
                evidence_id="ev-01",
                source_id="WS-CITY-01",
                source_type="WATER_SENSOR",
                confidence=0.95,
                data={"flood_level": "HIGH", "depth_inches": 24.5},
            ),
            EvidenceItem(
                evidence_id="ev-02",
                source_id="RADAR-METRO-DOPPLER",
                source_type="RADAR",
                confidence=0.90,
                data={"heavy_rainfall": True, "rate_mm_hr": 48.0},
            ),
        ],
        verification=VerificationResult(
            verified=True,
            confidence=0.92,
            evidence_ids=["ev-01", "ev-02"],
            primary_factors=["IoT water gauge surge", "Doppler radar precipitation"],
            reasoning="Multiple independent sensor streams corroborate critical flooding.",
            verified_at=now,
        ),
        impact=ImpactAssessment(
            affected_hospital="CITY-HOSPITAL",
            hospital_access="AT_RISK",
            affected_roads=["ROUTE-A"],
            emergency_access_risk="HIGH",
            estimated_delay_minutes=15.0,
            secondary_hazards=["Substation power fluctuations"],
            narrative="Primary emergency corridor ROUTE-A impassable for standard vehicles.",
            assessed_at=now,
        ),
        resources=ResourceState(
            available_units=["AMB-01", "AMB-03"],
            selected_unit="AMB-01",
            selection_criteria=["available", "shortest_distance", "lowest_workload"],
            allocated_resources=[
                ResourceItem(
                    resource_id="AMB-01",
                    resource_type="HIGH_WATER_RESCUE",
                    callsign="Medic-Rescue 01",
                    status="RESERVED",
                    distance_km=2.1,
                    current_workload=1,
                    axle_clearance_inches=34.0,
                    reserved_for_incident="inc-test-001",
                    reservation_token="trk-test-123",
                )
            ],
        ),
        routes=RoutingState(
            selected_route_id="ROUTE-B",
            active_routes=[
                RouteOption(
                    route_id="ROUTE-B",
                    name="Industrial Way Detour",
                    status="SAFE",
                    distance_km=4.2,
                    estimated_time_minutes=11.0,
                    flood_depth_inches=4.0,
                    waypoints=[[8.5190, 76.9310], [8.5210, 76.9450], [8.5280, 76.9420]],
                    is_preferred=True,
                )
            ],
            blocked_routes=["ROUTE-A"],
            alternative_routes=["ROUTE-C"],
            total_distance_km=4.2,
            estimated_eta_minutes=11.0,
        ),
        plan=PlanData(
            plan_id="plan-001",
            version=1,
            status="APPROVED",
            actions=[
                PlanActionItem(
                    action_id="act-01",
                    action_type="SELECT_SAFE_ROUTE",
                    target_entity="ROUTE-B",
                    sequence=1,
                    risk_level="LOW",
                    status="COMPLETED",
                ),
                PlanActionItem(
                    action_id="act-02",
                    action_type="RESERVE_AMBULANCE",
                    target_entity="AMB-01",
                    sequence=2,
                    risk_level="MEDIUM",
                    requires_approval=True,
                    status="APPROVED",
                ),
            ],
        ),
        risk_assessment=RiskAssessmentData(
            overall_risk_level="MEDIUM",
            human_approval_required=True,
            high_risk_actions=["RESERVE_AMBULANCE"],
            policy_rules_triggered=["POLICY-RESOURCE-DISPATCH-TIER3"],
            justification="Resource allocation commits municipal emergency units.",
            assessed_at=now,
        ),
        approval=ApprovalRecordData(
            approval_id="appr-001",
            action_id="act-02",
            action_type="RESERVE_AMBULANCE",
            target_entity="AMB-01",
            risk_level="MEDIUM",
            status="APPROVED",
            reason="Confirmed high-water unit required for patient transfer.",
            reviewer_id="Commander Elena Vance",
            decision_token="tok-auth-456",
            decided_at=now,
        ),
        actions=[
            ActionExecutionReceipt(
                action_id="act-02",
                action_type="RESERVE_AMBULANCE",
                target_entity="AMB-01",
                status="COMPLETED",
                output_payload={"token": "trk-test-123", "bay": "Depot West"},
                executed_at=now,
                execution_duration_ms=45.2,
            )
        ],
        monitoring=MonitoringData(
            monitored_corridor="ROUTE-B",
            corridor_status="SAFE",
            environment_changed=False,
            water_level_inches=4.2,
            anomalies_detected=[],
            replan_triggered=False,
            last_checked_at=now,
        ),
        memory=MemoryState(
            retrieved_playbooks=[
                MemoryItem(
                    record_id="mem-01",
                    record_type="SEMANTIC_PLAYBOOK",
                    title="Hospital Flash Flood Protocol 4B",
                    content="Pre-emptively divert ambulances to elevated ring roads.",
                    relevance_score=0.94,
                )
            ],
            applied_heuristics=["H-ROUTING-CANAL-BYPASS"],
        ),
        errors=[],
        metadata=ExecutionMetadata(
            run_id="run-001",
            thread_id="th-001",
            current_step="MONITORING",
            plan_version=1,
            agent_hops=6,
            llm_model_used="gemini-2.5-flash",
        ),
    )


# -----------------------------------------------------------------------------
# 1. Valid State Tests
# -----------------------------------------------------------------------------
def test_valid_state_all_14_fields(fully_populated_state_model: NexusStateModel):
    """Assert fully populated state satisfies schema and exposes all 14 structured fields."""
    model = fully_populated_state_model

    # Verify every required field is populated and accessible
    assert model.incident is not None
    assert model.incident.incident_id == "inc-test-001"
    assert model.incident.location.latitude == 8.5241
    assert model.incident.location.longitude == 76.9366

    assert len(model.evidence) == 2
    assert model.evidence[0].source_id == "WS-CITY-01"

    assert model.verification is not None
    assert model.verification.verified is True
    assert model.verification.confidence == 0.92

    assert model.impact is not None
    assert model.impact.affected_hospital == "CITY-HOSPITAL"
    assert model.impact.emergency_access_risk == "HIGH"

    assert model.resources.selected_unit == "AMB-01"
    assert len(model.resources.allocated_resources) == 1

    assert model.routes.selected_route_id == "ROUTE-B"
    assert len(model.routes.active_routes) == 1

    assert model.plan is not None
    assert model.plan.version == 1
    assert len(model.plan.actions) == 2

    assert model.risk_assessment is not None
    assert model.risk_assessment.overall_risk_level == "MEDIUM"
    assert model.risk_assessment.human_approval_required is True

    assert model.approval is not None
    assert model.approval.status == "APPROVED"
    assert model.approval.reviewer_id == "Commander Elena Vance"

    assert len(model.actions) == 1
    assert model.actions[0].status == "COMPLETED"

    assert model.monitoring is not None
    assert model.monitoring.monitored_corridor == "ROUTE-B"

    assert len(model.memory.retrieved_playbooks) == 1
    assert model.memory.retrieved_playbooks[0].relevance_score == 0.94

    assert len(model.errors) == 0

    assert model.metadata.agent_hops == 6
    assert model.metadata.llm_model_used == "gemini-2.5-flash"

    # Validate state helper function
    validated = validate_nexus_state(model.to_langgraph_dict())
    assert validated.incident is not None
    assert validated.incident.incident_id == "inc-test-001"


# -----------------------------------------------------------------------------
# 2. Invalid State Tests
# -----------------------------------------------------------------------------
def test_invalid_state_coordinate_bounds():
    """Assert invalid coordinates outside latitude [-90, 90] or longitude [-180, 180] raise ValidationError."""
    with pytest.raises(ValidationError):
        IncidentLocation(latitude=91.0, longitude=76.9366)

    with pytest.raises(ValidationError):
        IncidentLocation(latitude=8.5241, longitude=-185.0)


def test_invalid_state_confidence_bounds():
    """Assert confidence scores outside [0.0, 1.0] raise ValidationError."""
    with pytest.raises(ValidationError):
        EvidenceItem(
            source_id="TEST-01",
            source_type="WATER_SENSOR",
            confidence=1.25,  # > 1.0 invalid
        )

    with pytest.raises(ValidationError):
        VerificationResult(
            verified=True,
            confidence=-0.1,  # < 0.0 invalid
            reasoning="Test reasoning string",
        )


def test_invalid_state_forbidden_extra_fields():
    """Assert extra unexpected fields raise ValidationError (ConfigDict extra='forbid')."""
    with pytest.raises(ValidationError):
        IncidentData(
            description="Flooding near City Hospital",
            location=IncidentLocation(latitude=8.5241, longitude=76.9366),
            unexpected_hallucinated_field="ILLEGAL",  # Extra field
        )

    with pytest.raises(ValidationError):
        NexusStateModel(
            hallucinated_agent_scratchpad="NotAllowedInSharedState",
        )


def test_invalid_state_sequence_and_distance_bounds():
    """Assert negative sequence orders and negative distances fail validation."""
    with pytest.raises(ValidationError):
        PlanActionItem(
            action_type="SELECT_AMBULANCE",
            target_entity="AMB-01",
            sequence=0,  # Must be >= 1
            risk_level="LOW",
        )

    with pytest.raises(ValidationError):
        RouteOption(
            route_id="ROUTE-A",
            name="Route A",
            status="SAFE",
            distance_km=-5.0,  # Negative distance invalid
            estimated_time_minutes=10.0,
        )


def test_validate_nexus_state_helper_rejects_malformed_dict():
    """Assert validate_nexus_state raises ValueError on invalid payload."""
    malformed_dict = {
        "incident": {
            "description": "Short",  # Fails min_length
            "location": {"latitude": 999.0, "longitude": 0.0},
        }
    }
    with pytest.raises(ValueError, match="NexusState validation failure"):
        validate_nexus_state(malformed_dict)


# -----------------------------------------------------------------------------
# 3. Partial State Tests
# -----------------------------------------------------------------------------
def test_partial_state_empty_baseline():
    """Assert create_empty_nexus_state produces a valid baseline state."""
    empty = create_empty_nexus_state()
    assert empty["incident"] is None
    assert empty["evidence"] == []
    assert empty["verification"] is None
    assert empty["impact"] is None
    assert empty["actions"] == []
    assert empty["metadata"]["current_step"] == "START"

    # NexusStateModel can validate empty baseline
    validated = NexusStateModel.model_validate(empty)
    assert validated.incident is None
    assert validated.metadata.current_step == "START"


def test_partial_state_initialization(sample_incident: IncidentData):
    """Assert create_initial_nexus_state sets incident and preserves thread_id."""
    initial = create_initial_nexus_state(sample_incident, thread_id="thread-custom-99")
    assert initial["incident"] is not None
    assert isinstance(initial["incident"], dict)
    assert initial["incident"]["incident_id"] == "inc-test-001"
    assert isinstance(initial["metadata"], dict)
    assert initial["metadata"]["thread_id"] == "thread-custom-99"

    validated = NexusStateModel.model_validate(initial)
    assert validated.incident is not None
    assert validated.incident.incident_id == "inc-test-001"
    assert validated.metadata.thread_id == "thread-custom-99"


def test_partial_state_incremental_merging(sample_incident: IncidentData):
    """Assert merge_nexus_state applies partial agent updates and increments hops."""
    state = create_initial_nexus_state(sample_incident)
    assert isinstance(state["metadata"], dict)
    initial_hops = state["metadata"]["agent_hops"]
    assert initial_hops == 0

    # Verification Agent completes
    veri_update = {
        "verification": VerificationResult(
            verified=True,
            confidence=0.90,
            evidence_ids=["ev-10"],
            reasoning="Verified by dual stream gauges.",
        ).model_dump(mode="json")
    }
    state = merge_nexus_state(state, veri_update)
    assert isinstance(state["metadata"], dict)
    assert isinstance(state["verification"], dict)
    assert state["metadata"]["agent_hops"] == 1
    assert state["verification"]["verified"] is True

    # Impact Agent completes
    impact_update = {
        "impact": ImpactAssessment(
            affected_hospital="CITY-HOSPITAL",
            hospital_access="AT_RISK",
            affected_roads=["ROUTE-A"],
            emergency_access_risk="HIGH",
        ).model_dump(mode="json")
    }
    state = merge_nexus_state(state, impact_update)
    assert isinstance(state["metadata"], dict)
    assert isinstance(state["impact"], dict)
    assert state["metadata"]["agent_hops"] == 2
    assert state["impact"]["affected_hospital"] == "CITY-HOSPITAL"

    # Validate state remains strictly valid after incremental partial merges
    model = validate_nexus_state(state)
    assert model.incident is not None
    assert model.verification is not None
    assert model.impact is not None
    assert model.incident.incident_id == "inc-test-001"
    assert model.verification.confidence == 0.90
    assert model.impact.emergency_access_risk == "HIGH"
    assert model.metadata.agent_hops == 2


# -----------------------------------------------------------------------------
# 4. Serialization & Deserialization Tests
# -----------------------------------------------------------------------------
def test_serialization_and_deserialization_roundtrip(fully_populated_state_model: NexusStateModel):
    """Assert complete state serializes to JSON and deserializes identically."""
    original = fully_populated_state_model

    # 1. Serialize to JSON string
    json_str = serialize_nexus_state(original)
    assert isinstance(json_str, str)
    assert "inc-test-001" in json_str
    assert "ROUTE-B" in json_str
    assert "CITY-HOSPITAL" in json_str

    # 2. Deserialize from JSON string
    reconstructed = deserialize_nexus_state(json_str)
    assert isinstance(reconstructed, NexusStateModel)

    # 3. Assert deep semantic equality
    assert reconstructed.incident is not None and original.incident is not None
    assert reconstructed.verification is not None and original.verification is not None
    assert reconstructed.impact is not None and original.impact is not None
    assert reconstructed.plan is not None and original.plan is not None
    assert reconstructed.approval is not None and original.approval is not None
    assert reconstructed.incident.incident_id == original.incident.incident_id
    assert reconstructed.incident.location.latitude == original.incident.location.latitude
    assert reconstructed.verification.confidence == original.verification.confidence
    assert reconstructed.impact.affected_hospital == original.impact.affected_hospital
    assert reconstructed.resources.selected_unit == original.resources.selected_unit
    assert reconstructed.routes.selected_route_id == original.routes.selected_route_id
    assert len(reconstructed.plan.actions) == len(original.plan.actions)
    assert reconstructed.approval.decision_token == original.approval.decision_token
    assert reconstructed.actions[0].output_payload == original.actions[0].output_payload
    assert reconstructed.metadata.agent_hops == original.metadata.agent_hops


def test_langgraph_dict_conversion(fully_populated_state_model: NexusStateModel):
    """Assert to_langgraph_dict produces JSON-primitive dictionary suitable for LangGraph checkpointers."""
    model = fully_populated_state_model
    lg_dict = model.to_langgraph_dict()

    assert isinstance(lg_dict, dict)
    # Ensure serializable via standard json.dumps
    dumped = json.dumps(lg_dict)
    assert isinstance(dumped, str)

    # Reconstruct from dict
    restored = NexusStateModel.from_langgraph_dict(dict(lg_dict))
    assert restored.incident is not None
    assert restored.approval is not None
    assert restored.incident.incident_id == "inc-test-001"
    assert restored.approval.reviewer_id == "Commander Elena Vance"


def test_agent_error_recording_in_state():
    """Assert error events are captured cleanly in the state schema."""
    state = create_empty_nexus_state()
    err = AgentErrorItem(
        node_name="ROUTING_NODE",
        error_type="TransientNetworkTimeout",
        message="Simulated sensor probe timed out; fallback applied.",
        recoverable=True,
    )
    state = merge_nexus_state(state, {"errors": [err.model_dump(mode="json")]})

    validated = validate_nexus_state(state)
    assert len(validated.errors) == 1
    assert validated.errors[0].node_name == "ROUTING_NODE"
    assert validated.errors[0].recoverable is True
