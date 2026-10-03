"""NEXUS Synthetic Environment & Simulation Services.

Provides deterministic simulation of:
- Hydrological water sensors
- Precipitation radar
- Multi-source citizen incident reports
- Regional ambulance fleet inventory & reservation with idempotency
- Synthetic road network graph using NetworkX and Shapely geometries
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

import networkx as nx
from pydantic import BaseModel, Field
from shapely.geometry import LineString


# -----------------------------------------------------------------------------
# Evidence & Sensory Tools
# -----------------------------------------------------------------------------
class WaterSensorReading(BaseModel):
    sensor_id: str = "WS-CITY-01"
    station_name: str = "City Hospital Canal Bridge Gauge"
    flood_level: Literal["NORMAL", "MODERATE", "HIGH"] = "HIGH"
    water_level_inches: float = 35.0
    flood_stage_threshold_inches: float = 24.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WeatherRadarReading(BaseModel):
    radar_id: str = "RADAR-METRO-DOPPLER"
    heavy_rainfall: bool = True
    precipitation_rate_in_per_hr: float = 3.2
    storm_cell_moving_towards: str = "City Hospital Medical Corridor"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CitizenReportItem(BaseModel):
    report_id: str
    source_user: str
    report_text: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SimulatedEvidenceService:
    """Simulated evidence service providing authentic, non-hallucinated readings."""

    @staticmethod
    def query_water_sensor(
        latitude: float = 8.5241, longitude: float = 76.9366
    ) -> WaterSensorReading:
        return WaterSensorReading(
            sensor_id="WS-CITY-01",
            station_name="City Hospital Canal Bridge Gauge",
            flood_level="HIGH",
            water_level_inches=35.0,
            flood_stage_threshold_inches=24.0,
            timestamp=datetime.now(UTC),
        )

    @staticmethod
    def query_radar(latitude: float = 8.5241, longitude: float = 76.9366) -> WeatherRadarReading:
        return WeatherRadarReading(
            radar_id="RADAR-METRO-DOPPLER",
            heavy_rainfall=True,
            precipitation_rate_in_per_hr=3.2,
            storm_cell_moving_towards="City Hospital Medical Corridor",
            timestamp=datetime.now(UTC),
        )

    @staticmethod
    def query_incident_reports(
        latitude: float = 8.5241, longitude: float = 76.9366
    ) -> list[CitizenReportItem]:
        now = datetime.now(UTC)
        return [
            CitizenReportItem(
                report_id="rep-cit-01",
                source_user="civic_watcher_441",
                report_text="Heavy flooding is blocking the emergency access road near City Hospital. Ambulances may not be able to reach emergency entrance.",
                timestamp=now,
            ),
            CitizenReportItem(
                report_id="rep-cit-02",
                source_user="nurse_commute_88",
                report_text="Water rapidly rising outside City Hospital emergency bay; passenger sedans are hydro-locked.",
                timestamp=now,
            ),
        ]


# -----------------------------------------------------------------------------
# Fleet Inventory & Reservation Service
# -----------------------------------------------------------------------------
class AmbulanceUnit(BaseModel):
    unit_id: str
    unit_name: str
    status: Literal["AVAILABLE", "BUSY", "RESERVED", "MAINTENANCE"]
    location: tuple[float, float]
    distance_km: float
    current_workload: int
    axle_clearance_inches: float = 34.0


class ReservationReceipt(BaseModel):
    reservation_id: str
    unit_id: str
    incident_id: str
    status: Literal["RESERVED", "FAILED"]
    tracking_token: str
    timestamp: datetime
    idempotent_replay: bool = False


class SimulatedFleetService:
    """Manages synthetic municipal ambulance fleet with strict deterministic selection and idempotency."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Reset fleet to known scenario baseline."""
        self._fleet: dict[str, AmbulanceUnit] = {
            "AMB-01": AmbulanceUnit(
                unit_id="AMB-01",
                unit_name="Medic-Rescue 01 (Ford F-550 High-Water 4x4)",
                status="AVAILABLE",
                location=(8.5190, 76.9310),
                distance_km=2.1,
                current_workload=1,
                axle_clearance_inches=34.0,
            ),
            "AMB-02": AmbulanceUnit(
                unit_id="AMB-02",
                unit_name="Standard Medic Unit 02",
                status="BUSY",
                location=(8.5150, 76.9280),
                distance_km=1.5,
                current_workload=5,
                axle_clearance_inches=12.0,
            ),
            "AMB-03": AmbulanceUnit(
                unit_id="AMB-03",
                unit_name="Medic-Rescue 03 (Freightliner M2 Severe-Duty)",
                status="AVAILABLE",
                location=(8.5350, 76.9480),
                distance_km=4.8,
                current_workload=2,
                axle_clearance_inches=40.0,
            ),
        }
        # Idempotency storage: (unit_id, incident_id) -> ReservationReceipt
        self._reservations: dict[tuple[str, str], ReservationReceipt] = {}

    def get_all_ambulances(self) -> list[AmbulanceUnit]:
        return list(self._fleet.values())

    def get_available_ambulances(self) -> list[AmbulanceUnit]:
        return [unit for unit in self._fleet.values() if unit.status == "AVAILABLE"]

    def select_best_ambulance(self) -> AmbulanceUnit:
        """Select best available ambulance using deterministic rules:
        1. Available
        2. Shortest distance
        3. Lowest current workload
        """
        available = self.get_available_ambulances()
        if not available:
            raise RuntimeError("No available ambulances found in fleet inventory.")

        # Sort key: (distance_km, current_workload)
        sorted_units = sorted(available, key=lambda u: (u.distance_km, u.current_workload))
        return sorted_units[0]

    def reserve_ambulance(self, unit_id: str, incident_id: str) -> ReservationReceipt:
        """Reserve ambulance with idempotency guarantee."""
        key = (unit_id, incident_id)
        if key in self._reservations:
            existing = self._reservations[key]
            # Return existing receipt with idempotency flag
            return ReservationReceipt(
                reservation_id=existing.reservation_id,
                unit_id=existing.unit_id,
                incident_id=existing.incident_id,
                status=existing.status,
                tracking_token=existing.tracking_token,
                timestamp=existing.timestamp,
                idempotent_replay=True,
            )

        if unit_id not in self._fleet:
            raise KeyError(f"Ambulance {unit_id} not found in depot registry.")

        unit = self._fleet[unit_id]
        if unit.status not in ["AVAILABLE", "RESERVED"]:
            raise RuntimeError(f"Cannot reserve ambulance {unit_id}: status is {unit.status}")

        unit.status = "RESERVED"
        receipt = ReservationReceipt(
            reservation_id=f"res-{uuid.uuid4().hex[:8]}",
            unit_id=unit_id,
            incident_id=incident_id,
            status="RESERVED",
            tracking_token=f"trk-{uuid.uuid4().hex[:12]}",
            timestamp=datetime.now(UTC),
            idempotent_replay=False,
        )
        self._reservations[key] = receipt
        return receipt


