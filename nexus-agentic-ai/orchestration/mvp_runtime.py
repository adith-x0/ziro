"""NEXUS MVP Runtime Orchestration Manager.

Provides thread state management, execution control, interrupt handling,
and query interfaces for the MVP LangGraph state machine.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command

from orchestration.mvp_graph import nexus_mvp_graph
from orchestration.mvp_models import (
    AuditEvent,
    IncidentCreateResponse,
)
from tools.synthetic_environment import (
    simulated_fleet_service,
    synthetic_road_network,
)

logger = logging.getLogger("nexus.mvp_runtime")


class MvpRuntimeManager:
    """Singleton runtime manager for NEXUS MVP execution lifecycle."""

    def __init__(self) -> None:
        self.incidents: dict[str, dict[str, Any]] = {}
        self.pending_approvals: dict[str, dict[str, Any]] = {}
        self.approval_to_incident: dict[str, str] = {}

    def reset_simulation(self) -> dict[str, str]:
        """Resets synthetic road network, fleet registry, and runtime memories."""
        synthetic_road_network.reset()
        simulated_fleet_service.reset()
        self.incidents.clear()
        self.pending_approvals.clear()
        self.approval_to_incident.clear()
        logger.info("NEXUS MVP simulation and runtime successfully reset.")
        return {"status": "RESET_SUCCESSFUL", "message": "Fleet, roads, and graph cache reset."}

    def create_incident(
        self,
        description: str,
        latitude: float = 8.5241,
        longitude: float = 76.9366,
    ) -> IncidentCreateResponse:
        """Step 1: Receives raw incident and assigns tracking ID."""
        incident_id = f"inc-{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)

        initial_event = AuditEvent(
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            incident_id=incident_id,
            event_type="incident.created",
            actor="INGESTION_SYSTEM",
            summary="Emergency report received and registered in NEXUS dispatch buffer.",
            payload={
                "description": description,
                "location": {"latitude": latitude, "longitude": longitude},
            },
            timestamp=now,
        )

        record: dict[str, Any] = {
            "incident_id": incident_id,
            "description": description,
            "latitude": latitude,
            "longitude": longitude,
            "status": "RECEIVED",
            "current_plan_version": 1,
            "environment_changed": False,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "audit_events": [initial_event.model_dump(mode="json")],
            "execution_receipts": [],
            "verification": None,
            "impact": None,
            "routing": None,
            "plan_v1": None,
            "plan_v2": None,
            "approval_record": None,
            "monitoring": None,
        }

        self.incidents[incident_id] = record
        logger.info(f"Created incident {incident_id} at ({latitude}, {longitude})")
        return IncidentCreateResponse(incident_id=incident_id, status="RECEIVED")

    async def start_incident(self, incident_id: str) -> dict[str, Any]:
        """Runs the graph from START until interrupt (at policy gate) or completion."""
        if incident_id not in self.incidents:
            raise KeyError(f"Incident {incident_id} not found.")

        incident_data = self.incidents[incident_id]
        config = {"configurable": {"thread_id": incident_id}}

        initial_state = {
            "incident_id": incident_id,
            "description": incident_data["description"],
            "latitude": incident_data["latitude"],
            "longitude": incident_data["longitude"],
        }

        logger.info(f"Triggering LangGraph execution pipeline for {incident_id}...")
        graph_output = await nexus_mvp_graph.ainvoke(initial_state, config=config)

        # Inspect current state checkpoint
        state_snapshot = nexus_mvp_graph.get_state(config)
        return self._sync_state_from_graph(incident_id, graph_output, state_snapshot)

    async def resume_with_decision(
        self,
        approval_id: str,
        decision: str,  # "APPROVED" or "REJECTED"
        reviewer_id: str = "Elena Vance (EOC Watch Commander)",
    ) -> dict[str, Any]:
        """Resumes LangGraph execution from interrupt with commander's decision."""
        if approval_id not in self.approval_to_incident:
            raise KeyError(f"Approval request {approval_id} not found or already decided.")

        incident_id = self.approval_to_incident[approval_id]
        config = {"configurable": {"thread_id": incident_id}}

        decision_token = f"tok-{uuid.uuid4().hex[:12]}"
        resume_payload = {
            "decision": decision,
            "reviewer_id": reviewer_id,
            "decision_token": decision_token,
        }

        logger.info(
            f"Resuming LangGraph {incident_id} with decision {decision} by {reviewer_id}..."
        )
        graph_output = await nexus_mvp_graph.ainvoke(
            Command(resume=resume_payload),
            config=config,
        )

        state_snapshot = nexus_mvp_graph.get_state(config)
        # Remove from pending approvals
        if approval_id in self.pending_approvals:
            del self.pending_approvals[approval_id]
        del self.approval_to_incident[approval_id]

        return self._sync_state_from_graph(incident_id, graph_output, state_snapshot)

    def _sync_state_from_graph(
        self,
        incident_id: str,
        graph_output: dict[str, Any],
        state_snapshot: Any,
    ) -> dict[str, Any]:
        """Synchronizes graph values and pending interrupts into runtime state."""
        rec = self.incidents.get(incident_id, {})
        values = state_snapshot.values if hasattr(state_snapshot, "values") else graph_output

        rec.update(values)
        rec["updated_at"] = datetime.now(UTC).isoformat()

        # Check if paused at interrupt (Human in the loop)
        if hasattr(state_snapshot, "tasks") and state_snapshot.tasks:
            for task in state_snapshot.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    for intr in task.interrupts:
                        intr_val = intr.value
                        if isinstance(intr_val, dict) and "approval_id" in intr_val:
                            appr_id = intr_val["approval_id"]
                            self.pending_approvals[appr_id] = intr_val
                            self.approval_to_incident[appr_id] = incident_id
                            rec["status"] = "AWAITING_APPROVAL"
                            rec["pending_approval_id"] = appr_id
                            if rec.get("plan_v1"):
                                rec["plan_v1"]["status"] = "AWAITING_APPROVAL"
                                for act in rec["plan_v1"].get("actions", []):
                                    if act.get("action_type") == intr_val.get("action"):
                                        act["status"] = "AWAITING_APPROVAL"

        self.incidents[incident_id] = rec
        return rec

    def get_incident_state(self, incident_id: str) -> dict[str, Any]:
        """Returns the complete operational state for an incident."""
        if incident_id not in self.incidents:
            raise KeyError(f"Incident {incident_id} not found.")
        return self.incidents[incident_id]

    def get_pending_approvals(self) -> list[dict[str, Any]]:
        """Returns all pending human authorization requests."""
        return list(self.pending_approvals.values())

    def get_incident_timeline(self, incident_id: str) -> list[dict[str, Any]]:
        """Returns formatted chronological timeline entries for an incident."""
        state = self.get_incident_state(incident_id)
        events = state.get("audit_events", [])
        timeline: list[dict[str, Any]] = []

        for idx, evt in enumerate(events):
            timeline.append(
                {
                    "id": evt.get("event_id", f"tline-{idx}"),
                    "order": idx + 1,
                    "event_type": evt.get("event_type", "event.unknown"),
                    "actor": evt.get("actor", "SYSTEM"),
                    "summary": evt.get("summary", ""),
                    "timestamp": evt.get("timestamp", datetime.now(UTC).isoformat()),
                    "payload": evt.get("payload", {}),
                }
            )
        return timeline

    def get_incident_plan(self, incident_id: str) -> dict[str, Any]:
        """Returns active plan, version status, and replanning history."""
        state = self.get_incident_state(incident_id)
        version = state.get("current_plan_version", 1)
        plan_v1 = state.get("plan_v1")
        plan_v2 = state.get("plan_v2")

        active_plan = plan_v2 if (version == 2 and plan_v2) else plan_v1

        return {
            "incident_id": incident_id,
            "current_plan_version": version,
            "environment_changed": state.get("environment_changed", False),
            "replan_reason": state.get("replan_reason"),
            "active_plan": active_plan,
            "plan_v1": plan_v1,
            "plan_v2": plan_v2,
        }

    def get_incident_audit(self, incident_id: str) -> list[dict[str, Any]]:
        """Returns raw audit events."""
        state = self.get_incident_state(incident_id)
        events: list[dict[str, Any]] = list(state.get("audit_events", []))
        return events

    def block_route(self, route_id: str) -> dict[str, Any]:
        """Forces route blockage in synthetic road network for scenario testing."""
        synthetic_road_network.block_route(route_id)
        return {
            "status": "ROUTE_BLOCKED",
            "route_id": route_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }


# Global runtime singleton
mvp_runtime = MvpRuntimeManager()
