"""NEXUS Tool Schemas & Input/Output Data Contracts.

Defines Pydantic schemas for the 11 safe operational tools:
1. Weather (`WeatherInput`, `WeatherOutput`)
2. Incident reports (`IncidentReportsInput`, `IncidentReportsOutput`)
3. Image analysis (`ImageAnalysisInput`, `ImageAnalysisOutput`)
4. Geolocation (`GeolocationInput`, `GeolocationOutput`)
5. Routing (`RoutingInput`, `RoutingOutput`)
6. Resource search (`ResourceSearchInput`, `ResourceSearchOutput`)
7. Hospital status (`HospitalStatusInput`, `HospitalStatusOutput`)
8. Notifications (`NotificationInput`, `NotificationOutput`)
9. Ambulance reservation (`AmbulanceReservationInput`, `AmbulanceReservationOutput`)
10. Incident status update (`IncidentStatusUpdateInput`, `IncidentStatusUpdateOutput`)
11. Audit logging (`AuditLogInput`, `AuditLogOutput`)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SIMULATION_ENVIRONMENT_TAG = "simulation/mock environment"


class ToolBaseModel(BaseModel):
    """Base schema enforcing extra-field rejection and serializability."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
    )


# -----------------------------------------------------------------------------
# 1. Weather Schemas
# -----------------------------------------------------------------------------
class WeatherInput(ToolBaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees")


class WeatherOutput(ToolBaseModel):
    temperature_c: float
    rainfall_rate_mm_hr: float
    flood_level: Literal["LOW", "MEDIUM", "HIGH"]
    precipitation_type: str
    wind_speed_kmh: float
    advisory: str
    is_simulation: bool = Field(default=True, description="Strictly true for all mock tools")
    environment: str = Field(default=SIMULATION_ENVIRONMENT_TAG)


# -----------------------------------------------------------------------------
# 2. Incident Reports Schemas
# -----------------------------------------------------------------------------
class IncidentReportsInput(ToolBaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    radius_km: float = Field(default=5.0, ge=0.1, le=50.0)


class IncidentReportItem(ToolBaseModel):
    report_id: str
    reported_at: datetime
    observer_type: str
    description: str
    water_depth_estimate_inches: float
    corridor: str


class IncidentReportsOutput(ToolBaseModel):
    reports: list[IncidentReportItem]
    total_reports: int
    summary: str
    is_simulation: bool = Field(default=True)
    environment: str = Field(default=SIMULATION_ENVIRONMENT_TAG)


# -----------------------------------------------------------------------------
# 3. Image Analysis Schemas
# -----------------------------------------------------------------------------
class ImageAnalysisInput(ToolBaseModel):
    image_url: str | None = Field(default=None)
    image_bytes_base64: str | None = Field(default=None)
    prompt: str = Field(
        default="Analyze water depth, passable vehicles, and submerged infrastructure."
    )


class ImageAnalysisOutput(ToolBaseModel):
    water_depth_estimate_inches: float
    submerged_landmarks: list[str]
    vehicles_impassable: list[str]
    emergency_risk: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    is_simulation: bool = Field(default=True)
    environment: str = Field(default=SIMULATION_ENVIRONMENT_TAG)


# -----------------------------------------------------------------------------
# 4. Geolocation Schemas
# -----------------------------------------------------------------------------
class GeolocationInput(ToolBaseModel):
    query_address_or_landmark: str = Field(..., min_length=2)


class GeolocationOutput(ToolBaseModel):
    resolved_name: str
    latitude: float
    longitude: float
    zone_type: str
    is_simulation: bool = Field(default=True)
    environment: str = Field(default=SIMULATION_ENVIRONMENT_TAG)


# -----------------------------------------------------------------------------
# 5. Routing Schemas
# -----------------------------------------------------------------------------
class RoutingInput(ToolBaseModel):
    origin: str = Field(default="DEPOT")
    destination: str = Field(default="CITY-HOSPITAL")
    avoid_routes: list[str] = Field(default_factory=list)
    vehicle_clearance_inches: float = Field(default=12.0, ge=0.0)


class RoutingOutput(ToolBaseModel):
    selected_route_id: str
    route_name: str
    distance_km: float
    estimated_travel_time_minutes: float
    waypoints: list[list[float]]
    blocked_routes_detected: list[str]
    is_passable: bool
    is_simulation: bool = Field(default=True)
    environment: str = Field(default=SIMULATION_ENVIRONMENT_TAG)


# -----------------------------------------------------------------------------
# 6. Resource Search Schemas
# -----------------------------------------------------------------------------
class ResourceSearchInput(ToolBaseModel):
    resource_type: str = Field(default="AMBULANCE")
    required_clearance_inches: float = Field(default=0.0, ge=0.0)
    max_distance_km: float = Field(default=25.0, ge=0.0)


class ResourceSummaryItem(ToolBaseModel):
    unit_id: str
    unit_name: str
    status: str
    distance_km: float
    current_workload: int
    axle_clearance_inches: float


class ResourceSearchOutput(ToolBaseModel):
    available_resources: list[ResourceSummaryItem]
    selected_recommendation: str | None
    total_available: int
    is_simulation: bool = Field(default=True)
    environment: str = Field(default=SIMULATION_ENVIRONMENT_TAG)


# -----------------------------------------------------------------------------
# 7. Hospital Status Schemas
# -----------------------------------------------------------------------------
class HospitalStatusInput(ToolBaseModel):
    hospital_id: str = Field(default="CITY-HOSPITAL")


class HospitalStatusOutput(ToolBaseModel):
    hospital_id: str
    hospital_name: str
    emergency_room_status: str
    bed_capacity_total: int
    bed_capacity_available: int
    trauma_center_level: int
    power_grid_status: str
    flood_barrier_active: bool
    ingress_status: str
    is_simulation: bool = Field(default=True)
    environment: str = Field(default=SIMULATION_ENVIRONMENT_TAG)


# -----------------------------------------------------------------------------
# 8. Notifications Schemas
# -----------------------------------------------------------------------------
class NotificationInput(ToolBaseModel):
    channel: Literal["SMS", "EMAIL", "PAGER", "HOSPITAL_ALERT_FEED"]
    recipient: str = Field(..., min_length=2)
    title: str = Field(..., min_length=2)
    message: str = Field(..., min_length=2)
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = Field(default="MEDIUM")


class NotificationOutput(ToolBaseModel):
    delivery_id: str
    status: Literal["SENT_SIMULATED", "QUEUED_SIMULATED"]
    channel: str
    recipient: str
    timestamp: datetime
    is_simulation: bool = Field(default=True)
    environment: str = Field(default=SIMULATION_ENVIRONMENT_TAG)


# -----------------------------------------------------------------------------
# 9. Ambulance Reservation Schemas (Requires Approval Token)
# -----------------------------------------------------------------------------
class AmbulanceReservationInput(ToolBaseModel):
    unit_id: str = Field(..., min_length=2)
    incident_id: str = Field(..., min_length=2)
    destination: str = Field(default="CITY-HOSPITAL")
    detour_route_id: str | None = Field(default=None)
    approval_token: str | None = Field(
        default=None,
        description="Mandatory authorization token issued by human commander (cannot be bypassed).",
    )


class AmbulanceReservationOutput(ToolBaseModel):
    reservation_id: str
    unit_id: str
    incident_id: str
    status: Literal["RESERVED", "DISPATCHED", "FAILED"]
    tracking_token: str
    timestamp: datetime
    idempotent_replay: bool
    is_simulation: bool = Field(default=True)
    environment: str = Field(default=SIMULATION_ENVIRONMENT_TAG)


# -----------------------------------------------------------------------------
# 10. Incident Status Update Schemas
# -----------------------------------------------------------------------------
class IncidentStatusUpdateInput(ToolBaseModel):
    incident_id: str = Field(..., min_length=2)
    new_status: str = Field(..., min_length=2)
    commentary: str = Field(default="")


class IncidentStatusUpdateOutput(ToolBaseModel):
    incident_id: str
    previous_status: str
    current_status: str
    updated_at: datetime
    is_simulation: bool = Field(default=True)
    environment: str = Field(default=SIMULATION_ENVIRONMENT_TAG)


# -----------------------------------------------------------------------------
# 11. Audit Logging Schemas
# -----------------------------------------------------------------------------
class AuditLogInput(ToolBaseModel):
    incident_id: str = Field(..., min_length=2)
    event_type: str = Field(..., min_length=2)
    actor: str = Field(..., min_length=2)
    summary: str = Field(..., min_length=2)
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditLogOutput(ToolBaseModel):
    event_id: str
    incident_id: str
    event_type: str
    recorded_at: datetime
    cryptographic_digest: str
    is_simulation: bool = Field(default=True)
    environment: str = Field(default=SIMULATION_ENVIRONMENT_TAG)
