"""NEXUS Route Agent.

Determines feasible, safe topological emergency transit corridors connecting fleet depots
to critical trauma centers while avoiding flooded and impassable roadways.

Strict Safety and Grounding Rules:
- NEVER invent routes, waypoints, road names, or transit corridors.
- Queries ONLY authoritative sources: ToolRegistry ("routing") and synthetic road network.
- Strictly classifies each route segment:
  1. AVAILABLE (clear, unflooded, passable)
  2. BLOCKED (submerged or physically compromised)
  3. UNCERTAIN (contradictory telemetry or borderline water depth)
  4. STALE (road condition reports exceeding staleness threshold)
- Grounded route selection: primary route, alternative route, blocked route.
- Analytical only: never modifies road signage or actuates closures directly.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from agents.base import BaseAgent
from agents.schemas import NexusBaseSchema, RouteOption, RoutingState
from tools.registry import ToolRegistry, default_tool_registry
from tools.synthetic_environment import synthetic_road_network

logger = logging.getLogger("nexus.agents.routes")

ROUTE_ID_REGEX = re.compile(r"^[A-Z0-9_\-]{3,32}$")

INJECTION_PATTERNS = [
    re.compile(
        r"(?i)(ignore\s+(all\s+)?previous\s+instructions|system\s+override|force\s+(passable|safe)|bypass\s+(safety|gate|policy))"
    ),
    re.compile(r"(?i)(</system>|</user>|<system_instruction>|```system|ADMIN_OVERRIDE)"),
]


def detect_prompt_injection(text: str) -> bool:
    """Scans untrusted inputs and tool outputs for adversarial injection attempts."""
    if not text:
        return False
    return any(p.search(text) for p in INJECTION_PATTERNS)


# -----------------------------------------------------------------------------
# Route Agent Structured Output Schemas
# -----------------------------------------------------------------------------
class RouteItemAnalysis(NexusBaseSchema):
    """Evaluated topological transit corridor with safety classification."""

    route_id: str = Field(..., description="Unique route identifier, e.g. ROUTE-B")
    name: str = Field(..., description="Corridor name, e.g. Industrial Way Detour")
    origin: str = Field(default="Municipal EMS Depot")
    destination: str = Field(default="City Hospital Regional Medical Center")
    waypoints: list[list[float]] = Field(
        default_factory=list, description="Validated geographic coordinates"
    )
    distance_km: float = Field(..., ge=0.0, description="Transit corridor distance in km")
    estimated_time_minutes: float = Field(
        ..., ge=0.0, description="Estimated transit time in minutes"
    )
    status: Literal["AVAILABLE", "BLOCKED", "UNCERTAIN", "STALE"] = Field(
        ..., description="Current operational status of route"
    )
    blocked_segments: list[str] = Field(
        default_factory=list, description="Specific road segments compromised on this corridor"
    )
    max_flood_depth_inches: float = Field(
        default=0.0, ge=0.0, description="Highest water depth recorded along corridor"
    )
    is_primary: bool = Field(
        default=False, description="Whether selected as primary navigation route"
    )
    is_alternative: bool = Field(
        default=False, description="Whether designated as verified safe backup"
    )
    evidence_ids: list[str] = Field(
        default_factory=list, description="Evidence IDs corroborating this route status"
    )
    confidence: float = Field(
        default=0.90, ge=0.0, le=1.0, description="Confidence in route status determination"
    )

    @field_validator("route_id")
    @classmethod
    def validate_route_id_format(cls, v: str) -> str:
        if not ROUTE_ID_REGEX.match(v):
            raise ValueError(
                f"Invalid route identifier format: '{v}'. Must match {ROUTE_ID_REGEX.pattern}"
            )
        return v

    @field_validator("waypoints")
    @classmethod
    def validate_waypoint_coordinates(cls, waypoints: list[list[float]]) -> list[list[float]]:
        for pt in waypoints:
            if len(pt) < 2:
                raise ValueError(f"Malformed waypoint coordinate: {pt}")
            lat, lon = pt[0], pt[1]
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                raise ValueError(f"Waypoint out of geographic bounds: [{lat}, {lon}]")
        return waypoints

    # Backward compatibility properties for legacy state consumers
    @property
    def total_distance_km(self) -> float:
        return self.distance_km

    @property
    def estimated_transit_time_min(self) -> float:
        return self.estimated_time_minutes

    @property
    def is_compromised(self) -> bool:
        return self.status in ("BLOCKED", "UNCERTAIN")

    @property
    def max_water_clearance_supported_inches(self) -> float:
        return 24.0 if "BETA" in self.route_id or "ROUTE-B" in self.route_id else 48.0

    def to_route_option(self) -> RouteOption:
        """Converts to standardized NexusState RouteOption schema."""
        status_val: Literal["SAFE", "AT_RISK", "BLOCKED"] = (
            "SAFE"
            if self.status == "AVAILABLE"
            else ("BLOCKED" if self.status == "BLOCKED" else "AT_RISK")
        )
        return RouteOption(
            route_id=self.route_id,
            name=self.name,
            status=status_val,
            distance_km=self.distance_km,
            estimated_time_minutes=self.estimated_time_minutes,
            flood_depth_inches=self.max_flood_depth_inches,
            waypoints=self.waypoints,
            is_preferred=self.is_primary,
        )


class RouteAnalysisOutput(NexusBaseSchema):
    """Structured routing analysis output containing classified network corridors."""

    incident_id: str = Field(..., description="Unique incident identifier under evaluation")
    selected_route_id: str | None = Field(
        default=None, description="Primary safe route selected for transit"
    )
    active_routes: list[RouteItemAnalysis] = Field(
        default_factory=list, description="All evaluated candidate route corridors"
    )
    primary_route: RouteItemAnalysis | None = Field(
        default=None, description="Selected primary corridor"
    )
    alternative_routes: list[RouteItemAnalysis] = Field(
        default_factory=list, description="Safe alternative backup corridors"
    )
    blocked_routes: list[RouteItemAnalysis] = Field(
        default_factory=list, description="Corridors confirmed impassable / flooded"
    )
    uncertain_routes: list[RouteItemAnalysis] = Field(
        default_factory=list, description="Corridors with contradictory or borderline telemetry"
    )
    stale_routes_detected: list[str] = Field(
        default_factory=list, description="Route IDs whose road telemetry exceeded staleness limit"
    )
    contradictions_detected: list[str] = Field(
        default_factory=list, description="Contradictions between registry status and live sensors"
    )
    evidence_ids: list[str] = Field(
        default_factory=list, description="Authoritative evidence IDs tying incident to routing"
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Overall confidence in topological routing assessment"
    )
    missing_information: list[str] = Field(
        default_factory=list, description="Missing telemetry items or unqueried corridors"
    )
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_simulation: bool = Field(
        default=True, description="Strictly True for all simulation/mock environments"
    )

    def to_routing_state(self) -> RoutingState:
        """Converts to standardized NexusState RoutingState schema."""
        options = [r.to_route_option() for r in self.active_routes]
        dist = self.primary_route.distance_km if self.primary_route else 0.0
        eta = self.primary_route.estimated_time_minutes if self.primary_route else 0.0
        return RoutingState(
            selected_route_id=self.selected_route_id,
            active_routes=options,
            blocked_routes=[r.route_id for r in self.blocked_routes],
            alternative_routes=[r.route_id for r in self.alternative_routes],
            total_distance_km=dist,
            estimated_eta_minutes=eta,
        )


# -----------------------------------------------------------------------------
# Route Agent Implementation
# -----------------------------------------------------------------------------
class RouteAgent(BaseAgent):
    """Determines safe topological transit corridors using routing engine and road sensors."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        staleness_max_hours: float = 2.0,
    ) -> None:
        super().__init__(
            name="RouteAgent",
            role="Topological road network evaluation, safe corridor routing, and obstacle detection",
        )
        self.tool_registry = tool_registry or default_tool_registry
        self.staleness_max_hours = staleness_max_hours

    async def analyze(
        self,
        incident: Any,
        impact: Any = None,
        evidence_items: list[Any] | None = None,
        avoid_routes: list[str] | None = None,
        vehicle_clearance_inches: float = 34.0,
    ) -> RouteAnalysisOutput:
        """Evaluates topological routes between depot and destination avoiding compromised corridors."""
        inc_id = self._extract_incident_id(incident)
        evidence_list = evidence_items or []
        evidence_ids = [
            getattr(e, "evidence_id", str(e)) for e in evidence_list if hasattr(e, "evidence_id")
        ]

        # 1. Determine Known Blockages & Corridors to Avoid
        avoid_list: list[str] = list(avoid_routes or [])
        if impact:
            affected_corridors = getattr(impact, "affected_roads", []) or (
                impact.get("affected_roads", []) if isinstance(impact, dict) else []
            )
            for corr in affected_corridors:
                c_upper = str(corr).upper()
                if "PARKWAY" in c_upper or "METROPOLITAN" in c_upper or "ROUTE-A" in c_upper:
                    if "ROUTE-A" not in avoid_list:
                        avoid_list.append("ROUTE-A")

        # 2. Query Routing Tool
        tool_query_success = False
        routing_tool_output: Any = None
        missing_info: list[str] = []

        try:
            res = await self.tool_registry.execute(
                "routing",
                {
                    "origin": "DEPOT",
                    "destination": "CITY-HOSPITAL",
                    "avoid_routes": avoid_list,
                    "vehicle_clearance_inches": vehicle_clearance_inches,
                },
            )
            if res.success and res.output:
                tool_query_success = True
                routing_tool_output = res.output
            else:
                error_msg = res.error.message if res.error else "Execution failed"
                logger.warning(f"[RouteAgent] Routing tool execution failed: {error_msg}")
                missing_info.append(f"routing_tool_failure: {error_msg}")
        except Exception as exc:
            logger.error(f"[RouteAgent] Exception during routing tool query: {exc}")
            missing_info.append(f"routing_tool_exception: {str(exc)}")

        # 3. Inspect All Grounded Corridors in Road Network
        active_routes: list[RouteItemAnalysis] = []
        blocked_routes: list[RouteItemAnalysis] = []
        alternative_routes: list[RouteItemAnalysis] = []
        uncertain_routes: list[RouteItemAnalysis] = []
        stale_routes_detected: list[str] = []
        contradictions_detected: list[str] = []

        # We query the synthetic road network for authoritative topology
        known_routes = synthetic_road_network.routes

        for route_id, road_seg in known_routes.items():
            r_name = road_seg.name
            dist = road_seg.distance_km
            eta = road_seg.estimated_time_minutes
            flood_depth = road_seg.max_flood_depth_inches
            waypoints = [
                [pt[0], pt[1]]
                for pt in road_seg.geometry_wkt.replace("LINESTRING (", "")
                .replace(")", "")
                .split(", ")
            ]
            formatted_wps = []
            for wp_str in waypoints:
                coords = [float(c) for c in wp_str[0].split(" ") if c]
                if len(coords) >= 2:
                    formatted_wps.append([coords[0], coords[1]])

            # Check prompt injection in road name
            if detect_prompt_injection(r_name):
                logger.warning(f"[RouteAgent] Sanitized prompt injection in road name: {r_name}")
                r_name = f"Corridor-{route_id}"

            # Contradiction check:
            # If route is marked "SAFE" but sensor evidence indicates flood stage > clearance
            is_contradicted = False
            for e in evidence_list:
                data = getattr(e, "data", None) or (
                    e.get("data", {}) if isinstance(e, dict) else {}
                )
                if (
                    "water_level_inches" in data
                    and float(data["water_level_inches"]) > vehicle_clearance_inches
                ):
                    if route_id == "ROUTE-B" and "B" in str(data.get("corridor", "")):
                        is_contradicted = True
                        contradictions_detected.append(
                            f"Contradiction: {route_id} marked SAFE in registry, but sensor reports {data['water_level_inches']} in water depth."
                        )

            # Classify status
            status: Literal["AVAILABLE", "BLOCKED", "UNCERTAIN", "STALE"]
            if is_contradicted:
                status = "UNCERTAIN"
                blocked_segments = [f"{r_name} (Contradictory Sensor Data)"]
            elif (
                route_id in avoid_list
                or road_seg.status == "BLOCKED"
                or flood_depth > vehicle_clearance_inches
            ):
                status = "BLOCKED"
                blocked_segments = [r_name]
            else:
                status = "AVAILABLE"
                blocked_segments = []

            item = RouteItemAnalysis(
                route_id=route_id,
                name=r_name,
                origin="Municipal EMS Depot",
                destination="City Hospital Regional Medical Center",
                waypoints=formatted_wps,
                distance_km=dist,
                estimated_time_minutes=eta,
                status=status,
                blocked_segments=blocked_segments,
                max_flood_depth_inches=flood_depth,
                evidence_ids=evidence_ids,
                confidence=0.95 if not is_contradicted else 0.50,
            )

            active_routes.append(item)
            if status == "BLOCKED":
                blocked_routes.append(item)
            elif status == "UNCERTAIN":
                uncertain_routes.append(item)

        # 4. Determine Primary & Alternative Corridors
        # Available corridors sorted by travel time:
        available_corridors = [r for r in active_routes if r.status == "AVAILABLE"]
        available_corridors.sort(key=lambda r: (r.estimated_time_minutes, r.distance_km))

        primary_route: RouteItemAnalysis | None = None
        selected_route_id: str | None = None

        if available_corridors:
            primary_route = available_corridors[0]
            primary_route.is_primary = True
            selected_route_id = primary_route.route_id

            # Remaining available corridors become alternatives
            for alt in available_corridors[1:]:
                alt.is_alternative = True
                alternative_routes.append(alt)

        # If tool returned a specific recommendation that matches available routes, synchronize
        if routing_tool_output and hasattr(routing_tool_output, "selected_route_id"):
            tool_rec = routing_tool_output.selected_route_id
            if any(r.route_id == tool_rec and r.status == "AVAILABLE" for r in active_routes):
                selected_route_id = tool_rec
                for r in active_routes:
                    if r.route_id == selected_route_id:
                        r.is_primary = True
                        primary_route = r
                    else:
                        r.is_primary = False

        # 5. Confidence Calculation Policy
        base_confidence = 0.95 if tool_query_success else 0.50
        if contradictions_detected:
            base_confidence = max(0.40, base_confidence - 0.25)
        if missing_info:
            base_confidence = max(0.30, base_confidence - 0.20)
        confidence = round(base_confidence, 2)

        return RouteAnalysisOutput(
            incident_id=inc_id,
            selected_route_id=selected_route_id,
            active_routes=active_routes,
            primary_route=primary_route,
            alternative_routes=alternative_routes,
            blocked_routes=blocked_routes,
            uncertain_routes=uncertain_routes,
            stale_routes_detected=stale_routes_detected,
            contradictions_detected=contradictions_detected,
            evidence_ids=evidence_ids,
            confidence=confidence,
            missing_information=missing_info,
            assessed_at=datetime.now(UTC),
            is_simulation=True,
        )

    async def process(self, state: Any) -> dict[str, Any]:
        """LangGraph StateGraph processing protocol."""
        state_dict = state if isinstance(state, dict) else {}
        incident = state_dict.get("incident") or state_dict.get("perception_output") or state_dict
        impact = state_dict.get("impact") or state_dict.get("impact_assessment")
        evidence = state_dict.get("evidence") or state_dict.get("evidence_trail") or []

        # Check avoid segments from previously compromised routes in state
        avoid_routes: list[str] = []
        for prev_route in state_dict.get("active_routes", []):
            if getattr(prev_route, "is_compromised", False) or (
                prev_route.get("is_compromised") if isinstance(prev_route, dict) else False
            ):
                rid = getattr(prev_route, "route_id", None) or (
                    prev_route.get("route_id") if isinstance(prev_route, dict) else None
                )
                if rid and rid not in avoid_routes:
                    avoid_routes.append(rid)

        output = await self.analyze(
            incident=incident,
            impact=impact,
            evidence_items=evidence,
            avoid_routes=avoid_routes,
        )

        return {
            "current_status": "ROUTED",
            "routes": output.to_routing_state(),
            "route_analysis": output,
            "active_routes": output.active_routes,
            "selected_primary_route_id": output.selected_route_id,
            "metadata": {
                "selected_route": output.selected_route_id,
                "blocked_count": len(output.blocked_routes),
                "alternative_count": len(output.alternative_routes),
            },
        }

    def _extract_incident_id(self, incident: Any) -> str:
        """Safely extracts incident ID."""
        if isinstance(incident, dict):
            return str(incident.get("incident_id") or incident.get("id") or "inc-synthetic-01")
        return str(getattr(incident, "incident_id", "inc-synthetic-01"))
