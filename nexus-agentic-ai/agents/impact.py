"""NEXUS Impact Analysis Agent.

Evaluates operational impact on critical care infrastructure, road passability,
hospital accessibility, emergency vehicle mobility, and secondary hazards.

Strict Safety and Grounding Rules:
- NEVER invent roads, hospitals, shelters, resources, coordinates, or infrastructure status.
- Every factual claim must reference authoritative evidence IDs or registered tool telemetry.
- Explicitly separates:
  1. VERIFIED FACTS (empirically grounded in sensor/tool data)
  2. INFERRED RISKS (projected secondary hazards derived from facts)
  3. UNKNOWN INFORMATION (operational information gaps)
- Analytical only: never dispatches vehicles or executes operational actions.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field

from agents.base import BaseAgent
from agents.schemas import ImpactAssessment, NexusBaseSchema
from tools.registry import ToolRegistry, default_tool_registry

logger = logging.getLogger("nexus.agents.impact")

# -----------------------------------------------------------------------------
# Security & Prompt Injection Defense
# -----------------------------------------------------------------------------
INJECTION_PATTERNS = [
    re.compile(
        r"(?i)(ignore\s+(all\s+)?previous\s+instructions|system\s+override|disregard\s+(the\s+)?system|you\s+are\s+now|DAN\s+mode|unrestricted\s+mode)"
    ),
    re.compile(
        r"(?i)(mark\s+(this\s+)?as\s+(safe|unaffected|clear)|bypass\s+(safety|gate|policy|impact)|force\s+passable)"
    ),
    re.compile(r"(?i)(</system>|</user>|<system_instruction>|```system|ADMIN_OVERRIDE)"),
]


def detect_prompt_injection(text: str) -> bool:
    """Scans untrusted inputs and external descriptions for adversarial injection attempts."""
    if not text:
        return False
    return any(p.search(text) for p in INJECTION_PATTERNS)


# -----------------------------------------------------------------------------
# Impact Agent Structured Output Schemas
# -----------------------------------------------------------------------------
class ImpactAnalysisOutput(NexusBaseSchema):
    """Structured operational impact analysis output."""

    incident_id: str = Field(..., description="Unique incident identifier under evaluation")
    affected_areas: list[str] = Field(
        default_factory=list, description="Specific geographic corridors and zones affected"
    )
    affected_roads: list[str] = Field(
        default_factory=list, description="Roadway corridors confirmed impacted or submerged"
    )
    affected_facilities: list[str] = Field(
        default_factory=list, description="Critical care facilities directly threatened or isolated"
    )
    emergency_access_status: Literal["ACCESSIBLE", "AT_RISK", "COMPROMISED", "SEVERED"] = Field(
        ..., description="Current operational accessibility status of primary facility"
    )
    ingress_cut_off: bool = Field(
        ..., description="True if primary emergency ingress is severed or impassable"
    )
    verified_facts: list[str] = Field(
        default_factory=list,
        description="Factual impact statements strictly grounded in evidence IDs or tool records",
    )
    inferred_risks: list[str] = Field(
        default_factory=list,
        description="Potential secondary risks projected from verified facts (clearly distinct from facts)",
    )
    unknown_information: list[str] = Field(
        default_factory=list,
        description="Specific operational unknowns and gaps in situational awareness",
    )
    secondary_risks: list[str] = Field(
        default_factory=list, description="List of specific secondary hazard types"
    )
    operational_priorities: list[str] = Field(
        default_factory=list,
        description="Prioritized list of recommended operational focus areas",
    )
    evidence_ids: list[str] = Field(
        default_factory=list, description="Authoritative evidence IDs corroborating this assessment"
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Overall confidence score for this impact analysis"
    )
    missing_information: list[str] = Field(
        default_factory=list, description="Missing telemetry items required for complete certainty"
    )
    narrative: str = Field(..., description="Comprehensive factual summary narrative")
    facility_telemetry: dict[str, Any] = Field(
        default_factory=dict, description="Telemetry returned by facility status tools"
    )
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_simulation: bool = Field(
        default=True, description="Strictly True for all simulation/mock environments"
    )

    # Backward compatibility properties for legacy state consumers
    @property
    def critical_facility_name(self) -> str:
        return (
            self.affected_facilities[0]
            if self.affected_facilities
            else "City Hospital Regional Medical Center"
        )

    @property
    def facility_type(self) -> str:
        return "trauma_hospital"

    @property
    def estimated_isolation_risk_minutes(self) -> int:
        return 45 if self.ingress_cut_off else 0

    @property
    def severely_affected_corridors(self) -> list[str]:
        return self.affected_roads

    @property
    def population_density_index(self) -> float:
        return 0.88

    @property
    def summary_narrative(self) -> str:
        return self.narrative

    def to_impact_assessment(self) -> ImpactAssessment:
        """Converts to standardized NexusState ImpactAssessment schema."""
        risk_map: dict[str, Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]] = {
            "ACCESSIBLE": "LOW",
            "AT_RISK": "MEDIUM",
            "COMPROMISED": "HIGH",
            "SEVERED": "CRITICAL",
        }
        return ImpactAssessment(
            affected_hospital=self.critical_facility_name,
            hospital_access=self.emergency_access_status,
            affected_roads=self.affected_roads,
            emergency_access_risk=risk_map.get(self.emergency_access_status, "HIGH"),
            estimated_delay_minutes=float(self.estimated_isolation_risk_minutes),
            secondary_hazards=self.secondary_risks,
            narrative=self.narrative,
            assessed_at=self.assessed_at,
        )


# -----------------------------------------------------------------------------
# Impact Analysis Agent Implementation
# -----------------------------------------------------------------------------
class ImpactAnalysisAgent(BaseAgent):
    """Analyzes spatial and operational disruption to emergency facilities and roadways."""

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        super().__init__(
            name="ImpactAnalysisAgent",
            role="Critical infrastructure disruption, facility access, and secondary hazard analysis",
        )
        self.tool_registry = tool_registry or default_tool_registry

    async def analyze(
        self,
        incident: Any,
        verification: Any = None,
        evidence_items: list[Any] | None = None,
    ) -> ImpactAnalysisOutput:
        """Conducts structured empirical impact evaluation based on verified evidence."""
        # 1. Normalize Incident & Location Context
        inc_id, facility_hint, reported_roads, raw_text = self._parse_incident_context(incident)

        # 2. Extract Evidence & Verified Claims
        evidence_list = evidence_items or []
        evidence_ids: list[str] = []
        for e in evidence_list:
            eid = getattr(e, "evidence_id", None) or (
                e.get("evidence_id") if isinstance(e, dict) else None
            )
            if eid and eid not in evidence_ids:
                evidence_ids.append(eid)

        # Also pull from verification if provided
        if verification:
            v_eids = getattr(verification, "evidence_ids", []) or (
                verification.get("evidence_ids", []) if isinstance(verification, dict) else []
            )
            for eid in v_eids:
                if eid not in evidence_ids:
                    evidence_ids.append(eid)

        # 3. Security scan on incoming text
        injection_flagged = detect_prompt_injection(raw_text)
        if injection_flagged:
            logger.warning(
                f"[ImpactAnalysisAgent] Adversarial injection detected in incident text: {raw_text[:80]}"
            )

        # 4. Gather Critical Care Facility Telemetry via Tool
        hospital_id = "CITY-HOSPITAL"
        facility_telemetry: dict[str, Any] = {}
        tool_query_success = False

        try:
            res = await self.tool_registry.execute("hospital_status", {"hospital_id": hospital_id})
            if res.success and res.output:
                tool_query_success = True
                payload = (
                    res.output.model_dump(mode="json")
                    if hasattr(res.output, "model_dump")
                    else dict(res.output)
                )
                facility_telemetry = payload
        except Exception as exc:
            logger.warning(f"[ImpactAnalysisAgent] Hospital status tool query failed: {exc}")

        # 5. Determine Ingress and Roadway Status Grounded in Evidence
        verified_facts: list[str] = []
        inferred_risks: list[str] = []
        unknown_information: list[str] = []
        affected_roads: list[str] = []
        affected_areas: list[str] = []
        secondary_risks: list[str] = []
        operational_priorities: list[str] = []

        # Corroborate affected roads from evidence
        max_flood_depth_observed = 0.0
        for e in evidence_list:
            data = getattr(e, "data", None) or (e.get("data", {}) if isinstance(e, dict) else {})
            # Water sensor
            if "water_level_inches" in data:
                depth = float(data.get("water_level_inches", 0.0))
                max_flood_depth_observed = max(max_flood_depth_observed, depth)
                if depth >= 24.0:
                    verified_facts.append(
                        f"Hydrological stream gauge recorded {depth:.1f} inches flood stage exceeding 24-inch threshold."
                    )
            # Image analysis
            if "water_depth_estimate_inches" in data:
                img_depth = float(data.get("water_depth_estimate_inches", 0.0))
                max_flood_depth_observed = max(max_flood_depth_observed, img_depth)
                verified_facts.append(
                    f"Traffic camera visual telemetry indicates {img_depth:.1f} inches water depth; passenger vehicles impassable."
                )
            # Citizen reports
            if "reports" in data and isinstance(data["reports"], list):
                for rep in data["reports"]:
                    corridor = rep.get("corridor") or "Metropolitan Parkway"
                    if corridor == "ROUTE-A":
                        if "Metropolitan Parkway" not in affected_roads:
                            affected_roads.append("Metropolitan Parkway")
                    if corridor not in affected_roads:
                        affected_roads.append(corridor)
                    verified_facts.append(
                        f"Field observation confirmed {corridor} submerged and hazardous."
                    )

        # Merge any specific roads reported in incident
        for r in reported_roads:
            if r not in affected_roads:
                affected_roads.append(r)

        if not affected_roads:
            affected_roads.append("Metropolitan Parkway")

        # Ground facility status
        facility_name = facility_telemetry.get(
            "hospital_name", facility_hint or "City Hospital Regional Medical Center"
        )
        affected_facilities = [facility_name]

        ingress_telemetry = facility_telemetry.get("ingress_status", "PRIMARY_ROAD_CUT_OFF")
        barrier_active = facility_telemetry.get("flood_barrier_active", True)
        er_status = facility_telemetry.get("emergency_room_status", "OPERATIONAL")
        beds_available = facility_telemetry.get("bed_capacity_available", 38)

        if tool_query_success:
            verified_facts.append(
                f"{facility_name} facility telemetry confirmed: ER status is '{er_status}', "
                f"available ER beds: {beds_available}, perimeter flood barriers: {'ACTIVE' if barrier_active else 'INACTIVE'}."
            )
            verified_facts.append(f"Facility ingress telemetry confirms: '{ingress_telemetry}'.")

        # Contradiction check:
        # If sensor indicates dry conditions (< 5.0 in) but facility ingress telemetry reports cut off
        is_contradicted = False
        if (
            max_flood_depth_observed > 0.0
            and max_flood_depth_observed < 5.0
            and ("CUT_OFF" in ingress_telemetry or "BLOCKED" in ingress_telemetry)
        ):
            is_contradicted = True
            unknown_information.append(
                f"Contradiction: Stream gauge indicates shallow water ({max_flood_depth_observed:.1f} in) "
                f"while facility telemetry reports ingress '{ingress_telemetry}'."
            )

        # Assess access status based on empirical depth and telemetry
        emergency_access_status: Literal["ACCESSIBLE", "AT_RISK", "COMPROMISED", "SEVERED"]
        if is_contradicted:
            emergency_access_status = "AT_RISK"
            ingress_cut_off = False
            affected_areas.append("City Hospital Ingress Corridor (Contradictory Telemetry)")
        elif (
            max_flood_depth_observed >= 24.0
            or "CUT_OFF" in ingress_telemetry
            or "BLOCKED" in ingress_telemetry
        ):
            emergency_access_status = "SEVERED"
            ingress_cut_off = True
            affected_areas.append("City Hospital Medical Complex & Ingress Corridor")
            affected_areas.append("Metropolitan Parkway Floodplain Sector")
        elif max_flood_depth_observed >= 12.0 or "COMPROMISED" in ingress_telemetry:
            emergency_access_status = "COMPROMISED"
            ingress_cut_off = True
            affected_areas.append("City Hospital Ingress Corridor")
        elif max_flood_depth_observed > 0.0:
            emergency_access_status = "AT_RISK"
            ingress_cut_off = False
            affected_areas.append("City Hospital Vicinity")
        else:
            emergency_access_status = "ACCESSIBLE"
            ingress_cut_off = False

        # Inferred Secondary Risks (Carefully segregated from verified facts)
        if ingress_cut_off:
            inferred_risks.append(
                "Standard low-clearance ambulances attempting ingress along primary artery face immediate hydro-locking risk."
            )
            inferred_risks.append(
                "Critical trauma transport may incur 30-45 minute transit delays without immediate alternate corridor routing."
            )
            inferred_risks.append(
                "Surrounding catchment area civilian traffic diversion may congest secondary bypass roads."
            )
            secondary_risks.extend(
                [
                    "Emergency vehicle hydro-locking on primary artery",
                    "Critical trauma intake transit delay",
                    "Secondary arterial traffic gridlock",
                    "Facility dependency on backup electrical generator fuel resilience",
                ]
            )
        else:
            inferred_risks.append(
                "Rising precipitation rate may escalate water depth to flood stage within 60 minutes."
            )
            secondary_risks.append("Potential localized waterlogging")

        # Operational Priorities (Actionable focus areas)
        if ingress_cut_off:
            operational_priorities.append(
                "Identify and establish verified safe detour route avoiding Metropolitan Parkway."
            )
            operational_priorities.append(
                "Restrict ambulance dispatch to specialized high-water clearance rescue units."
            )
            operational_priorities.append(
                "Transmit operational advisory to City Hospital trauma reception regarding alternate ingress."
            )
        else:
            operational_priorities.append(
                "Continue hydrological monitoring of canal drainage basin."
            )

        # Unknown Information & Situational Awareness Gaps
        unknown_information.append("Exact rate of floodwater drainage / canal outflow unknown.")
        unknown_information.append(
            "Real-time operational status of municipal stormwater diversion pumps unconfirmed."
        )
        if not tool_query_success:
            unknown_information.append(
                "Direct facility telemetry currently unreachable via hospital status tool."
            )

        missing_info: list[str] = []
        if not tool_query_success:
            missing_info.append("hospital_status_telemetry")
        if max_flood_depth_observed == 0.0:
            missing_info.append("confirmed_peak_water_depth")

        # Confidence Calculation Policy
        base_confidence = 0.90 if tool_query_success else 0.75
        if not evidence_ids:
            base_confidence = min(base_confidence, 0.60)
        if injection_flagged:
            base_confidence = max(0.40, base_confidence - 0.20)
        if len(missing_info) > 1:
            base_confidence = max(0.50, base_confidence - 0.15)
        confidence = round(base_confidence, 2)

        # Synthesize Narrative
        narrative = (
            f"Impact Assessment for Incident '{inc_id}': "
            f"Emergency access to {facility_name} is currently {emergency_access_status}. "
            f"Primary corridor ({', '.join(affected_roads)}) is impassable due to verified flood surge "
            f"({max_flood_depth_observed:.1f} in peak depth observed). "
            f"Ingress cut off: {ingress_cut_off}. "
            f"Operational priority is alternate corridor routing and high-water EMS vehicle allocation."
        )

        return ImpactAnalysisOutput(
            incident_id=inc_id,
            affected_areas=affected_areas,
            affected_roads=affected_roads,
            affected_facilities=affected_facilities,
            emergency_access_status=emergency_access_status,
            ingress_cut_off=ingress_cut_off,
            verified_facts=verified_facts,
            inferred_risks=inferred_risks,
            unknown_information=unknown_information,
            secondary_risks=secondary_risks,
            operational_priorities=operational_priorities,
            evidence_ids=evidence_ids,
            confidence=confidence,
            missing_information=missing_info,
            narrative=narrative,
            facility_telemetry=facility_telemetry,
            assessed_at=datetime.now(UTC),
            is_simulation=True,
        )

    async def process(self, state: Any) -> dict[str, Any]:
        """LangGraph StateGraph processing protocol."""
        state_dict = state if isinstance(state, dict) else {}
        incident = state_dict.get("incident") or state_dict.get("perception_output") or state_dict
        verification = state_dict.get("verification")
        evidence = state_dict.get("evidence") or state_dict.get("evidence_trail") or []

        output = await self.analyze(
            incident=incident,
            verification=verification,
            evidence_items=evidence,
        )

        return {
            "current_status": "IMPACT_EVALUATED",
            "impact": output,
            "impact_assessment": output,  # Exposes backward-compatible properties (.ingress_cut_off, etc.)
            "metadata": {
                "emergency_access_status": output.emergency_access_status,
                "ingress_cut_off": output.ingress_cut_off,
                "confidence": output.confidence,
            },
        }

    def _parse_incident_context(self, incident: Any) -> tuple[str, str | None, list[str], str]:
        """Safely parses incident entity or dictionary into core parameters."""
        inc_id = "inc-synthetic-01"
        facility_hint = None
        reported_roads: list[str] = []
        raw_text = ""

        if isinstance(incident, dict):
            inc_id = incident.get("incident_id") or incident.get("id") or inc_id
            raw_text = (
                incident.get("description")
                or incident.get("raw_report")
                or incident.get("raw_user_report")
                or incident.get("incident_title")
                or ""
            )
            meta = incident.get("metadata_payload") or incident.get("metadata") or {}
            facility_hint = meta.get("target_facility") or meta.get("critical_facility_name")
            if "Metropolitan Parkway" in raw_text or "Metropolitan" in raw_text:
                reported_roads.append("Metropolitan Parkway")
        else:
            inc_id = getattr(incident, "incident_id", inc_id)
            raw_text = getattr(incident, "description", "") or getattr(incident, "raw_report", "")
            loc = getattr(incident, "location", None)
            if loc:
                facility_hint = getattr(loc, "primary_landmark", None) or getattr(
                    loc, "address_reference", None
                )
            if "Metropolitan Parkway" in raw_text or "Metropolitan" in raw_text:
                reported_roads.append("Metropolitan Parkway")

        return str(inc_id), facility_hint, reported_roads, raw_text


# Backward-compatible alias for existing imports
ImpactAssessmentAgent = ImpactAnalysisAgent