# -----------------------------------------------------------------------------
# Synthetic Road Network Graph (NetworkX + Shapely)
# -----------------------------------------------------------------------------
class RoadSegment(BaseModel):
    route_id: str
    name: str
    status: Literal["SAFE", "BLOCKED"]
    distance_km: float
    estimated_time_minutes: float
    geometry_wkt: str
    max_flood_depth_inches: float = 0.0


class RoutingResult(BaseModel):
    selected_route: str
    alternatives: list[str]
    blocked_roads: list[str]
    estimated_time_minutes: float
    total_distance_km: float
    waypoints: list[list[float]]


class SyntheticRoadNetwork:
    """Topological road network surrounding City Hospital implemented with NetworkX and Shapely."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Construct synthetic graph."""
        self.graph = nx.Graph()

        # Coordinates
        self.node_depot = (8.5180, 76.9300)
        self.node_incident = (8.5241, 76.9366)
        self.node_hospital = (8.5280, 76.9420)
        self.node_industrial = (8.5210, 76.9450)
        self.node_ring_overpass = (8.5320, 76.9320)

        # Add nodes
        self.graph.add_node("DEPOT", pos=self.node_depot, type="fleet_depot")
        self.graph.add_node("INCIDENT", pos=self.node_incident, type="flood_epicenter")
        self.graph.add_node("CITY-HOSPITAL", pos=self.node_hospital, type="trauma_hospital")
        self.graph.add_node("WAYPOINT_B_IND", pos=self.node_industrial, type="detour_waypoint")
        self.graph.add_node(
            "WAYPOINT_C_OVERPASS", pos=self.node_ring_overpass, type="overpass_waypoint"
        )

        # Road segments definitions
        geom_a = LineString([self.node_depot, self.node_incident, self.node_hospital])
        geom_b = LineString([self.node_depot, self.node_industrial, self.node_hospital])
        geom_c = LineString([self.node_depot, self.node_ring_overpass, self.node_hospital])

        self.routes: dict[str, RoadSegment] = {
            "ROUTE-A": RoadSegment(
                route_id="ROUTE-A",
                name="Metropolitan Parkway (Direct Hospital Artery)",
                status="BLOCKED",  # Initially blocked by flood
                distance_km=2.5,
                estimated_time_minutes=6.0,
                geometry_wkt=geom_a.wkt,
                max_flood_depth_inches=35.0,
            ),
            "ROUTE-B": RoadSegment(
                route_id="ROUTE-B",
                name="Industrial Way Detour (Canal Bypass)",
                status="SAFE",  # Initially safe
                distance_km=4.2,
                estimated_time_minutes=11.0,
                geometry_wkt=geom_b.wkt,
                max_flood_depth_inches=8.5,
            ),
            "ROUTE-C": RoadSegment(
                route_id="ROUTE-C",
                name="North Ring Elevated Overpass",
                status="SAFE",  # Safe alternative
                distance_km=6.0,
                estimated_time_minutes=16.0,
                geometry_wkt=geom_c.wkt,
                max_flood_depth_inches=0.0,
            ),
        }

        # Build graph edges
        self._sync_graph_edges()

    def _sync_graph_edges(self) -> None:
        """Sync graph edges based on road status."""
        self.graph.clear_edges()
        # ROUTE-A edge
        weight_a = (
            float("inf")
            if self.routes["ROUTE-A"].status == "BLOCKED"
            else self.routes["ROUTE-A"].distance_km
        )
        self.graph.add_edge(
            "DEPOT", "CITY-HOSPITAL", key="ROUTE-A", weight=weight_a, route_id="ROUTE-A"
        )

        # ROUTE-B edge via industrial waypoint
        weight_b = (
            float("inf")
            if self.routes["ROUTE-B"].status == "BLOCKED"
            else self.routes["ROUTE-B"].distance_km
        )
        self.graph.add_edge(
            "DEPOT", "WAYPOINT_B_IND", key="ROUTE-B-1", weight=weight_b / 2.0, route_id="ROUTE-B"
        )
        self.graph.add_edge(
            "WAYPOINT_B_IND",
            "CITY-HOSPITAL",
            key="ROUTE-B-2",
            weight=weight_b / 2.0,
            route_id="ROUTE-B",
        )

        # ROUTE-C edge via overpass waypoint
        weight_c = (
            float("inf")
            if self.routes["ROUTE-C"].status == "BLOCKED"
            else self.routes["ROUTE-C"].distance_km
        )
        self.graph.add_edge(
            "DEPOT",
            "WAYPOINT_C_OVERPASS",
            key="ROUTE-C-1",
            weight=weight_c / 2.0,
            route_id="ROUTE-C",
        )
        self.graph.add_edge(
            "WAYPOINT_C_OVERPASS",
            "CITY-HOSPITAL",
            key="ROUTE-C-2",
            weight=weight_c / 2.0,
            route_id="ROUTE-C",
        )

    def block_route(self, route_id: str) -> RoadSegment:
        """Inject environmental change: block a specific route."""
        if route_id not in self.routes:
            raise KeyError(f"Route {route_id} does not exist in network topology.")
        self.routes[route_id].status = "BLOCKED"
        self._sync_graph_edges()
        return self.routes[route_id]

    def get_route(self, route_id: str) -> RoadSegment:
        if route_id not in self.routes:
            raise KeyError(f"Route {route_id} does not exist in network topology.")
        return self.routes[route_id]

    def unblock_route(self, route_id: str) -> RoadSegment:
        if route_id not in self.routes:
            raise KeyError(f"Route {route_id} does not exist in network topology.")
        self.routes[route_id].status = "SAFE"
        self._sync_graph_edges()
        return self.routes[route_id]

    def calculate_safe_route(self) -> RoutingResult:
        """Deterministic routing algorithm selecting the shortest safe route."""
        blocked = [rid for rid, r in self.routes.items() if r.status == "BLOCKED"]
        safe = [rid for rid, r in self.routes.items() if r.status == "SAFE"]

        if not safe:
            raise RuntimeError("All synthetic routes are blocked. No passable corridor found.")

        # Candidate selection based on lowest travel time / distance among safe routes
        # ROUTE-B (11 min) is preferred over ROUTE-C (16 min) if both safe
        sorted_safe = sorted(
            safe,
            key=lambda rid: (self.routes[rid].estimated_time_minutes, self.routes[rid].distance_km),
        )
        selected = sorted_safe[0]
        alternatives = [r for r in sorted_safe if r != selected]

        # Generate geometry coordinates using Shapely
        line = LineString(
            [
                (p[0], p[1])
                for p in [
                    self.node_depot,
                    self.node_industrial if selected == "ROUTE-B" else self.node_ring_overpass,
                    self.node_hospital,
                ]
            ]
        )
        waypoints = [[float(coord[0]), float(coord[1])] for coord in line.coords]

        return RoutingResult(
            selected_route=selected,
            alternatives=alternatives,
            blocked_roads=blocked,
            estimated_time_minutes=self.routes[selected].estimated_time_minutes,
            total_distance_km=self.routes[selected].distance_km,
            waypoints=waypoints,
        )


# Global singleton instances for local execution / API state
simulated_evidence_service = SimulatedEvidenceService()
simulated_fleet_service = SimulatedFleetService()
synthetic_road_network = SyntheticRoadNetwork()
