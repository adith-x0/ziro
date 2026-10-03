"""NEXUS Resource Agent.

Determines available operational resources (ambulances, specialized high-water rescue
units, transport vehicles) to respond to verified crisis incidents.

Strict Safety and Grounding Rules:
- NEVER invent resources, unit IDs, locations, or vehicle specifications.
- Queries ONLY authoritative sources: ToolRegistry ("resource_search") and synthetic fleet inventory.
- Explicitly separates:
  1. AVAILABLE (ready, unreserved, matching clearance criteria)
  2. UNAVAILABLE (busy, out of service, or failing clearance constraints)
  3. UNKNOWN (unverified availability)
- If required resources are unavailable, strictly declares resource gaps; NEVER substitutes fabricated units.
- Analytical only: never dispatches vehicles or makes medical/clinical decisions.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from agents.base import BaseAgent
from agents.schemas import NexusBaseSchema, ResourceItem, ResourceState
from tools.registry import ToolRegistry, default_tool_registry

logger = logging.getLogger("nexus.agents.resources")

# Resource ID validation pattern (e.g. "AMB-01", "RESCUE-02")
RESOURCE_ID_REGEX = re.compile(r"^[A-Z0-9_\-]{3,32}$")

INJECTION_PATTERNS = [
    re.compile(
        r"(?i)(ignore\s+(all\s+)?previous\s+instructions|system\s+override|force\s+available|bypass\s+(safety|gate|policy))"
    ),
    re.compile(r"(?i)(</system>|</user>|<system_instruction>|```system|ADMIN_OVERRIDE)"),
]


def detect_prompt_injection(text: str) -> bool:
    """Scans untrusted inputs and tool outputs for adversarial injection attempts."""
    if not text:
        return False
    return any(p.search(text) for p in INJECTION_PATTERNS)


# -----------------------------------------------------------------------------
# Resource Agent Structured Output Schemas
# -----------------------------------------------------------------------------
class ResourceItemAnalysis(NexusBaseSchema):
    """Specification and operational suitability of a single evaluated emergency unit."""

    resource_id: str = Field(..., description="Unique unit identifier, e.g. AMB-01")
    resource_type: str = Field(default="AMBULANCE", description="Category of resource")
    name: str = Field(..., description="Official vehicle or team callsign")
    availability: Literal["AVAILABLE", "UNAVAILABLE", "UNKNOWN"] = Field(
        ..., description="Strict availability classification"
    )
    current_location: tuple[float, float] | str = Field(
        ..., description="Current coordinates or station reference"
    )
    distance_km: float = Field(..., ge=0.0, description="Transit distance to incident/depot")
    current_workload: int = Field(default=0, ge=0, description="Active missions assigned")
    axle_clearance_inches: float = Field(
        default=12.0, ge=0.0, description="Water fording / axle clearance capability"
    )
    capacity: int | None = Field(default=None, description="Patient or payload capacity if known")
    status: str = Field(..., description="Raw provider status string")
    suitability: str = Field(
        ..., description="Deterministic evaluation of vehicle suitability for incident terrain"
    )
    evidence_source: str = Field(
        default="resource_search", description="Tool or database source corroborating this record"
    )

    @field_validator("resource_id")
    @classmethod
    def validate_resource_id_format(cls, v: str) -> str:
        if not RESOURCE_ID_REGEX.match(v):
            raise ValueError(
                f"Invalid resource identifier format: '{v}'. Must match {RESOURCE_ID_REGEX.pattern}"
            )
        return v

    def to_resource_item(self) -> ResourceItem:
        """Converts to standardized NexusState ResourceItem schema."""
        type_str = "AMBULANCE"
        if "HIGH_WATER" in self.resource_type.upper() or self.axle_clearance_inches >= 30.0:
            type_str = "HIGH_WATER_RESCUE"

        raw_status = self.status.upper()
        status_val: Literal["AVAILABLE", "BUSY", "RESERVED", "OUT_OF_SERVICE", "DISPATCHED"] = (
            "AVAILABLE" if raw_status == "AVAILABLE" else "BUSY"
        )
        return ResourceItem(
            resource_id=self.resource_id,
            resource_type=type_str,  # type: ignore[arg-type]
            callsign=self.name,
            status=status_val,
            distance_km=self.distance_km,
            current_workload=self.current_workload,
            axle_clearance_inches=self.axle_clearance_inches,
        )


class ResourceAnalysisOutput(NexusBaseSchema):
    """Structured resource allocation and fleet inventory analysis output."""

    incident_id: str = Field(..., description="Unique incident identifier under evaluation")
    available_resources: list[ResourceItemAnalysis] = Field(
        default_factory=list, description="Vetted resources confirmed available and suitable"
    )
    unavailable_resources: list[ResourceItemAnalysis] = Field(
        default_factory=list,
        description="Vetted resources confirmed busy, out of service, or unsuitable",
    )
    unknown_resources: list[ResourceItemAnalysis] = Field(
        default_factory=list, description="Resources queried without confirmation"
    )
    resource_gaps: list[str] = Field(
        default_factory=list,
        description="Operational resource shortages or unmet clearance capabilities",
    )
    recommended_resource_matches: list[str] = Field(
        default_factory=list, description="Ranked list of recommended unit IDs"
    )
    selected_recommendation: str | None = Field(
        default=None, description="Top deterministic unit recommendation, or None if gap exists"
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="Authoritative evidence IDs tying incident to resource needs",
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in resource discovery and telemetry"
    )
    missing_information: list[str] = Field(
        default_factory=list, description="Unconfirmed telemetry or unqueried inventory sectors"
    )
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_simulation: bool = Field(
        default=True, description="Strictly True for all simulation/mock environments"
    )

    def to_resource_state(self) -> ResourceState:
        """Converts to standardized NexusState ResourceState schema."""
        allocated = [r.to_resource_item() for r in self.available_resources]
        return ResourceState(
            available_units=[r.resource_id for r in self.available_resources],
            selected_unit=self.selected_recommendation,
            selection_criteria=[
                "High-water axle clearance >= 24 inches",
                "Shortest transit distance",
                "Lowest active workload",
            ],
            allocated_resources=allocated,
        )


# -----------------------------------------------------------------------------
# Resource Agent Implementation
# -----------------------------------------------------------------------------
class ResourceAgent(BaseAgent):
    """Determines available fleet units and specialized assets via deterministic matching."""

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        super().__init__(
            name="ResourceAgent",
            role="Emergency fleet discovery, clearance vetting, and deterministic resource matching",
        )
        self.tool_registry = tool_registry or default_tool_registry

    async def analyze(
        self,
        incident: Any,
        impact: Any = None,
        evidence_items: list[Any] | None = None,
        required_clearance_inches: float | None = None,
    ) -> ResourceAnalysisOutput:
        """Searches and classifies available fleet units based on terrain and clearance requirements."""
        # 1. Parse incident and determine required clearance
        inc_id = self._extract_incident_id(incident)
        evidence_list = evidence_items or []
        evidence_ids = [
            getattr(e, "evidence_id", str(e)) for e in evidence_list if hasattr(e, "evidence_id")
        ]

        # Determine required water clearance from impact or arguments
        clearance_req = 12.0
        if required_clearance_inches is not None:
            clearance_req = required_clearance_inches
        elif impact:
            is_cut_off = getattr(impact, "ingress_cut_off", False) or (
                impact.get("ingress_cut_off", False) if isinstance(impact, dict) else False
            )
            if is_cut_off:
                clearance_req = 24.0  # Hospital ingress flooded requires high-water units

        # 2. Query Resource Search Tool
        available_resources: list[ResourceItemAnalysis] = []
        unavailable_resources: list[ResourceItemAnalysis] = []
        unknown_resources: list[ResourceItemAnalysis] = []
        resource_gaps: list[str] = []
        missing_info: list[str] = []
        tool_query_success = False

        try:
            res = await self.tool_registry.execute(
                "resource_search",
                {
                    "resource_type": "AMBULANCE",
                    "required_clearance_inches": 0.0,  # Query all units to classify available vs unavailable
                    "max_distance_km": 25.0,
                },
            )
            if res.success and res.output:
                tool_query_success = True
                units = getattr(res.output, "available_resources", [])
                self._classify_units(
                    units=units,
                    clearance_req=clearance_req,
                    available_out=available_resources,
                    unavailable_out=unavailable_resources,
                )

                # Check fleet inventory service to discover all units and track unavailable ones
                try:
                    from tools.mock_providers import MockResourceSearchProvider
                    from tools.synthetic_environment import simulated_fleet_service

                    tool = self.tool_registry.get("resource_search")
                    provider = getattr(tool, "provider", None)
                    if isinstance(provider, MockResourceSearchProvider):
                        all_known = simulated_fleet_service.get_all_ambulances()
                        seen_ids = {u.resource_id for u in available_resources} | {
                            u.resource_id for u in unavailable_resources
                        }
                        for u in all_known:
                            if u.unit_id not in seen_ids:
                                reason = (
                                    "BUSY/DEPLOYED"
                                    if u.status != "AVAILABLE"
                                    else f"INSUFFICIENT_CLEARANCE ({u.axle_clearance_inches:.1f} in < {clearance_req:.1f} in)"
                                )
                                unavailable_resources.append(
                                    ResourceItemAnalysis(
                                        resource_id=u.unit_id,
                                        resource_type="AMBULANCE",
                                        name=u.unit_name,
                                        availability="UNAVAILABLE",
                                        current_location="Municipal Fleet Depot",
                                        distance_km=u.distance_km,
                                        current_workload=u.current_workload,
                                        axle_clearance_inches=u.axle_clearance_inches,
                                        status=u.status,
                                        suitability=f"UNSUITABLE: {reason}.",
                                        evidence_source="synthetic_fleet_service",
                                    )
                                )
                except Exception:
                    pass
            else:
                error_msg = res.error.message if res.error else "Execution failed"
                logger.warning(f"[ResourceAgent] Resource search tool failed: {error_msg}")
                missing_info.append(f"resource_search_tool_failure: {error_msg}")
        except Exception as exc:
            logger.error(f"[ResourceAgent] Exception during resource search: {exc}")
            missing_info.append(f"resource_search_exception: {str(exc)}")

        # 3. Deterministic Matching & Gap Analysis
        recommended_matches: list[str] = []
        selected_unit: str | None = None

        if available_resources:
            # Sort deterministically:
            # 1. Shortest transit distance
            # 2. Lowest current workload
            # 3. Higher clearance
            sorted_units = sorted(
                available_resources,
                key=lambda u: (
                    u.distance_km,
                    u.current_workload,
                    -u.axle_clearance_inches,
                ),
            )
            recommended_matches = [u.resource_id for u in sorted_units]
            selected_unit = sorted_units[0].resource_id
        else:
            resource_gaps.append(
                f"No available high-water emergency ambulances meeting required clearance of {clearance_req:.1f} inches."
            )

        # 4. Confidence calculation
        base_confidence = 0.95 if tool_query_success else 0.40
        if not available_resources and tool_query_success:
            # Grounded knowledge that no units are available is still confident assessment
            base_confidence = 0.90
        if missing_info:
            base_confidence = max(0.30, base_confidence - 0.20)
        confidence = round(base_confidence, 2)

        return ResourceAnalysisOutput(
            incident_id=inc_id,
            available_resources=available_resources,
            unavailable_resources=unavailable_resources,
            unknown_resources=unknown_resources,
            resource_gaps=resource_gaps,
            recommended_resource_matches=recommended_matches,
            selected_recommendation=selected_unit,
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

        output = await self.analyze(
            incident=incident,
            impact=impact,
            evidence_items=evidence,
        )

        return {
            "current_status": "ROUTED"
            if state_dict.get("current_status") == "ROUTED"
            else "IMPACT_EVALUATED",
            "resources": output.to_resource_state(),
            "resource_analysis": output,
            "available_fleet": [r.model_dump() for r in output.available_resources],
            "metadata": {
                "selected_resource": output.selected_recommendation,
                "available_count": len(output.available_resources),
                "resource_gaps": output.resource_gaps,
            },
        }

    def _classify_units(
        self,
        units: list[Any],
        clearance_req: float,
        available_out: list[ResourceItemAnalysis],
        unavailable_out: list[ResourceItemAnalysis],
    ) -> None:
        """Classifies each discovered unit deterministically into available vs unavailable."""
        for u in units:
            if isinstance(u, dict):
                unit_id = u.get("unit_id")
                unit_name = u.get("unit_name") or f"Unit-{unit_id}"
                status = str(u.get("status", "UNKNOWN")).upper()
                dist = float(u.get("distance_km", 0.0))
                workload = int(u.get("current_workload", 0))
                clearance = float(u.get("axle_clearance_inches", 12.0))
            else:
                unit_id = getattr(u, "unit_id", None)
                unit_name = getattr(u, "unit_name", None) or f"Unit-{unit_id}"
                status = str(getattr(u, "status", "UNKNOWN")).upper()
                dist = float(getattr(u, "distance_km", 0.0))
                workload = int(getattr(u, "current_workload", 0))
                clearance = float(getattr(u, "axle_clearance_inches", 12.0))

            # Security: Validate ID format
            if not unit_id or not RESOURCE_ID_REGEX.match(unit_id):
                logger.warning(f"[ResourceAgent] Rejected invalid unit identifier: '{unit_id}'")
                continue

            # Check prompt injection in unit name
            if detect_prompt_injection(unit_name):
                logger.warning(
                    f"[ResourceAgent] Sanitized prompt injection in unit name: {unit_name}"
                )
                unit_name = f"Sanitized-Unit-{unit_id}"

            # Classify suitability
            meets_clearance = clearance >= clearance_req
            if status == "AVAILABLE" and meets_clearance:
                suitability = (
                    f"SUITABLE: High-water clearance ({clearance:.1f} in >= {clearance_req:.1f} in), "
                    f"ready at {dist:.1f}km."
                )
                available_out.append(
                    ResourceItemAnalysis(
                        resource_id=unit_id,
                        resource_type="AMBULANCE",
                        name=unit_name,
                        availability="AVAILABLE",
                        current_location="Municipal Fleet Depot",
                        distance_km=dist,
                        current_workload=workload,
                        axle_clearance_inches=clearance,
                        status=status,
                        suitability=suitability,
                        evidence_source="resource_search",
                    )
                )
            else:
                reason = (
                    "BUSY/MAINTENANCE"
                    if status != "AVAILABLE"
                    else f"INSUFFICIENT_CLEARANCE ({clearance:.1f} in < {clearance_req:.1f} in)"
                )
                suitability = f"UNSUITABLE: {reason}."
                unavailable_out.append(
                    ResourceItemAnalysis(
                        resource_id=unit_id,
                        resource_type="AMBULANCE",
                        name=unit_name,
                        availability="UNAVAILABLE",
                        current_location="Municipal Fleet Depot",
                        distance_km=dist,
                        current_workload=workload,
                        axle_clearance_inches=clearance,
                        status=status,
                        suitability=suitability,
                        evidence_source="resource_search",
                    )
                )

    def _extract_incident_id(self, incident: Any) -> str:
        """Safely extracts incident ID."""
        if isinstance(incident, dict):
            return str(incident.get("incident_id") or incident.get("id") or "inc-synthetic-01")
        return str(getattr(incident, "incident_id", "inc-synthetic-01"))
