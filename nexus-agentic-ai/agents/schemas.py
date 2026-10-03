"""NEXUS Agent Schemas & Structured Pydantic LLM Output Contracts.

Defines strongly typed, validated schemas for all agent outputs and state fields:
- incident
- evidence
- verification
- impact
- resources
- routes
- plan
- risk_assessment
- approval
- actions
- monitoring
- memory
- errors
- metadata
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# -----------------------------------------------------------------------------
# Base Configured Schema
# -----------------------------------------------------------------------------
class NexusBaseSchema(BaseModel):
    """Base schema enforcing strict validation and serializability."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
    )


# -----------------------------------------------------------------------------
# 1. Incident Schemas
# -----------------------------------------------------------------------------
class IncidentLocation(NexusBaseSchema):
    """Geographic point with strict latitude/longitude bounds."""

    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees")
    address_reference: str | None = Field(
        default=None, description="Nearby landmark or street reference"
    )


class IncidentData(NexusBaseSchema):
    """Structured perception data of a reported real-world emergency."""

    incident_id: str = Field(default_factory=lambda: f"inc-{uuid.uuid4().hex[:8]}")
    description: str = Field(..., min_length=5, description="Factual description of the incident")
    category: Literal[
        "FLOODING",
        "INFRASTRUCTURE_FAILURE",
        "SUPPLY_CHAIN_DISRUPTION",
        "HAZMAT_SPILL",
        "MASS_CASUALTY",
        "OTHER",
    ] = Field(default="FLOODING")
    severity: Literal["MINOR", "MODERATE", "SEVERE", "CRITICAL"] = Field(default="MODERATE")
    location: IncidentLocation
    reported_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reporter_type: Literal["CITIZEN", "IOT_SENSOR", "DISPATCH_FEED", "FIRST_RESPONDER"] = Field(
        default="CITIZEN"
    )
    affected_radius_meters: float = Field(default=500.0, ge=0.0)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


# -----------------------------------------------------------------------------
# 2. Evidence Schemas
# -----------------------------------------------------------------------------
class EvidenceItem(NexusBaseSchema):
    """Single item of empirical evidence collected from sensors, feeds, or citizens."""

    evidence_id: str = Field(default_factory=lambda: f"ev-{uuid.uuid4().hex[:8]}")
    source_id: str = Field(..., description="Sensor hardware identifier or report ID")
    source_type: Literal[
        "WATER_SENSOR",
        "RADAR",
        "CITIZEN_REPORT",
        "TRAFFIC_CAMERA",
        "SATELLITE",
        "HISTORICAL_RECORD",
    ]
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Source reliability score between 0 and 1"
    )
    data: dict[str, Any] = Field(default_factory=dict, description="Raw telemetry payload")
    verified: bool = Field(default=True)

    @property
    def data_payload(self) -> dict[str, Any]:
        """Backward compatibility alias for legacy data_payload."""
        return self.data

    @property
    def confidence_score(self) -> float:
        """Backward compatibility alias for legacy confidence_score."""
        return self.confidence

    @property
    def timestamp(self) -> datetime:
        """Backward compatibility alias for legacy timestamp."""
        return self.observed_at

    @property
    def corroborated(self) -> bool:
        """Backward compatibility alias for legacy corroborated."""
        return self.verified


# -----------------------------------------------------------------------------
# 3. Verification Schemas
# -----------------------------------------------------------------------------
class VerificationResult(NexusBaseSchema):
    """Output of the Verification Agent corroborating the incident."""

    verified: bool = Field(..., description="Whether incident is corroborated by evidence")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall verification confidence")
    evidence_ids: list[str] = Field(
        default_factory=list, description="IDs of corroborating evidence"
    )
    primary_factors: list[str] = Field(
        default_factory=list, description="Key empirical observations supporting verification"
    )
    reasoning: str = Field(
        ..., min_length=5, description="Structured explanation of verification decision"
    )
    verified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# -----------------------------------------------------------------------------
