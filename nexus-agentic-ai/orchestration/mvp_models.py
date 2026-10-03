"""NEXUS MVP Typed State & Data Schemas.

Strict Pydantic models for the complete vertical slice:
- Incidents
- Verification evidence
- Impact analysis
- Resource selection
- Deterministic routing
- Action DAGs and Plan versions
- Policy approvals
- Tamper-evident audit events
"""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class IncidentLocation(BaseModel):
    latitude: float = Field(default=8.5241, ge=-90.0, le=90.0)
    longitude: float = Field(default=76.9366, ge=-180.0, le=180.0)


class IncidentCreateRequest(BaseModel):
    description: str = Field(
        ...,
        json_schema_extra={
            "example": "Heavy flooding is blocking the emergency access road near City Hospital. Ambulances may not be able to reach the emergency entrance."
        },
    )
    location: IncidentLocation = Field(default_factory=IncidentLocation)


class IncidentCreateResponse(BaseModel):
    incident_id: str
    status: str = "RECEIVED"


class VerificationResult(BaseModel):
    verified: bool = True
    confidence: float = 0.90
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = "Multiple independent simulated sources support the incident."
    evidence_items: list[dict[str, Any]] = Field(default_factory=list)


class ImpactResult(BaseModel):
    hospital_access: Literal["SAFE", "AT_RISK", "BLOCKED"] = "AT_RISK"
    affected_roads: list[str] = Field(default_factory=lambda: ["ROUTE-A"])
    emergency_access_risk: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "HIGH"
    affected_hospital: str = "CITY-HOSPITAL"
    isolation_eta_minutes: int = 45


class ResourceSelectionResult(BaseModel):
    selected_ambulance: str = "AMB-01"
    available_ambulances: list[str] = Field(default_factory=lambda: ["AMB-01", "AMB-03"])
    selection_reason: str = (
        "AMB-01 is available with shortest distance (2.1km) and lowest current workload (1)."
    )


class RouteCalculationResult(BaseModel):
    selected_route: str = "ROUTE-B"
    alternatives: list[str] = Field(default_factory=lambda: ["ROUTE-C"])
    blocked_roads: list[str] = Field(default_factory=lambda: ["ROUTE-A"])
    estimated_time_minutes: float = 11.0
    total_distance_km: float = 4.2
    waypoints: list[list[float]] = Field(default_factory=list)


class ActionDAGItem(BaseModel):
    action_id: str
    action_type: Literal[
        "VERIFY_INCIDENT",
        "SELECT_AMBULANCE",
        "SELECT_SAFE_ROUTE",
        "RESERVE_AMBULANCE",
        "NOTIFY_HOSPITAL",
        "REROUTE_CORRIDOR",
    ]
    target_entity: str
    status: Literal["PENDING", "APPROVED", "REJECTED", "COMPLETED", "FAILED"] = "PENDING"
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"
    requires_approval: bool = False
    prerequisites: list[str] = Field(default_factory=list)
    tool_name: str
    execution_result: dict[str, Any] | None = None


class PlanVersionModel(BaseModel):
    plan_id: str
    incident_id: str
    version: int
    title: str
    selected_route: str
    assigned_ambulance: str
    actions: list[ActionDAGItem] = Field(default_factory=list)
    status: Literal[
        "PROPOSED", "AWAITING_APPROVAL", "APPROVED", "EXECUTING", "INVALIDATED", "COMPLETED"
    ] = "PROPOSED"
    invalidation_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalRecord(BaseModel):
    approval_id: str
    incident_id: str
    action_id: str
    action_type: str
    target_entity: str
    risk_level: str = "MEDIUM"
    status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    reason: str = "Resource allocation changes operational state and commits emergency vehicles."
    supporting_evidence_count: int = 3
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None
    reviewer_id: str | None = None
    decision_token: str | None = None


class AuditEvent(BaseModel):
    event_id: str
    incident_id: str
    event_type: Literal[
        "incident.created",
        "verification.started",
        "evidence.collected",
        "incident.verified",
        "impact.completed",
        "resource.selected",
        "route.selected",
        "plan.created",
        "approval.requested",
        "approval.approved",
        "approval.rejected",
        "action.executed",
        "environment.changed",
        "plan.invalidated",
        "plan.replanned",
    ]
    actor: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
