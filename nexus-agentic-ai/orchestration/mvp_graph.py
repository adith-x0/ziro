"""NEXUS MVP Complete LangGraph Stateful State Machine.

Constructs the complete operational lifecycle:
START
 ↓
incident
 ↓
verification
 ↓
impact
 ↓
resources
 ↓
routing
 ↓
planning
 ↓
policy_gate
 ↓
HITL interrupt
 ↓
execution
 ↓
monitoring
 ↓
environment change
 ↓
replanning
 ↓
new route
 ↓
END
"""

import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents.mvp_agents import (
    ImpactAgentMVP,
    PlanningAgentMVP,
    ReplanningSupervisorMVP,
    ResourceAgentMVP,
    RoutingAgentMVP,
    VerificationAgentMVP,
)
from orchestration.mvp_models import (
    ActionDAGItem,
    AuditEvent,
    PlanVersionModel,
)
from orchestration.policy_gatekeeper import PolicyGatekeeper
from tools.synthetic_environment import simulated_fleet_service, synthetic_road_network


class NexusMVPState(TypedDict, total=False):
    """Central typed state schema for the NEXUS MVP vertical slice."""

    incident_id: str
    description: str
    latitude: float
    longitude: float
    status: str

    verification: dict[str, Any]
    impact: dict[str, Any]
    selected_ambulance: str
    available_ambulances: list[str]
    routing: dict[str, Any]

    plan_v1: dict[str, Any]
    plan_v2: dict[str, Any] | None
    current_plan_version: int

    approval_record: dict[str, Any] | None
    execution_receipts: list[dict[str, Any]]

    monitoring: dict[str, Any]
    environment_changed: bool
    replan_reason: str | None

    audit_events: list[dict[str, Any]]
    error: str | None


