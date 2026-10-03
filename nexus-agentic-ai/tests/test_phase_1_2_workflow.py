import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.enums import ActionStatus, IncidentStatus
from database.repository import (
    ActionRepository,
    ApprovalRepository,
    AuditLogRepository,
    EvidenceRepository,
    IncidentRepository,
    RouteRepository,
)
from database.session import Base
from orchestration.graph import InvalidStateTransitionError, NexusOrchestrator
from orchestration.risk_gate import DeterministicRiskGate
from orchestration.state import ActionItem
from tools.resource_inventory import ResourceInventoryTool
from tools.routing_engine import RoutingEngineTool


@pytest_asyncio.fixture
async def session():
    """Create an isolated async database session for workflow verification."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as s:
        yield s

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_complete_18_step_workflow(session: AsyncSession):
    """Verify complete 18-step hospital flooding operational response lifecycle."""
    orchestrator = NexusOrchestrator()

    # -------------------------------------------------------------------------
    # STEP 1: Create hospital flooding incident
    # -------------------------------------------------------------------------
    state, inc = await orchestrator.step_1_create_incident(session)
    assert inc.id is not None
    assert state["current_status"] == "INGESTED"
    assert state["extracted_features"]["hazard_level"] == "critical"
    assert state["extracted_features"]["threatened_facility"] == "St. Jude Memorial Hospital"

    # -------------------------------------------------------------------------
    # STEP 2: Collect synthetic evidence
    # -------------------------------------------------------------------------
    evidence_items = await orchestrator.step_2_collect_evidence(session, state)
    assert len(evidence_items) >= 3
    assert len(state["evidence_trail"]) >= 3
    db_evidence = await EvidenceRepository.list_by_incident(session, inc.id)
    assert len(db_evidence) == len(evidence_items)

    # -------------------------------------------------------------------------
    # STEP 3: Verify incident
    # -------------------------------------------------------------------------
    verified_inc = await orchestrator.step_3_verify_incident(session, state)
    assert verified_inc.status == IncidentStatus.VERIFIED
    assert state["current_status"] == "VERIFIED"
    assert state["verification_confidence"] >= 0.85

    # -------------------------------------------------------------------------
    # STEP 4: Calculate impact
    # -------------------------------------------------------------------------
    impacted_inc = await orchestrator.step_4_calculate_impact(session, state)
    assert impacted_inc.status == IncidentStatus.IMPACT_EVALUATED
    assert state["current_status"] == "IMPACT_EVALUATED"
    assert state["impact_assessment"].ingress_cut_off is True
    assert "Metropolitan Parkway" in state["impact_assessment"].severely_affected_corridors

    # -------------------------------------------------------------------------
    # STEP 5: Find available ambulance
    # -------------------------------------------------------------------------
    fleet = await orchestrator.step_5_find_ambulance(session, state)
    assert len(fleet) >= 1
    # Check for no fabricated resources
    for unit in fleet:
        assert unit["resource_type"] == "high_water_ambulance"
    assert any(u["unit_id"] == "MEDIC-RESCUE-44" for u in fleet)

    # -------------------------------------------------------------------------
    # STEP 6: Calculate safe route
    # -------------------------------------------------------------------------
    route_beta = await orchestrator.step_6_calculate_safe_route(session, state)
    assert state["current_status"] == "ROUTED"
    assert "BETA" in state["selected_primary_route_id"]
    assert route_beta.total_distance_km == 6.4
    assert route_beta.is_compromised is False

    # -------------------------------------------------------------------------
    # STEP 7: Create action DAG
    # -------------------------------------------------------------------------
    plan_v1, actions_v1 = await orchestrator.step_7_create_action_dag(session, state)
    assert plan_v1.version == 1
    assert len(actions_v1) == 4
    action_types = [a.action_type for a in actions_v1]
    assert "UPDATE_VARIABLE_MESSAGE_SIGN" in action_types
    assert "CLOSE_PRIMARY_ARTERY" in action_types
    assert "RESERVE_AMBULANCE" in action_types
    assert "NOTIFY_HOSPITAL_TRAUMA_BAY" in action_types

    # -------------------------------------------------------------------------
    # STEP 8: Trigger deterministic policy gate
    # -------------------------------------------------------------------------
    needs_approval = await orchestrator.step_8_trigger_policy_gate(session, state)
    assert needs_approval is True
    assert state["requires_human_approval"] is True
    # Tier 4 High and Tier 3 Medium must require approval
    for a in state["action_plan"]:
        if a.action_type in ["CLOSE_PRIMARY_ARTERY", "RESERVE_AMBULANCE"]:
            assert a.approval_required is True
            assert a.approval_status == "PENDING"
        elif a.action_type in ["UPDATE_VARIABLE_MESSAGE_SIGN", "NOTIFY_HOSPITAL_TRAUMA_BAY"]:
            assert a.approval_required is False
            assert a.approval_status == "AUTO_APPROVED"

    # -------------------------------------------------------------------------
    # STEP 9: Confirm HITL interrupt occurs
    # -------------------------------------------------------------------------
    interrupt_info = await orchestrator.step_9_confirm_hitl_interrupt(session, state)
    assert interrupt_info["status"] == "AWAITING_APPROVAL"
    assert interrupt_info["interrupted"] is True
    assert state["current_status"] == "AWAITING_APPROVAL"

    # Confirm DB persistence unbroken across interrupt boundary
    pending_approvals = await ApprovalRepository.list_pending(session, inc.id)
    assert len(pending_approvals) == 1
    reloaded_inc = await IncidentRepository.get_by_id(session, inc.id)
    assert reloaded_inc.status == IncidentStatus.AWAITING_APPROVAL

    # -------------------------------------------------------------------------
    # STEP 10: Approve reservation
    # -------------------------------------------------------------------------
    decision = await orchestrator.step_10_approve_reservation(
        session, state, reviewer_id="Elena Vance", rationale="High-water ambulance authorized"
    )
    assert decision["decision"] == "APPROVED"
    assert decision["decision_token"].startswith("tok-")

    # Confirm approval record in DB
    updated_approvals = await ApprovalRepository.list_pending(session, inc.id)
    assert len(updated_approvals) == 0  # No longer pending

    # -------------------------------------------------------------------------
    # STEP 11: Execute simulated reservation
    # -------------------------------------------------------------------------
    exec_results = await orchestrator.step_11_execute_reservation(session, state)
    assert len(exec_results) == 4
    assert state["current_status"] == "EXECUTING"
    for act in state["action_plan"]:
        assert act.executed is True
        assert act.execution_result is not None

    # Confirm DB actions updated to COMPLETED
    db_acts = await ActionRepository.list_by_plan(session, plan_v1.id)
    for db_act in db_acts:
        assert db_act.status == ActionStatus.COMPLETED

    # -------------------------------------------------------------------------
    # STEP 12: Start monitoring
    # -------------------------------------------------------------------------
    state = await orchestrator.step_12_start_monitoring(session, state)
    assert state["current_status"] == "MONITORING"
    assert "SG-INDUSTRIAL-202" in state["monitored_sensor_ids"]
    assert state["telemetry_surge_detected"] is False

    # -------------------------------------------------------------------------
    # STEP 13: Inject ROUTE-B failure
    # -------------------------------------------------------------------------
    chaos_res = await orchestrator.step_13_inject_route_b_failure(session, state)
    assert chaos_res["surge_injected"] is True
    assert chaos_res["water_level_in"] == 26.5

    # Confirm route marked compromised in DB
    db_routes = await RouteRepository.get_by_incident(session, inc.id)
    beta_route = next(r for r in db_routes if "BETA" in r.route_name.upper())
    assert beta_route.is_compromised is True

    # -------------------------------------------------------------------------
    # STEP 14: Detect environmental change
    # -------------------------------------------------------------------------
    detected = await orchestrator.step_14_detect_environmental_change(session, state)
    assert detected is True
    assert state["telemetry_surge_detected"] is True
    assert state["current_status"] == "REPLANNING"

    # -------------------------------------------------------------------------
    # STEP 15: Invalidate stale plan
    # -------------------------------------------------------------------------
    invalidated_plan = await orchestrator.step_15_invalidate_stale_plan(session, state)
    assert invalidated_plan.status == "INVALIDATED_BY_SURGE"

    # -------------------------------------------------------------------------
    # STEP 16: Generate replacement route (Route Gamma)
    # -------------------------------------------------------------------------
    route_gamma = await orchestrator.step_16_generate_replacement_route(session, state)
    assert "GAMMA" in route_gamma.route_name.upper()
    assert state["selected_primary_route_id"] == "ROUTE-GAMMA-OVERPASS"
    assert route_gamma.total_distance_km == 7.8
    assert route_gamma.max_water_clearance_supported_inches == 48.0

    # -------------------------------------------------------------------------
    # STEP 17: Produce new plan version (Plan v2)
    # -------------------------------------------------------------------------
    plan_v2, actions_v2 = await orchestrator.step_17_produce_new_plan_version(session, state)
    assert plan_v2.version == 2
    assert len(actions_v2) == 4
    assert state["replan_iteration_count"] == 1
    assert state["current_status"] == "PLAN_SYNTHESIZED"

    # -------------------------------------------------------------------------
    # STEP 18: Continue execution safely
    # -------------------------------------------------------------------------
    final_res = await orchestrator.step_18_continue_execution_safely(session, state)
    assert final_res["status"] == "RESOLVED"
    assert final_res["plan_version"] == 2
    assert final_res["actions_executed"] == 4
    assert final_res["audit_chain_valid"] is True
    assert state["current_status"] == "RESOLVED"

    # Verify cryptographic audit ledger completeness
    audit_chain_ok = await AuditLogRepository.verify_chain_integrity(session)
    assert audit_chain_ok is True


@pytest.mark.asyncio
async def test_safety_violations_prevented(session: AsyncSession):
    """Test safety guardrails preventing policy bypass, unapproved execution, and duplicate execution."""
    gate = DeterministicRiskGate()

    # 1. Test LLM attempting to mark Tier 4 action as auto-approved
    bypassed_action = ActionItem(
        action_id="act-bypass-01",
        sequence_order=1,
        action_type="CLOSE_PRIMARY_ARTERY",
        target_entity="Metropolitan Parkway",
        risk_tier="TIER_1_AUTO",  # Attempted downgrade
        description="LLM claims closing artery is low risk",
        execution_payload={},
        approval_required=False,  # Attempted bypass
        approval_status="AUTO_APPROVED",  # Attempted bypass
    )
    evaluated, needs_app = gate.evaluate_plan([bypassed_action])
    assert needs_app is True
    assert evaluated[0].risk_tier == "TIER_4_HIGH"
    assert evaluated[0].approval_required is True
    assert evaluated[0].approval_status == "PENDING"

    # 2. Test execution of unapproved action raises PermissionError
    with pytest.raises(PermissionError) as exc_info:
        gate.validate_execution_permission(evaluated[0], decision_token=None)
    assert "cannot execute without explicit human commander approval" in str(exc_info.value)

    # 3. Test execution without decision token raises PermissionError even if approved
    evaluated[0].approval_status = "APPROVED"
    with pytest.raises(PermissionError) as exc_token:
        gate.validate_execution_permission(evaluated[0], decision_token=None)
    assert "requires a valid signed commander authorization token" in str(exc_token.value)

    # 4. Test duplicate execution prevention
    evaluated[0].executed = True
    with pytest.raises(RuntimeError) as exc_dup:
        gate.validate_execution_permission(evaluated[0], decision_token="tok-valid-12345")
    assert "Duplicate execution prevented" in str(exc_dup.value)


@pytest.mark.asyncio
async def test_tool_hallucination_and_fabrication_prevention():
    """Verify tools do not hallucinate routes or fabricate resource types."""
    # 1. Resource Inventory Tool
    inv_tool = ResourceInventoryTool()
    # Query for water pumps
    pump_res = await inv_tool.run(
        resource_type="mobile_water_pump", near_latitude=37.77, near_longitude=-122.41
    )
    for p in pump_res["resources"]:
        assert p["resource_type"] == "mobile_water_pump"
        assert "AMBULANCE" not in p["unit_id"]

    # 2. Routing Engine Tool
    routing_tool = RoutingEngineTool()
    # If Route Beta is avoided, it MUST return Route Gamma, never Route Beta
    route_res = await routing_tool.run(
        origin_coords=(37.768, -122.410),
        destination_coords=(37.776, -122.421),
        vehicle_clearance_inches=34.0,
        avoid_segments=["Industrial_Way"],
    )
    assert route_res["route_id"] == "ROUTE-GAMMA-OVERPASS"
    assert "Industrial_Way" not in route_res["traversed_segments"]

    # If both Beta and Gamma are avoided, it must return impassable, NOT a hallucinated route
    blocked_res = await routing_tool.run(
        origin_coords=(37.768, -122.410),
        destination_coords=(37.776, -122.421),
        vehicle_clearance_inches=34.0,
        avoid_segments=["Industrial_Way", "North_Ridge_Overpass"],
    )
    assert blocked_res["safe_for_vehicle"] is False
    assert blocked_res["route_id"] == "NO_PASSABLE_ROUTE"
    assert len(blocked_res["waypoints"]) == 0


@pytest.mark.asyncio
async def test_invalid_state_transitions_prevented():
    """Verify that illegal state machine jumps are prevented."""
    orchestrator = NexusOrchestrator()
    # Attempting to jump from INGESTED directly to EXECUTING
    with pytest.raises(InvalidStateTransitionError):
        orchestrator.validate_transition("INGESTED", "EXECUTING")

    # Attempting to jump from AWAITING_APPROVAL directly to RESOLVED
    with pytest.raises(InvalidStateTransitionError):
        orchestrator.validate_transition("AWAITING_APPROVAL", "RESOLVED")
