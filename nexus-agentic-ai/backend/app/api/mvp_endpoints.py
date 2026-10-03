"""NEXUS MVP Operational REST Endpoints.

Implements all 11 core vertical-slice API endpoints for incident lifecycle,
HITL approvals, timeline tracking, and environmental simulation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from orchestration.mvp_models import (
    IncidentCreateRequest,
    IncidentCreateResponse,
)
from orchestration.mvp_runtime import mvp_runtime
from pydantic import BaseModel, Field

router = APIRouter(tags=["NEXUS MVP Operations"])


class DecisionRequest(BaseModel):
    reviewer_id: str = Field(
        default="Elena Vance (EOC Watch Commander)",
        description="Name or callsign of authorizing commander",
    )


class SimulationRouteBlockRequest(BaseModel):
    route_id: str = Field(..., description="ID of route to block (e.g. ROUTE-B)")


# -----------------------------------------------------------------------------
# Incident Endpoints
# -----------------------------------------------------------------------------
@router.post(
    "/incidents",
    response_model=IncidentCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new emergency incident report",
)
async def create_incident(
    payload: IncidentCreateRequest,
    auto_start: bool = Query(
        default=False,
        description="Automatically trigger verification and planning pipeline upon creation",
    ),
) -> IncidentCreateResponse:
    """Step 1: Perception & Ingestion.

    Receives citizen/sensor incident report and assigns unique incident tracking ID.
    """
    res = mvp_runtime.create_incident(
        description=payload.description,
        latitude=payload.location.latitude,
        longitude=payload.location.longitude,
    )

    if auto_start:
        await mvp_runtime.start_incident(res.incident_id)

    return res


@router.post(
    "/incidents/{incident_id}/start",
    summary="Trigger the automated perception, verification, and planning pipeline",
)
async def start_incident_processing(incident_id: str) -> dict[str, Any]:
    """Runs the NEXUS LangGraph pipeline from START until the HITL Policy Gate interrupt."""
    try:
        updated_state = await mvp_runtime.start_incident(incident_id)
        return {
            "incident_id": incident_id,
            "status": updated_state.get("status"),
            "pending_approval": updated_state.get("pending_approval_id") is not None,
            "verification": updated_state.get("verification"),
            "impact": updated_state.get("impact"),
            "selected_ambulance": updated_state.get("selected_ambulance"),
            "routing": updated_state.get("routing"),
            "plan_v1": updated_state.get("plan_v1"),
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}") from e


@router.get(
    "/incidents/{incident_id}",
    summary="Get full operational state of an incident",
)
async def get_incident(incident_id: str) -> dict[str, Any]:
    """Retrieves full incident state snapshot."""
    try:
        return mvp_runtime.get_incident_state(incident_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/incidents/{incident_id}/status",
    summary="Get high-level status badge and lifecycle flags",
)
async def get_incident_status(incident_id: str) -> dict[str, Any]:
    """Returns quick status summary for status cards and polling UI."""
    try:
        state = mvp_runtime.get_incident_state(incident_id)
        return {
            "incident_id": incident_id,
            "status": state.get("status", "UNKNOWN"),
            "current_plan_version": state.get("current_plan_version", 1),
            "requires_approval": state.get("status") == "AWAITING_APPROVAL",
            "environment_changed": state.get("environment_changed", False),
            "updated_at": state.get("updated_at"),
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/incidents/{incident_id}/timeline",
    summary="Get ordered chronological lifecycle timeline",
)
async def get_incident_timeline(incident_id: str) -> list[dict[str, Any]]:
    """Returns sequence of operational events with actors, timestamps, and summaries."""
    try:
        return mvp_runtime.get_incident_timeline(incident_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/incidents/{incident_id}/plan",
    summary="Get active and versioned operational plans",
)
async def get_incident_plan(incident_id: str) -> dict[str, Any]:
    """Returns current active plan and version history (Plan v1 & Plan v2)."""
    try:
        return mvp_runtime.get_incident_plan(incident_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/incidents/{incident_id}/audit",
    summary="Get immutable audit logs for this incident",
)
async def get_incident_audit(incident_id: str) -> list[dict[str, Any]]:
    """Returns audit log records ensuring full accountability."""
    try:
        return mvp_runtime.get_incident_audit(incident_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# -----------------------------------------------------------------------------
# Human-In-The-Loop Approval Endpoints
# -----------------------------------------------------------------------------
@router.get(
    "/approvals/pending",
    summary="List all pending authorization requests",
)
async def list_pending_approvals() -> list[dict[str, Any]]:
    """Returns all actions halted at the deterministic safety gate awaiting human authorization."""
    return mvp_runtime.get_pending_approvals()


@router.post(
    "/approvals/{approval_id}/approve",
    summary="Human Commander APPROVES the pending action",
)
async def approve_action(
    approval_id: str,
    payload: DecisionRequest | None = None,
) -> dict[str, Any]:
    """Resumes graph execution from interrupt with APPROVED decision token.

    Completes execution, monitoring, environmental injection, and replanning.
    """
    reviewer = payload.reviewer_id if payload else "Elena Vance (EOC Watch Commander)"
    try:
        res = await mvp_runtime.resume_with_decision(
            approval_id=approval_id,
            decision="APPROVED",
            reviewer_id=reviewer,
        )
        return {
            "status": "APPROVED_AND_RESUMED",
            "approval_id": approval_id,
            "incident_status": res.get("status"),
            "current_plan_version": res.get("current_plan_version"),
            "message": "Human approval verified. Autonomous execution and monitoring completed.",
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution resume error: {str(e)}") from e


@router.post(
    "/approvals/{approval_id}/reject",
    summary="Human Commander REJECTS the pending action",
)
async def reject_action(
    approval_id: str,
    payload: DecisionRequest | None = None,
) -> dict[str, Any]:
    """Resumes graph execution from interrupt with REJECTED decision token."""
    reviewer = payload.reviewer_id if payload else "Elena Vance (EOC Watch Commander)"
    try:
        res = await mvp_runtime.resume_with_decision(
            approval_id=approval_id,
            decision="REJECTED",
            reviewer_id=reviewer,
        )
        return {
            "status": "REJECTED_AND_HALTED",
            "approval_id": approval_id,
            "incident_status": res.get("status"),
            "message": "Action rejected by human commander. Execution halted safely.",
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution halt error: {str(e)}") from e


# -----------------------------------------------------------------------------
# Simulation Control Endpoints
# -----------------------------------------------------------------------------
@router.post(
    "/simulation/block-route/{route_id}",
    summary="Inject simulated environmental failure (e.g. ROUTE-B flooded)",
)
async def block_route_simulation(route_id: str) -> dict[str, Any]:
    """Modifies synthetic road network topology to trigger dynamic replanning."""
    res = mvp_runtime.block_route(route_id)
    return res


@router.post(
    "/simulation/reset",
    summary="Reset synthetic environment, fleet depot, and state graph",
)
async def reset_simulation() -> dict[str, Any]:
    """Resets entire simulation back to clean baseline."""
    return mvp_runtime.reset_simulation()
