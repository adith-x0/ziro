from datetime import datetime
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class GeoPoint(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    address_reference: str | None = None


class EvidenceItem(BaseModel):
    evidence_id: str
    source_type: Literal[
        "citizen_photo",
        "iot_stream_gauge",
        "traffic_cctv",
        "historical_vector_match",
    ]
    timestamp: datetime
    data_payload: dict[str, Any]
    visual_water_depth_inches: float | None = None
    sensor_reading_inches: float | None = None
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    corroborated: bool


class ImpactAssessment(BaseModel):
    critical_facility_name: str
    facility_type: Literal[
        "trauma_hospital",
        "power_station",
        "water_treatment",
        "transit_hub",
    ]
    ingress_cut_off: bool
    estimated_isolation_risk_minutes: int
    severely_affected_corridors: list[str]
    population_density_index: float
    summary_narrative: str


class RouteOption(BaseModel):
    route_id: str
    origin: str
    destination: str
    waypoints: list[list[float]]
    total_distance_km: float
    estimated_transit_time_min: float
    max_water_clearance_supported_inches: float
    is_compromised: bool = False
    compromised_reason: str | None = None


class ActionItem(BaseModel):
    action_id: str
    sequence_order: int
    action_type: Literal[
        "UPDATE_VARIABLE_MESSAGE_SIGN",
        "DISPATCH_HIGH_WATER_EMS",
        "RESERVE_AMBULANCE",
        "DEPLOY_ROAD_BLOCK_BARRIER",
        "NOTIFY_HOSPITAL_TRAUMA_BAY",
        "ACTIVATE_SECONDARY_DETOUR",
        "ISSUE_PUBLIC_TRAVEL_ADVISORY",
        "CLOSE_PRIMARY_ARTERY",
        "REROUTE_TRAUMA_PATIENTS",
    ]
    target_entity: str
    risk_tier: Literal["TIER_1_AUTO", "TIER_2_LOW", "TIER_3_MEDIUM", "TIER_4_HIGH"]
    description: str
    execution_payload: dict[str, Any]
    approval_required: bool
    approval_status: Literal["PENDING", "APPROVED", "REJECTED", "AUTO_APPROVED"]
    executed: bool = False
    execution_result: dict[str, Any] | None = None


class AuditRecord(BaseModel):
    record_id: str
    timestamp: datetime
    node_name: str
    actor: Literal[
        "INGESTION_AGENT",
        "VERIFICATION_AGENT",
        "IMPACT_AGENT",
        "PLANNER_AGENT",
        "RISK_GATE",
        "HUMAN_COMMANDER",
        "EXECUTION_AGENT",
        "MONITOR_AGENT",
    ]
    action_summary: str
    state_delta: dict[str, Any]
    signature_hash: str


class NexusIncidentState(TypedDict, total=False):
    """LangGraph Central Incident State Schema."""

    incident_id: str
    incident_title: str
    current_status: Literal[
        "INGESTED",
        "VERIFIED",
        "IMPACT_EVALUATED",
        "ROUTED",
        "PLAN_SYNTHESIZED",
        "AWAITING_APPROVAL",
        "EXECUTING",
        "MONITORING",
        "REPLANNING",
        "RESOLVED",
    ]
    raw_user_report: str
    image_attachment_url: str | None
    epicenter_coords: GeoPoint

    extracted_features: dict[str, Any]
    evidence_trail: list[EvidenceItem]
    verification_confidence: float
    impact_assessment: ImpactAssessment | None

    available_fleet: list[dict[str, Any]]
    active_routes: list[RouteOption]
    selected_primary_route_id: str | None

    action_plan: list[ActionItem]
    requires_human_approval: bool
    commander_decision: dict[str, Any] | None

    monitored_sensor_ids: list[str]
    telemetry_surge_detected: bool
    replan_iteration_count: int

    audit_log: list[AuditRecord]
    system_errors: list[str]