def _create_audit_event(
    incident_id: str,
    event_type: str,
    actor: str,
    summary: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = AuditEvent(
        event_id=f"evt-{uuid.uuid4().hex[:8]}",
        incident_id=incident_id,
        event_type=event_type,  # type: ignore
        actor=actor,
        summary=summary,
        payload=payload or {},
        timestamp=datetime.now(UTC),
    )
    return event.model_dump(mode="json")


# -----------------------------------------------------------------------------
# Node Implementations
# -----------------------------------------------------------------------------
async def incident_node(state: NexusMVPState) -> dict[str, Any]:
    """Validates raw report and initializes incident record."""
    inc_id = state.get("incident_id", f"inc-{uuid.uuid4().hex[:8]}")
    desc = state.get("description", "Heavy flooding near City Hospital emergency entrance.")
    lat = state.get("latitude", 8.5241)
    lon = state.get("longitude", 76.9366)

    event = _create_audit_event(
        incident_id=inc_id,
        event_type="incident.created",
        actor="INGESTION_SYSTEM",
        summary="Citizen incident report received and ingested.",
        payload={"description": desc, "location": {"latitude": lat, "longitude": lon}},
    )

    return {
        "incident_id": inc_id,
        "description": desc,
        "latitude": lat,
        "longitude": lon,
        "status": "RECEIVED",
        "current_plan_version": 1,
        "environment_changed": False,
        "execution_receipts": [],
        "audit_events": [event],
    }


async def verification_node(state: NexusMVPState) -> dict[str, Any]:
    """Queries simulated water sensor, radar, and incident reports to verify incident."""
    inc_id = state["incident_id"]
    lat = state.get("latitude", 8.5241)
    lon = state.get("longitude", 76.9366)

    agent = VerificationAgentMVP()
    veri_started_evt = _create_audit_event(
        incident_id=inc_id,
        event_type="verification.started",
        actor="VERIFICATION_AGENT",
        summary="Queried IoT water stream gauges, radar, and citizen telemetry.",
    )

    res = await agent.verify(lat, lon)

    evidence_evt = _create_audit_event(
        incident_id=inc_id,
        event_type="evidence.collected",
        actor="VERIFICATION_AGENT",
        summary="Collected 3 independent simulated evidence sources.",
        payload={"evidence_ids": res.evidence_ids},
    )

    verified_evt = _create_audit_event(
        incident_id=inc_id,
        event_type="incident.verified",
        actor="VERIFICATION_AGENT",
        summary=f"Incident confirmed with {int(res.confidence * 100)}% verified confidence.",
        payload={"verified": res.verified, "confidence": res.confidence},
    )

    existing_events = list(state.get("audit_events", []))
    existing_events.extend([veri_started_evt, evidence_evt, verified_evt])

    return {
        "status": "VERIFIED",
        "verification": res.model_dump(mode="json"),
        "audit_events": existing_events,
    }


async def impact_node(state: NexusMVPState) -> dict[str, Any]:
    """Evaluates hospital access risk and severed corridors."""
    inc_id = state["incident_id"]
    veri_res = state.get("verification", {})
    lat = state.get("latitude", 8.5241)
    lon = state.get("longitude", 76.9366)

    agent = ImpactAgentMVP()
    impact_res = await agent.analyze(veri_res, lat, lon)

    impact_evt = _create_audit_event(
        incident_id=inc_id,
        event_type="impact.completed",
        actor="IMPACT_AGENT",
        summary=f"Facility {impact_res.affected_hospital} ingress is {impact_res.hospital_access}; Route A flooded.",
        payload=impact_res.model_dump(mode="json"),
    )

    events = list(state.get("audit_events", []))
    events.append(impact_evt)

    return {
        "status": "IMPACT_EVALUATED",
        "impact": impact_res.model_dump(mode="json"),
        "audit_events": events,
    }


async def resources_node(state: NexusMVPState) -> dict[str, Any]:
    """Queries fleet inventory and deterministically selects optimal ambulance."""
    inc_id = state["incident_id"]
    agent = ResourceAgentMVP()
    sel_res = await agent.select_resource()

    resource_evt = _create_audit_event(
        incident_id=inc_id,
        event_type="resource.selected",
        actor="RESOURCE_AGENT",
        summary=f"Deterministically selected ambulance {sel_res.selected_ambulance}.",
        payload=sel_res.model_dump(mode="json"),
    )

    events = list(state.get("audit_events", []))
    events.append(resource_evt)

    return {
        "status": "RESOURCES_SELECTED",
        "selected_ambulance": sel_res.selected_ambulance,
        "available_ambulances": sel_res.available_ambulances,
        "audit_events": events,
    }


async def routing_node(state: NexusMVPState) -> dict[str, Any]:
    """Calculates safe topological path bypassing flooded Route A."""
    inc_id = state["incident_id"]
    agent = RoutingAgentMVP()
    route_res = await agent.route()

    route_evt = _create_audit_event(
        incident_id=inc_id,
        event_type="route.selected",
        actor="ROUTING_ENGINE",
        summary=f"Selected {route_res.selected_route} (ETA {route_res.estimated_time_minutes} min).",
        payload=route_res.model_dump(mode="json"),
    )

    events = list(state.get("audit_events", []))
    events.append(route_evt)

    return {
        "status": "ROUTED",
        "routing": route_res.model_dump(mode="json"),
        "audit_events": events,
    }


async def planning_node(state: NexusMVPState) -> dict[str, Any]:
    """Synthesizes structured action DAG for Plan v1."""
    inc_id = state["incident_id"]
    amb_id = state["selected_ambulance"]
    route_id = state["routing"]["selected_route"]

    agent = PlanningAgentMVP()
    plan_v1 = await agent.create_plan(inc_id, amb_id, route_id)

    plan_evt = _create_audit_event(
        incident_id=inc_id,
        event_type="plan.created",
        actor="PLANNER_AGENT",
        summary=f"Synthesized Plan v1 with {len(plan_v1.actions)} sequenced actions.",
        payload={"plan_id": plan_v1.plan_id, "actions_count": len(plan_v1.actions)},
    )

    events = list(state.get("audit_events", []))
    events.append(plan_evt)

    return {
        "status": "PLAN_CREATED",
        "plan_v1": plan_v1.model_dump(mode="json"),
        "audit_events": events,
    }


async def policy_gate_node(state: NexusMVPState) -> dict[str, Any]:
    """Applies strict deterministic policy rules and calls interrupt() for human approval."""
    inc_id = state["incident_id"]
    plan_dict = state["plan_v1"]
    raw_actions = [ActionDAGItem(**a) for a in plan_dict.get("actions", [])]

    # Evaluate action permissions deterministically
    evaluated_actions, approvals, requires_approval = PolicyGatekeeper.evaluate_plan(
        raw_actions, inc_id
    )

    plan_dict["actions"] = [a.model_dump(mode="json") for a in evaluated_actions]
    events = list(state.get("audit_events", []))

    if requires_approval and approvals:
        primary_approval = approvals[0]
        approval_dict = primary_approval.model_dump(mode="json")

        appr_req_evt = _create_audit_event(
            incident_id=inc_id,
            event_type="approval.requested",
            actor="POLICY_GATEKEEPER",
            summary=f"Action RESERVE_AMBULANCE requires human authorization (Risk: {primary_approval.risk_level}).",
            payload=approval_dict,
        )
        events.append(appr_req_evt)

        plan_dict["status"] = "AWAITING_APPROVAL"

        # ---------------------------------------------------------------------
        # LANGGRAPH HUMAN-IN-THE-LOOP INTERRUPT
        # Pauses graph execution until human commander issues APPROVE / REJECT
        # ---------------------------------------------------------------------
        interrupt_payload = {
            "incident_id": inc_id,
            "approval_id": primary_approval.approval_id,
            "action": primary_approval.action_type,
            "target": primary_approval.target_entity,
            "risk_level": primary_approval.risk_level,
            "reason": primary_approval.reason,
            "supporting_evidence_count": primary_approval.supporting_evidence_count,
        }

        # Halt and await human decision
        human_decision = interrupt(interrupt_payload)

        # Resumed from interrupt with human decision
        decision = human_decision.get("decision", "APPROVED")
        reviewer_id = human_decision.get("reviewer_id", "Elena Vance (EOC Watch Commander)")
        token = human_decision.get("decision_token", f"tok-{uuid.uuid4().hex[:12]}")

        primary_approval.status = decision
        primary_approval.decided_at = datetime.now(UTC)
        primary_approval.reviewer_id = reviewer_id
        primary_approval.decision_token = token
        approval_dict = primary_approval.model_dump(mode="json")

        if decision == "APPROVED":
            appr_dec_evt = _create_audit_event(
                incident_id=inc_id,
                event_type="approval.approved",
                actor="HUMAN_COMMANDER",
                summary=f"Commander {reviewer_id} APPROVED reservation of {primary_approval.target_entity}.",
                payload=approval_dict,
            )
            events.append(appr_dec_evt)
            # Mark action approved in DAG
            for a in plan_dict["actions"]:
                if a["action_type"] == primary_approval.action_type:
                    a["status"] = "APPROVED"

            plan_dict["status"] = "APPROVED"
            return {
                "status": "APPROVED",
                "plan_v1": plan_dict,
                "approval_record": approval_dict,
                "audit_events": events,
            }
        else:
            appr_dec_evt = _create_audit_event(
                incident_id=inc_id,
                event_type="approval.rejected",
                actor="HUMAN_COMMANDER",
                summary=f"Commander {reviewer_id} REJECTED action {primary_approval.action_type}.",
                payload=approval_dict,
            )
            events.append(appr_dec_evt)
            for a in plan_dict["actions"]:
                if a["action_type"] == primary_approval.action_type:
                    a["status"] = "REJECTED"

            plan_dict["status"] = "REJECTED"
            return {
                "status": "REJECTED",
                "plan_v1": plan_dict,
                "approval_record": approval_dict,
                "audit_events": events,
            }

    plan_dict["status"] = "APPROVED"
    return {
        "status": "APPROVED",
        "plan_v1": plan_dict,
        "approval_record": None,
        "audit_events": events,
    }


async def execution_node(state: NexusMVPState) -> dict[str, Any]:
    """Executes approved ambulance reservation against simulated fleet service with idempotency."""
    inc_id = state["incident_id"]
    amb_id = state["selected_ambulance"]
    plan_dict = state["plan_v1"]

    if state.get("status") == "REJECTED":
        return {"status": "REJECTED"}

    # Execute reservation against fleet service
    receipt = simulated_fleet_service.reserve_ambulance(amb_id, inc_id)

    # Update action status to COMPLETED
    for act in plan_dict.get("actions", []):
        if act["action_type"] == "RESERVE_AMBULANCE":
            act["status"] = "COMPLETED"
            act["execution_result"] = receipt.model_dump(mode="json")
        elif act["action_type"] == "NOTIFY_HOSPITAL":
            act["status"] = "COMPLETED"
            act["execution_result"] = {
                "alert": "Inbound transport inbound via Route B Industrial Detour."
            }

    plan_dict["status"] = "COMPLETED"

    exec_evt = _create_audit_event(
        incident_id=inc_id,
        event_type="action.executed",
        actor="EXECUTION_AGENT",
        summary=f"Ambulance {amb_id} successfully reserved with token {receipt.tracking_token}.",
        payload={
            "tool": "fleet_service.reserve_ambulance",
            "receipt": receipt.model_dump(mode="json"),
            "idempotent": receipt.idempotent_replay,
        },
    )

    events = list(state.get("audit_events", []))
    events.append(exec_evt)

    receipts = list(state.get("execution_receipts", []))
    receipts.append(receipt.model_dump(mode="json"))

    return {
        "status": "EXECUTING",
        "plan_v1": plan_dict,
        "execution_receipts": receipts,
        "audit_events": events,
    }


async def monitoring_node(state: NexusMVPState) -> dict[str, Any]:
    """Initial surveillance along active corridor (Route B = SAFE)."""
    events = list(state.get("audit_events", []))

    mon_status = {
        "monitored_corridor": "ROUTE-B",
        "route_status": "SAFE",
        "timestamp": datetime.now(UTC).isoformat(),
    }

    return {
        "status": "MONITORING",
        "monitoring": mon_status,
        "audit_events": events,
    }


async def environment_change_node(state: NexusMVPState) -> dict[str, Any]:
    """Simulated environmental change injection: ROUTE-B = BLOCKED."""
    inc_id = state["incident_id"]

    # Block route in synthetic road network
    synthetic_road_network.block_route("ROUTE-B")

    env_evt = _create_audit_event(
        incident_id=inc_id,
        event_type="environment.changed",
        actor="MONITORING_SUPERVISOR",
        summary="Hydrological sensor surge detected: ROUTE-B is BLOCKED.",
        payload={"blocked_route": "ROUTE-B", "new_status": "BLOCKED"},
    )

    events = list(state.get("audit_events", []))
    events.append(env_evt)

    return {
        "status": "ENVIRONMENT_CHANGED",
        "environment_changed": True,
        "monitoring": {"monitored_corridor": "ROUTE-B", "route_status": "BLOCKED"},
        "audit_events": events,
    }


async def replanning_node(state: NexusMVPState) -> dict[str, Any]:
    """Invalidates Plan v1 and synthesizes Plan v2 with ROUTE-C."""
    inc_id = state["incident_id"]
    old_plan = PlanVersionModel(**state["plan_v1"])

    supervisor = ReplanningSupervisorMVP()
    invalidated_v1, plan_v2, route_c_calc = await supervisor.replan(old_plan, inc_id)

    plan_inval_evt = _create_audit_event(
        incident_id=inc_id,
        event_type="plan.invalidated",
        actor="REPLANNING_SUPERVISOR",
        summary="Plan v1 invalidated: Active route ROUTE-B became blocked.",
        payload={"plan_id": invalidated_v1.plan_id, "reason": invalidated_v1.invalidation_reason},
    )

    plan_v2_evt = _create_audit_event(
        incident_id=inc_id,
        event_type="plan.replanned",
        actor="REPLANNING_SUPERVISOR",
        summary="Plan v2 synthesized: Selected ROUTE-C North Ring Overpass (ETA 16 min).",
        payload={"plan_id": plan_v2.plan_id, "selected_route": "ROUTE-C"},
    )

    events = list(state.get("audit_events", []))
    events.extend([plan_inval_evt, plan_v2_evt])

    return {
        "status": "REPLANNING",
        "plan_v1": invalidated_v1.model_dump(mode="json"),
        "plan_v2": plan_v2.model_dump(mode="json"),
        "current_plan_version": 2,
        "routing": route_c_calc.model_dump(mode="json"),
        "replan_reason": "Selected route ROUTE-B became blocked.",
        "audit_events": events,
    }


async def new_route_execution_node(state: NexusMVPState) -> dict[str, Any]:
    """Finalizes response under Plan v2 (Route C) and sets status to RESOLVED."""
    inc_id = state["incident_id"]
    events = list(state.get("audit_events", []))

    exec_v2_evt = _create_audit_event(
        incident_id=inc_id,
        event_type="action.executed",
        actor="EXECUTION_AGENT",
        summary="Inbound ambulance diverted to ROUTE-C; hospital trauma bay notified.",
        payload={
            "diverted_corridor": "ROUTE-C",
            "preserved_ambulance": state["selected_ambulance"],
        },
    )
    events.append(exec_v2_evt)

    return {
        "status": "RESOLVED",
        "audit_events": events,
    }


# -----------------------------------------------------------------------------
# Graph Assembly
# -----------------------------------------------------------------------------
def build_nexus_mvp_graph() -> Any:
    """Builds and compiles the complete LangGraph StateGraph with MemorySaver checkpointer."""
    workflow = StateGraph(NexusMVPState)

    # 1. Add all discrete nodes
    workflow.add_node("incident", incident_node)
    workflow.add_node("verification", verification_node)
    workflow.add_node("impact", impact_node)
    workflow.add_node("resources", resources_node)
    workflow.add_node("routing", routing_node)
    workflow.add_node("planning", planning_node)
    workflow.add_node("policy_gate", policy_gate_node)
    workflow.add_node("execution", execution_node)
    workflow.add_node("monitoring", monitoring_node)
    workflow.add_node("environment_change", environment_change_node)
    workflow.add_node("replanning", replanning_node)
    workflow.add_node("new_route", new_route_execution_node)

    # 2. Add sequential transitions
    workflow.add_edge(START, "incident")
    workflow.add_edge("incident", "verification")
    workflow.add_edge("verification", "impact")
    workflow.add_edge("impact", "resources")
    workflow.add_edge("resources", "routing")
    workflow.add_edge("routing", "planning")
    workflow.add_edge("planning", "policy_gate")

    # Conditional branching from policy_gate
    def route_after_gate(state: NexusMVPState) -> str:
        if state.get("status") == "REJECTED":
            return END
        return "execution"

    workflow.add_conditional_edges("policy_gate", route_after_gate, ["execution", END])
    workflow.add_edge("execution", "monitoring")
    workflow.add_edge("monitoring", "environment_change")
    workflow.add_edge("environment_change", "replanning")
    workflow.add_edge("replanning", "new_route")
    workflow.add_edge("new_route", END)

    checkpointer = MemorySaver()
    app = workflow.compile(checkpointer=checkpointer)
    return app


# Singleton compiled graph instance
nexus_mvp_graph = build_nexus_mvp_graph()
