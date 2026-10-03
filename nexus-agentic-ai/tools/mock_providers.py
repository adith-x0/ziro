"""NEXUS Deterministic Mock Tool Providers for Simulation Environment.

Every mock provider:
- Produces deterministic, reproducible operational data
- Connects directly to the synthetic environment services
- Explicitly flags all output as `simulation/mock environment`
- Enforces safety boundaries (no real emergency actions)
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from tools.interfaces import (
    AmbulanceReservationProvider,
    AuditLogProvider,
    GeolocationProvider,
    HospitalStatusProvider,
    ImageAnalysisProvider,
    IncidentReportsProvider,
    IncidentStatusProvider,
    NotificationProvider,
    ResourceSearchProvider,
    RoutingProvider,
    WeatherProvider,
)
from tools.schemas import (
    SIMULATION_ENVIRONMENT_TAG,
    AmbulanceReservationInput,
    AmbulanceReservationOutput,
    AuditLogInput,
    AuditLogOutput,
    GeolocationOutput,
    HospitalStatusOutput,
    ImageAnalysisInput,
    ImageAnalysisOutput,
    IncidentReportItem,
    IncidentReportsOutput,
    IncidentStatusUpdateInput,
    IncidentStatusUpdateOutput,
    NotificationInput,
    NotificationOutput,
    ResourceSearchInput,
    ResourceSearchOutput,
    ResourceSummaryItem,
    RoutingInput,
    RoutingOutput,
    WeatherOutput,
)
from tools.synthetic_environment import (
    simulated_fleet_service,
    synthetic_road_network,
)


class MockWeatherProvider(WeatherProvider):
    """Deterministic hydrological weather provider simulating heavy rain and flash flooding."""

    async def get_weather(self, lat: float, lon: float) -> WeatherOutput:
        return WeatherOutput(
            temperature_c=24.5,
            rainfall_rate_mm_hr=58.2,
            flood_level="HIGH",
            precipitation_type="HEAVY_TORRENTIAL_RAIN",
            wind_speed_kmh=42.0,
            advisory="Severe hydrological surge alert: low-lying corridors near City Hospital flooded.",
            is_simulation=True,
            environment=SIMULATION_ENVIRONMENT_TAG,
        )


class MockIncidentReportsProvider(IncidentReportsProvider):
    """Deterministic citizen and field sensor report aggregator."""

    async def get_reports(self, lat: float, lon: float, radius_km: float) -> IncidentReportsOutput:
        now = datetime.now(UTC)
        reports = [
            IncidentReportItem(
                report_id="rep-cit-01",
                reported_at=now,
                observer_type="CITIZEN_MOBILE",
                description="Water rising rapidly on Route A near Hospital gate. Sedans stalled.",
                water_depth_estimate_inches=18.0,
                corridor="ROUTE-A",
            ),
            IncidentReportItem(
                report_id="rep-cit-02",
                reported_at=now,
                observer_type="COMMERCIAL_DRIVER",
                description="Route A impassable at canal underpass; detour via Route B recommended.",
                water_depth_estimate_inches=22.0,
                corridor="ROUTE-A",
            ),
        ]
        return IncidentReportsOutput(
            reports=reports,
            total_reports=len(reports),
            summary="Multiple citizen reports confirm Route A submerged under 18-22 inches of water.",
            is_simulation=True,
            environment=SIMULATION_ENVIRONMENT_TAG,
        )


class MockImageAnalysisProvider(ImageAnalysisProvider):
    """Deterministic vision provider evaluating flood depth and vehicle clearance."""

    async def analyze_image(self, input_data: ImageAnalysisInput) -> ImageAnalysisOutput:
        return ImageAnalysisOutput(
            water_depth_estimate_inches=19.5,
            submerged_landmarks=["Hospital Access Ramp", "Curb line", "Route A Drain Gate"],
            vehicles_impassable=["Passenger Car / Sedan", "Compact SUV", "Standard Ambulance"],
            emergency_risk="HIGH",
            confidence=0.91,
            is_simulation=True,
            environment=SIMULATION_ENVIRONMENT_TAG,
        )


class MockGeolocationProvider(GeolocationProvider):
    """Deterministic spatial geocoding provider for City Hospital vicinity."""

    async def geocode(self, query: str) -> GeolocationOutput:
        q_upper = query.upper()
        if "HOSPITAL" in q_upper or "CITY" in q_upper:
            return GeolocationOutput(
                resolved_name="City Hospital Emergency Complex",
                latitude=8.5280,
                longitude=76.9420,
                zone_type="CRITICAL_CARE_HEALTHCARE_ZONE",
                is_simulation=True,
                environment=SIMULATION_ENVIRONMENT_TAG,
            )
        elif "DEPOT" in q_upper:
            return GeolocationOutput(
                resolved_name="Central Municipal EMS Fleet Depot",
                latitude=8.5180,
                longitude=76.9300,
                zone_type="MUNICIPAL_LOGISTICS_ZONE",
                is_simulation=True,
                environment=SIMULATION_ENVIRONMENT_TAG,
            )
        return GeolocationOutput(
            resolved_name=f"Synthesized Location for: {query}",
            latitude=8.5241,
            longitude=76.9366,
            zone_type="URBAN_FLOOD_ZONE",
            is_simulation=True,
            environment=SIMULATION_ENVIRONMENT_TAG,
        )


class MockRoutingProvider(RoutingProvider):
    """Deterministic topological routing provider using NetworkX road network."""

    async def calculate_route(self, input_data: RoutingInput) -> RoutingOutput:
        for blocked_id in input_data.avoid_routes:
            if blocked_id in synthetic_road_network.routes:
                synthetic_road_network.routes[blocked_id].status = "BLOCKED"

        result = synthetic_road_network.calculate_safe_route()
        route_seg = synthetic_road_network.get_route(result.selected_route)

        return RoutingOutput(
            selected_route_id=result.selected_route,
            route_name=route_seg.name,
            distance_km=result.total_distance_km,
            estimated_travel_time_minutes=result.estimated_time_minutes,
            waypoints=result.waypoints,
            blocked_routes_detected=result.blocked_roads,
            is_passable=True,
            is_simulation=True,
            environment=SIMULATION_ENVIRONMENT_TAG,
        )


class MockResourceSearchProvider(ResourceSearchProvider):
    """Deterministic emergency fleet search provider using SimulatedFleetService."""

    async def search_resources(self, input_data: ResourceSearchInput) -> ResourceSearchOutput:
        all_units = simulated_fleet_service.get_all_ambulances()
        available = [
            ResourceSummaryItem(
                unit_id=u.unit_id,
                unit_name=u.unit_name,
                status=u.status,
                distance_km=u.distance_km,
                current_workload=u.current_workload,
                axle_clearance_inches=u.axle_clearance_inches,
            )
            for u in all_units
            if u.status == "AVAILABLE"
            and u.axle_clearance_inches >= input_data.required_clearance_inches
            and u.distance_km <= input_data.max_distance_km
        ]

        best_unit = None
        if available:
            sorted_units = sorted(available, key=lambda x: (x.distance_km, x.current_workload))
            best_unit = sorted_units[0].unit_id

        return ResourceSearchOutput(
            available_resources=available,
            selected_recommendation=best_unit,
            total_available=len(available),
            is_simulation=True,
            environment=SIMULATION_ENVIRONMENT_TAG,
        )


class MockHospitalStatusProvider(HospitalStatusProvider):
    """Deterministic hospital facility telemetry provider."""

    async def get_hospital_status(self, hospital_id: str) -> HospitalStatusOutput:
        return HospitalStatusOutput(
            hospital_id=hospital_id,
            hospital_name="City Hospital Regional Medical Center",
            emergency_room_status="OPERATIONAL_CRITICAL_INGRESS",
            bed_capacity_total=450,
            bed_capacity_available=38,
            trauma_center_level=1,
            power_grid_status="NOMINAL_BACKUP_GENERATORS_READY",
            flood_barrier_active=True,
            ingress_status="PRIMARY_ROAD_CUT_OFF_USE_DETOUR_B",
            is_simulation=True,
            environment=SIMULATION_ENVIRONMENT_TAG,
        )


class MockNotificationProvider(NotificationProvider):
    """Deterministic operational alert dispatcher."""

    async def send_notification(self, input_data: NotificationInput) -> NotificationOutput:
        return NotificationOutput(
            delivery_id=f"notif-{uuid.uuid4().hex[:8]}",
            status="SENT_SIMULATED",
            channel=input_data.channel,
            recipient=input_data.recipient,
            timestamp=datetime.now(UTC),
            is_simulation=True,
            environment=SIMULATION_ENVIRONMENT_TAG,
        )


class MockAmbulanceReservationProvider(AmbulanceReservationProvider):
    """Deterministic fleet reservation provider with idempotency guarantees."""

    async def reserve_ambulance(
        self, input_data: AmbulanceReservationInput
    ) -> AmbulanceReservationOutput:
        receipt = simulated_fleet_service.reserve_ambulance(
            input_data.unit_id, input_data.incident_id
        )
        return AmbulanceReservationOutput(
            reservation_id=receipt.reservation_id,
            unit_id=receipt.unit_id,
            incident_id=receipt.incident_id,
            status="RESERVED",
            tracking_token=receipt.tracking_token,
            timestamp=receipt.timestamp,
            idempotent_replay=receipt.idempotent_replay,
            is_simulation=True,
            environment=SIMULATION_ENVIRONMENT_TAG,
        )


class MockIncidentStatusProvider(IncidentStatusProvider):
    """Deterministic incident lifecycle state transition recorder."""

    def __init__(self) -> None:
        self._statuses: dict[str, str] = {}

    async def update_status(
        self, input_data: IncidentStatusUpdateInput
    ) -> IncidentStatusUpdateOutput:
        prev = self._statuses.get(input_data.incident_id, "RECEIVED")
        self._statuses[input_data.incident_id] = input_data.new_status
        return IncidentStatusUpdateOutput(
            incident_id=input_data.incident_id,
            previous_status=prev,
            current_status=input_data.new_status,
            updated_at=datetime.now(UTC),
            is_simulation=True,
            environment=SIMULATION_ENVIRONMENT_TAG,
        )


class MockAuditLogProvider(AuditLogProvider):
    """Deterministic cryptographically-hashed audit logging provider."""

    async def log_event(self, input_data: AuditLogInput) -> AuditLogOutput:
        now = datetime.now(UTC)
        evt_id = f"evt-{uuid.uuid4().hex[:8]}"
        hash_src = f"{evt_id}:{input_data.incident_id}:{input_data.event_type}:{now.isoformat()}"
        digest = hashlib.sha256(hash_src.encode("utf-8")).hexdigest()[:16]

        return AuditLogOutput(
            event_id=evt_id,
            incident_id=input_data.incident_id,
            event_type=input_data.event_type,
            recorded_at=now,
            cryptographic_digest=digest,
            is_simulation=True,
            environment=SIMULATION_ENVIRONMENT_TAG,
        )