# 4. Impact Schemas
# -----------------------------------------------------------------------------
class ImpactAssessment(NexusBaseSchema):
    """Output of the Impact Agent assessing infrastructure and facility risk."""

    affected_hospital: str = Field(..., description="Primary health facility at risk")
    hospital_access: Literal["ACCESSIBLE", "AT_RISK", "SEVERED", "COMPROMISED"]
    affected_roads: list[str] = Field(
        default_factory=list, description="List of road or corridor IDs affected"
    )
    emergency_access_risk: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    estimated_delay_minutes: float = Field(default=0.0, ge=0.0)
    secondary_hazards: list[str] = Field(default_factory=list)
    narrative: str = Field(default="", description="Structured impact summary")
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# -----------------------------------------------------------------------------
# 5. Resource Schemas
# -----------------------------------------------------------------------------
class ResourceItem(NexusBaseSchema):
    """Specification of an operational emergency vehicle or asset."""

    resource_id: str = Field(..., description="Unit identifier e.g. AMB-01")
    resource_type: Literal[
        "AMBULANCE",
        "HIGH_WATER_RESCUE",
        "EVACUATION_BUS",
        "BARRIER_TRUCK",
        "RESCUE_BOAT",
    ] = Field(default="AMBULANCE")
    callsign: str
    status: Literal["AVAILABLE", "BUSY", "RESERVED", "OUT_OF_SERVICE", "DISPATCHED"]
    distance_km: float = Field(..., ge=0.0)
    current_workload: int = Field(default=0, ge=0)
    axle_clearance_inches: float = Field(default=12.0, ge=0.0)
    reserved_for_incident: str | None = None
    reservation_token: str | None = None


class ResourceState(NexusBaseSchema):
    """Resource inventory state and deterministic selection outcome."""

    available_units: list[str] = Field(default_factory=list)
    selected_unit: str | None = None
    selection_criteria: list[str] = Field(default_factory=list)
    allocated_resources: list[ResourceItem] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# 6. Route Schemas
# -----------------------------------------------------------------------------
class RouteOption(NexusBaseSchema):
    """Topological road network route calculated by routing engine."""

    route_id: str = Field(..., description="Unique route segment identifier e.g. ROUTE-B")
    name: str
    status: Literal["SAFE", "AT_RISK", "BLOCKED"]
    distance_km: float = Field(..., ge=0.0)
    estimated_time_minutes: float = Field(..., ge=0.0)
    flood_depth_inches: float = Field(default=0.0, ge=0.0)
    waypoints: list[list[float]] = Field(default_factory=list)
    is_preferred: bool = Field(default=False)


class RoutingState(NexusBaseSchema):
    """Active topological navigation and alternative corridors."""

    selected_route_id: str | None = None
    active_routes: list[RouteOption] = Field(default_factory=list)
    blocked_routes: list[str] = Field(default_factory=list)
    alternative_routes: list[str] = Field(default_factory=list)
    total_distance_km: float = Field(default=0.0, ge=0.0)
    estimated_eta_minutes: float = Field(default=0.0, ge=0.0)


# -----------------------------------------------------------------------------
# 7. Action & Plan Schemas
# -----------------------------------------------------------------------------
class PlanActionItem(NexusBaseSchema):
    """Single discrete step in an operational action DAG."""

    action_id: str = Field(default_factory=lambda: f"act-{uuid.uuid4().hex[:8]}")
    action_type: Literal[
        "VERIFY_INCIDENT",
        "SELECT_AMBULANCE",
        "SELECT_SAFE_ROUTE",
        "RESERVE_AMBULANCE",
        "NOTIFY_HOSPITAL",
        "REROUTE_AMBULANCE",
        "UPDATE_VARIABLE_MESSAGE_SIGN",
        "ISSUE_PUBLIC_ALERT",
        "UPDATE_SIMULATED_ROAD_STATUS",
        "RESERVE_SIMULATED_RESOURCE",
        "UPDATE_SIMULATED_INCIDENT_STATUS",
        "SEND_SIMULATED_NOTIFICATION",
        "REQUEST_ADDITIONAL_VERIFICATION",
        "CALCULATE_ROUTE",
        "MONITOR_INCIDENT",
        "SEARCH_SIMULATED_RESOURCES",
        "CHECK_HOSPITAL_STATUS",
        "LOG_AUDIT_EVENT",
    ]
    target_entity: str
    sequence: int = Field(..., ge=1)
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL", "HUMAN_ONLY"]
    requires_approval: bool = False
    status: Literal[
        "PENDING",
        "AWAITING_APPROVAL",
        "APPROVED",
        "REJECTED",
        "EXECUTING",
        "COMPLETED",
        "FAILED",
        "INVALIDATED",
        "CANCELLED",
    ] = Field(default="PENDING")
    execution_receipt: dict[str, Any] | None = None


