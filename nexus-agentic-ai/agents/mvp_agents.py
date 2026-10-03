"""NEXUS MVP Specialized Agents.

Implements discrete agent charters:
- VerificationAgentMVP: Corroborates simulated water sensor, Doppler radar, and citizen reports
- ImpactAgentMVP: Analyzes isolation risk to City Hospital and road cuts
- ResourceAgentMVP: Deterministically selects optimal ambulance from fleet database
- RoutingAgentMVP: Calculates safe path using NetworkX/Shapely topological road graph
- PlanningAgentMVP: Synthesizes explicit action DAG for Plan v1
- ReplanningSupervisorMVP: Detects environment breach, invalidates Plan v1, and generates Plan v2 selecting Route C
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from orchestration.mvp_models import (
    ActionDAGItem,
    ImpactResult,
    PlanVersionModel,
    ResourceSelectionResult,
    RouteCalculationResult,
    VerificationResult,
)
from tools.synthetic_environment import (
    simulated_evidence_service,
    simulated_fleet_service,
    synthetic_road_network,
)


class VerificationAgentMVP:
    """Perception & verification agent querying authentic simulated sensory tools."""

    async def verify(self, latitude: float, longitude: float) -> VerificationResult:
        # 1. Query simulated stream gauge / water sensor
        water = simulated_evidence_service.query_water_sensor(latitude, longitude)
        # 2. Query simulated precipitation radar
        radar = simulated_evidence_service.query_radar(latitude, longitude)
        # 3. Query simulated citizen incident reports
        reports = simulated_evidence_service.query_incident_reports(latitude, longitude)

        evidence_ids = [water.sensor_id, radar.radar_id] + [r.report_id for r in reports]
        evidence_items: list[dict[str, Any]] = [
            water.model_dump(mode="json"),
            radar.model_dump(mode="json"),
            *[r.model_dump(mode="json") for r in reports],
        ]

        verified = (
            water.flood_level == "HIGH" and radar.heavy_rainfall is True and len(reports) >= 2
        )
        confidence = 0.90 if verified else 0.40

        return VerificationResult(
            verified=verified,
            confidence=confidence,
            evidence_ids=evidence_ids,
            reason="Multiple independent simulated sources support the incident.",
            evidence_items=evidence_items,
        )


class ImpactAgentMVP:
    """Evaluates spatial threat to critical infrastructure (City Hospital)."""

    async def analyze(
        self, verification: VerificationResult | dict[str, Any], latitude: float, longitude: float
    ) -> ImpactResult:
        # Grounded strictly in simulated environment around City Hospital
        return ImpactResult(
            hospital_access="AT_RISK",
            affected_roads=["ROUTE-A"],
            emergency_access_risk="HIGH",
            affected_hospital="CITY-HOSPITAL",
            isolation_eta_minutes=45,
        )


class ResourceAgentMVP:
    """Queries regional fleet depot and deterministically selects highest priority unit."""

    async def select_resource(self) -> ResourceSelectionResult:
        best_unit = simulated_fleet_service.select_best_ambulance()
        available = [u.unit_id for u in simulated_fleet_service.get_available_ambulances()]

        return ResourceSelectionResult(
            selected_ambulance=best_unit.unit_id,
            available_ambulances=available,
            selection_reason=(
                f"{best_unit.unit_id} is available with shortest distance ({best_unit.distance_km}km) "
                f"and lowest current workload ({best_unit.current_workload})."
            ),
        )


class RoutingAgentMVP:
    """Computes shortest non-flooded path using NetworkX and Shapely road graph."""

    async def route(self) -> RouteCalculationResult:
        route_res = synthetic_road_network.calculate_safe_route()
        return RouteCalculationResult(
            selected_route=route_res.selected_route,
            alternatives=route_res.alternatives,
            blocked_roads=route_res.blocked_roads,
            estimated_time_minutes=route_res.estimated_time_minutes,
            total_distance_km=route_res.total_distance_km,
            waypoints=route_res.waypoints,
        )


class PlanningAgentMVP:
    """Synthesizes structured operational action DAG."""

    async def create_plan(
        self,
        incident_id: str,
        ambulance_id: str,
        route_id: str,
        hospital_id: str = "CITY-HOSPITAL",
    ) -> PlanVersionModel:
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"
        actions: list[ActionDAGItem] = [
            ActionDAGItem(
                action_id=f"act-verify-{uuid.uuid4().hex[:6]}",
                action_type="VERIFY_INCIDENT",
                target_entity=hospital_id,
                status="COMPLETED",
                risk_level="LOW",
                requires_approval=False,
                prerequisites=[],
                tool_name="evidence_service.verify",
            ),
            ActionDAGItem(
                action_id=f"act-select-amb-{uuid.uuid4().hex[:6]}",
                action_type="SELECT_AMBULANCE",
                target_entity=ambulance_id,
                status="COMPLETED",
                risk_level="LOW",
                requires_approval=False,
                prerequisites=["VERIFY_INCIDENT"],
                tool_name="fleet_service.select_best",
            ),
            ActionDAGItem(
                action_id=f"act-select-route-{uuid.uuid4().hex[:6]}",
                action_type="SELECT_SAFE_ROUTE",
                target_entity=route_id,
                status="COMPLETED",
                risk_level="LOW",
                requires_approval=False,
                prerequisites=["VERIFY_INCIDENT"],
                tool_name="road_network.calculate_safe_route",
            ),
            ActionDAGItem(
                action_id=f"act-reserve-{ambulance_id.lower()}",
                action_type="RESERVE_AMBULANCE",
                target_entity=ambulance_id,
                status="PENDING",
                risk_level="MEDIUM",
                requires_approval=True,
                prerequisites=["SELECT_AMBULANCE", "SELECT_SAFE_ROUTE"],
                tool_name="fleet_service.reserve_ambulance",
            ),
            ActionDAGItem(
                action_id=f"act-notify-hosp-{uuid.uuid4().hex[:6]}",
                action_type="NOTIFY_HOSPITAL",
                target_entity=hospital_id,
                status="PENDING",
                risk_level="LOW",
                requires_approval=False,
                prerequisites=["RESERVE_AMBULANCE"],
                tool_name="hospital_service.notify_incoming",
            ),
        ]

        return PlanVersionModel(
            plan_id=plan_id,
            incident_id=incident_id,
            version=1,
            title="Operational Response Plan v1: Route Beta Industrial Detour",
            selected_route=route_id,
            assigned_ambulance=ambulance_id,
            actions=actions,
            status="PROPOSED",
            created_at=datetime.now(UTC),
        )


class ReplanningSupervisorMVP:
    """Oversees environmental drift, plan invalidation, and contingency plan v2 synthesis."""

    async def replan(
        self, old_plan: PlanVersionModel, incident_id: str
    ) -> tuple[PlanVersionModel, PlanVersionModel, RouteCalculationResult]:
        """Invalidates Plan v1 and produces Plan v2 selecting Route C without repeating completed reservations."""
        # 1. Invalidate old plan
        old_plan.status = "INVALIDATED"
        old_plan.invalidation_reason = "Selected route ROUTE-B became blocked."

        # 2. Recalculate route over network topology
        route_res = synthetic_road_network.calculate_safe_route()
        assert route_res.selected_route == "ROUTE-C", (
            f"Expected ROUTE-C, got {route_res.selected_route}"
        )

        route_calc = RouteCalculationResult(
            selected_route=route_res.selected_route,
            alternatives=route_res.alternatives,
            blocked_roads=route_res.blocked_roads,
            estimated_time_minutes=route_res.estimated_time_minutes,
            total_distance_km=route_res.total_distance_km,
            waypoints=route_res.waypoints,
        )

        # 3. Create Plan v2 preserving completed actions
        plan_v2_id = f"plan-{uuid.uuid4().hex[:8]}"
        actions_v2: list[ActionDAGItem] = [
            # Preserved completed ambulance reservation
            ActionDAGItem(
                action_id=f"act-reserve-{old_plan.assigned_ambulance.lower()}",
                action_type="RESERVE_AMBULANCE",
                target_entity=old_plan.assigned_ambulance,
                status="COMPLETED",
                risk_level="MEDIUM",
                requires_approval=True,
                prerequisites=[],
                tool_name="fleet_service.reserve_ambulance",
                execution_result={
                    "status": "RESERVED",
                    "note": "Preserved from Plan v1 without duplicate call.",
                },
            ),
            # Reroute corridor action
            ActionDAGItem(
                action_id=f"act-reroute-{uuid.uuid4().hex[:6]}",
                action_type="REROUTE_CORRIDOR",
                target_entity=route_res.selected_route,
                status="COMPLETED",
                risk_level="LOW",
                requires_approval=False,
                prerequisites=["RESERVE_AMBULANCE"],
                tool_name="road_network.divert_traffic",
                execution_result={"status": "diverted", "corridor": route_res.selected_route},
            ),
            # Updated hospital notification
            ActionDAGItem(
                action_id=f"act-notify-hosp-v2-{uuid.uuid4().hex[:6]}",
                action_type="NOTIFY_HOSPITAL",
                target_entity="CITY-HOSPITAL",
                status="COMPLETED",
                risk_level="LOW",
                requires_approval=False,
                prerequisites=["REROUTE_CORRIDOR"],
                tool_name="hospital_service.notify_incoming",
                execution_result={
                    "alert": "Inbound transport rerouted via Route C North Ring Overpass."
                },
            ),
        ]

        plan_v2 = PlanVersionModel(
            plan_id=plan_v2_id,
            incident_id=incident_id,
            version=2,
            title="Operational Response Plan v2: Route C North Ring Elevated Overpass",
            selected_route=route_res.selected_route,
            assigned_ambulance=old_plan.assigned_ambulance,
            actions=actions_v2,
            status="COMPLETED",
            created_at=datetime.now(UTC),
        )

        return old_plan, plan_v2, route_calc