class PlanData(NexusBaseSchema):
    """Versioned operational plan containing sequenced actions."""

    plan_id: str = Field(default_factory=lambda: f"plan-{uuid.uuid4().hex[:8]}")
    version: int = Field(default=1, ge=1)
    plan_version: int = Field(default=1, ge=1)
    supersedes_plan_id: str | None = None
    reason_for_revision: str | None = None
    objective: str | None = None
    status: Literal[
        "DRAFT",
        "PROPOSED",
        "AWAITING_APPROVAL",
        "APPROVED",
        "REJECTED",
        "EXECUTING",
        "COMPLETED",
        "INVALIDATED",
        "VALID",
        "INVALID",
        "BLOCKED",
        "NEEDS_REVISION",
    ] = Field(default="PROPOSED")
    actions: list[PlanActionItem] = Field(default_factory=list)
    invalidation_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# -----------------------------------------------------------------------------
# 8. Risk Assessment Schemas
# -----------------------------------------------------------------------------
class RiskAssessmentData(NexusBaseSchema):
    """Output of the Safety Policy Gate evaluating plan risk."""

    overall_risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    human_approval_required: bool
    high_risk_actions: list[str] = Field(default_factory=list)
    policy_rules_triggered: list[str] = Field(default_factory=list)
    justification: str = Field(..., min_length=5)
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# -----------------------------------------------------------------------------
# 9. Approval Schemas
# -----------------------------------------------------------------------------
class ApprovalRecordData(NexusBaseSchema):
    """Human-in-the-loop authorization record."""

    approval_id: str = Field(default_factory=lambda: f"appr-{uuid.uuid4().hex[:8]}")
    action_id: str
    action_type: str
    target_entity: str
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    status: Literal["PENDING", "APPROVED", "REJECTED"] = Field(default="PENDING")
    reason: str
    reviewer_id: str | None = None
    decision_token: str | None = None
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None
    incident_id: str | None = None
    plan_id: str | None = None
    plan_version: int | None = None
    action_parameters_hash: str | None = None
    required_role: str = "COMMANDER"
    expires_at: datetime | None = None


# -----------------------------------------------------------------------------
# 10. Actions / Execution Receipts
# -----------------------------------------------------------------------------
class ActionExecutionReceipt(NexusBaseSchema):
    """Cryptographic or auditable receipt from simulated operational actuator."""

    action_id: str
    action_type: str
    target_entity: str
    status: Literal["COMPLETED", "FAILED", "IDEMPOTENT_REPLAY"]
    output_payload: dict[str, Any] = Field(default_factory=dict)
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    execution_duration_ms: float = Field(default=0.0, ge=0.0)


# -----------------------------------------------------------------------------
# 11. Monitoring Schemas
# -----------------------------------------------------------------------------
class MonitoringData(NexusBaseSchema):
    """Real-time corridor surveillance and anomaly detection."""

    monitored_corridor: str
    corridor_status: Literal["SAFE", "DEGRADED", "BLOCKED"]
    environment_changed: bool = Field(default=False)
    change_description: str | None = None
    water_level_inches: float = Field(default=0.0, ge=0.0)
    anomalies_detected: list[str] = Field(default_factory=list)
    replan_triggered: bool = Field(default=False)
    last_checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# -----------------------------------------------------------------------------
# 12. Memory Schemas
# -----------------------------------------------------------------------------
class MemoryItem(NexusBaseSchema):
    """Historical incident playbook or operational episodic memory."""

    record_id: str = Field(default_factory=lambda: f"mem-{uuid.uuid4().hex[:8]}")
    record_type: Literal["EPISODIC", "SEMANTIC_PLAYBOOK", "OPERATIONAL_HEURISTIC"]
    title: str
    content: str
    relevance_score: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryState(NexusBaseSchema):
    """Retrieved memory context and operational playbooks."""

    retrieved_playbooks: list[MemoryItem] = Field(default_factory=list)
    applied_heuristics: list[str] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# 13. Error Schemas
# -----------------------------------------------------------------------------
class AgentErrorItem(NexusBaseSchema):
    """Structured error captured during agent or tool execution."""

    error_id: str = Field(default_factory=lambda: f"err-{uuid.uuid4().hex[:8]}")
    node_name: str
    error_type: str
    message: str
    recoverable: bool = Field(default=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# -----------------------------------------------------------------------------
# 14. Metadata Schemas
# -----------------------------------------------------------------------------
class ExecutionMetadata(NexusBaseSchema):
    """Operational run provenance and LangGraph execution metadata."""

    run_id: str = Field(default_factory=lambda: f"run-{uuid.uuid4().hex[:8]}")
    thread_id: str = Field(default_factory=lambda: f"th-{uuid.uuid4().hex[:8]}")
    current_step: str = Field(default="START")
    plan_version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agent_hops: int = Field(default=0, ge=0)
    llm_model_used: str = Field(default="gemini-2.5-flash")
    extra: dict[str, Any] = Field(default_factory=dict)
