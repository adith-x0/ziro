"""NEXUS Verification Agent.

Independently corroborates incident reports using multi-source empirical evidence:
- Meteorological stream gauges & Doppler rainfall sensors (`weather`)
- Aggregated citizen and responder field dispatches (`incident_reports`)
- Visual flood depth and vehicle passability telemetry (`image_analysis`)
- Spatial landmark and geocoordinate cross-referencing (`geolocation`)

Implements deterministic confidence scoring, contradiction detection, staleness checks,
and prompt injection defense. Grounded strictly in authoritative tool executions with zero fabrication.
"""

from __future__ import annotations

import base64
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agents.base import BaseAgent
from agents.perception import PerceptionOutput
from agents.schemas import EvidenceItem, IncidentData, VerificationResult
from tools.registry import ToolRegistry, default_tool_registry

try:
    from app.config import settings
except ImportError:
    try:
        from backend.app.config import settings  # type: ignore[no-redef]
    except ImportError:
        settings = None  # type: ignore[assignment]


# -----------------------------------------------------------------------------
# Structured Pydantic Verification Output Schemas
# -----------------------------------------------------------------------------
class VerifiedFact(BaseModel):
    """Specific factual claim corroborating the incident, strictly anchored to evidence IDs."""

    model_config = ConfigDict(populate_by_name=True)

    claim: str = Field(..., description="Factual statement verified by empirical source")
    evidence_ids: list[str] = Field(
        ...,
        min_length=1,
        description="Authoritative evidence IDs supporting this claim",
    )
    source_types: list[str] = Field(
        ...,
        min_length=1,
        description="Types of sources corroborating the claim",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Corroboration reliability for this specific fact",
    )


class ContradictionItem(BaseModel):
    """Empirical discrepancy detected between reported claims and ground truth telemetry."""

    model_config = ConfigDict(populate_by_name=True)

    factor: str = Field(
        ...,
        description="Contradicted attribute: e.g. location, severity, weather, timing, security",
    )
    reported_claim: str = Field(..., description="What was asserted in report or perception")
    observed_telemetry: str = Field(..., description="What empirical tools revealed")
    evidence_id: str | None = Field(
        default=None, description="Conflicting evidence ID if applicable"
    )
    severity: Literal["MINOR", "MODERATE", "SEVERE"] = Field(
        ..., description="Operational severity of contradiction"
    )


class VerificationOutput(BaseModel):
    """Structured Pydantic contract produced by NEXUS Verification Agent."""

    model_config = ConfigDict(populate_by_name=True)

    verification_id: str = Field(default_factory=lambda: f"veri-{uuid.uuid4().hex[:8]}")
    incident_id: str = Field(..., description="ID of incident under verification")
    verification_status: Literal[
        "VERIFIED",
        "UNVERIFIED",
        "INSUFFICIENT_EVIDENCE",
        "CONTRADICTED",
        "FLAGGED_INJECTION",
    ] = Field(..., description="Categorical outcome of multi-source verification")
    verified: bool = Field(
        ...,
        description="True if confidence >= threshold and no fatal contradiction",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Deterministic multi-source confidence score",
    )
    confidence_threshold: float = Field(
        default=0.80, description="Configured confidence threshold applied"
    )
    verified_facts: list[VerifiedFact] = Field(
        default_factory=list,
        description="Verified facts bound to evidence IDs",
    )
    unverified_claims: list[str] = Field(
        default_factory=list,
        description="Claims from perception that lacked verification",
    )
    contradictions: list[ContradictionItem] = Field(
        default_factory=list,
        description="Preserved discrepancies across sources",
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="Authoritative IDs of all collected evidence",
    )
    evidence_summary: str = Field(
        ..., description="Comprehensive summary of cross-checked evidence"
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Operational parameters still unconfirmed",
    )
    source_count: int = Field(..., ge=0, description="Number of independent tools/sources queried")
    stale_evidence_detected: bool = Field(
        default=False,
        description="Whether any evidence exceeded staleness threshold",
    )
    tool_execution_status: dict[str, str] = Field(
        default_factory=dict,
        description="Execution status for each tool queried",
    )
    verification_timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_simulation: bool = Field(
        default=True,
        description="Strictly true for all NEXUS mock/simulation processing",
    )

    def to_verification_result(self) -> VerificationResult:
        """Converts to standardized NexusState VerificationResult schema."""
        return VerificationResult(
            verified=self.verified,
            confidence=self.confidence,
            evidence_ids=self.evidence_ids,
            primary_factors=[f.claim for f in self.verified_facts],
            reasoning=self.evidence_summary,
            verified_at=self.verification_timestamp,
        )


# -----------------------------------------------------------------------------
# Security & Prompt Injection Defense Patterns
# -----------------------------------------------------------------------------
INJECTION_PATTERNS = [
    re.compile(
        r"(?i)(ignore\s+(all\s+)?previous\s+instructions|system\s+override|disregard\s+(the\s+)?system|you\s+are\s+now|DAN\s+mode|unrestricted\s+mode)"
    ),
    re.compile(
        r"(?i)(mark\s+(this\s+)?as\s+verified|set\s+confidence\s+to\s+1|force\s+verification|bypass\s+(safety|gate|policy|verification))"
    ),
    re.compile(r"(?i)(</system>|</user>|<system_instruction>|```system|ADMIN_OVERRIDE)"),
]


def detect_prompt_injection(text: str) -> bool:
    """Scans untrusted inputs and tool outputs for adversarial injection attempts."""
    if not text:
        return False
    return any(p.search(text) for p in INJECTION_PATTERNS)


# -----------------------------------------------------------------------------
# Verification Agent Implementation
# -----------------------------------------------------------------------------
class VerificationAgent(BaseAgent):
    """Independent multi-source evidence corroborator and contradiction analyzer."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        confidence_threshold: float | None = None,
        staleness_max_hours: float | None = None,
    ) -> None:
        super().__init__(
            name="VerificationAgent",
            role="Multi-source empirical evidence verification and contradiction detection",
        )
        self.tool_registry = tool_registry or default_tool_registry

        # Configurable thresholds
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else (settings.verification_confidence_threshold if settings else 0.80)
        )
        self.staleness_max_hours = (
            staleness_max_hours
            if staleness_max_hours is not None
            else (settings.evidence_staleness_max_hours if settings else 2.0)
        )
        self._logger = logging.getLogger("nexus.agents.verification")

    async def verify(
        self,
        incident: IncidentData | PerceptionOutput | dict[str, Any],
        perception_output: PerceptionOutput | None = None,
        image_bytes: bytes | None = None,
        image_base64: str | None = None,
        existing_evidence: list[EvidenceItem] | None = None,
    ) -> tuple[VerificationOutput, list[EvidenceItem]]:
        """Executes multi-source empirical corroboration and contradiction detection."""
        # 1. Normalize Incident Inputs
        incident_id, lat, lon, landmark, severity, raw_text, missing_info = (
            self._extract_incident_context(incident, perception_output)
        )

        tool_status: dict[str, str] = {}
        collected_evidence: list[EvidenceItem] = list(existing_evidence or [])
        verified_facts: list[VerifiedFact] = []
        unverified_claims: list[str] = []
        contradictions: list[ContradictionItem] = []
        missing_operational_info: list[str] = list(missing_info)
        stale_detected = False

        # 2. Security Defense: Scan untrusted incident report
        if detect_prompt_injection(raw_text):
            self._logger.warning(
                f"[SECURITY ALERT] Prompt injection pattern detected in incident report: {raw_text[:80]}"
            )
            contra = ContradictionItem(
                factor="security",
                reported_claim="Untrusted incident report payload",
                observed_telemetry="Adversarial instruction injection detected and quarantined",
                severity="SEVERE",
            )
            output = VerificationOutput(
                incident_id=incident_id,
                verification_status="FLAGGED_INJECTION",
                verified=False,
                confidence=0.0,
                confidence_threshold=self.confidence_threshold,
                contradictions=[contra],
                evidence_summary="Verification aborted: Adversarial prompt injection detected in input.",
                missing_information=missing_operational_info,
                source_count=0,
                tool_execution_status={"security": "FLAGGED_INJECTION"},
            )
            return output, collected_evidence

        # 3. Gather Source 1: Meteorological Stream Gauge & Doppler (`weather`)
        weather_ev = await self._gather_weather_evidence(lat, lon, tool_status)
        if weather_ev:
            collected_evidence.append(weather_ev)

        # 4. Gather Source 2: Local Citizen & Responder Reports (`incident_reports`)
        reports_ev = await self._gather_reports_evidence(lat, lon, tool_status)
        if reports_ev:
            collected_evidence.append(reports_ev)

        # 5. Gather Source 3: Geolocation Landmark Resolution (`geolocation`)
        geo_ev = await self._gather_geolocation_evidence(landmark, lat, lon, tool_status)
        if geo_ev:
            collected_evidence.append(geo_ev)

        # 6. Gather Source 4: Traffic Camera & Visual Ingestion (`image_analysis`)
        image_ev = await self._gather_image_evidence(image_bytes, image_base64, tool_status)
        if image_ev:
            collected_evidence.append(image_ev)

        # 7. Security Defense: Scan tool responses for untrusted prompt injection
        for ev in collected_evidence:
            data_str = str(ev.data)
            if detect_prompt_injection(data_str):
                self._logger.warning(
                    f"[SECURITY ALERT] Tool output for source {ev.source_id} contained injection pattern."
                )
                contradictions.append(
                    ContradictionItem(
                        factor="security",
                        reported_claim=f"Tool response from {ev.source_id}",
                        observed_telemetry="Adversarial instruction injection detected in tool response",
                        severity="SEVERE",
                        evidence_id=ev.evidence_id,
                    )
                )

        # 8. Check for Stale Evidence
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=self.staleness_max_hours)
        for ev in collected_evidence:
            obs = ev.observed_at
            if obs.tzinfo is None:
                obs = obs.replace(tzinfo=UTC)
            if obs < cutoff:
                stale_detected = True
                contradictions.append(
                    ContradictionItem(
                        factor="timing",
                        reported_claim="Active ongoing emergency condition",
                        observed_telemetry=(
                            f"Evidence from {ev.source_id} observed at {obs.isoformat()} "
                            f"(exceeds {self.staleness_max_hours}h staleness threshold)"
                        ),
                        evidence_id=ev.evidence_id,
                        severity="MODERATE",
                    )
                )

        # 9. Cross-Check Evidence & Detect Domain Contradictions
        self._cross_check_weather_and_severity(
            severity=severity,
            collected_evidence=collected_evidence,
            verified_facts=verified_facts,
            contradictions=contradictions,
        )
        self._cross_check_incident_reports(
            landmark=landmark,
            collected_evidence=collected_evidence,
            verified_facts=verified_facts,
            contradictions=contradictions,
            unverified_claims=unverified_claims,
            missing_info=missing_operational_info,
        )
        self._cross_check_geolocation(
            reported_lat=lat,
            reported_lon=lon,
            collected_evidence=collected_evidence,
            verified_facts=verified_facts,
            contradictions=contradictions,
        )
        self._cross_check_image_evidence(
            severity=severity,
            collected_evidence=collected_evidence,
            verified_facts=verified_facts,
            contradictions=contradictions,
        )

        # Record unverified claims if essential aspects lacked evidence
        if not any(ev.source_type == "WATER_SENSOR" for ev in collected_evidence):
            unverified_claims.append(
                "Rainfall intensity and flood surge unverified by stream gauge"
            )
            missing_operational_info.append("stream_gauge_telemetry")
        if not any(ev.source_type == "CITIZEN_REPORT" for ev in collected_evidence):
            unverified_claims.append("Field observer corroboration unavailable")
            missing_operational_info.append("citizen_field_observations")

        # 10. Deterministic Confidence Calculation Policy
        confidence = self._calculate_confidence(
            evidence_items=collected_evidence,
            contradictions=contradictions,
            missing_info=missing_operational_info,
            stale_detected=stale_detected,
        )

        # 11. Determine Categorical Verification Status
        source_count = len(collected_evidence)
        severe_contradictions = any(c.severity == "SEVERE" for c in contradictions)

        if severe_contradictions:
            status: Literal[
                "VERIFIED",
                "UNVERIFIED",
                "INSUFFICIENT_EVIDENCE",
                "CONTRADICTED",
                "FLAGGED_INJECTION",
            ] = "CONTRADICTED"
            verified = False
        elif source_count < 2:
            status = "INSUFFICIENT_EVIDENCE"
            verified = False
        elif confidence < self.confidence_threshold:
            status = "UNVERIFIED"
            verified = False
        else:
            status = "VERIFIED"
            verified = True

        # 12. Synthesize Grounded Evidence Summary
        summary = self._synthesize_summary(
            status=status,
            confidence=confidence,
            source_count=source_count,
            verified_facts=verified_facts,
            contradictions=contradictions,
            unverified_claims=unverified_claims,
            tool_status=tool_status,
        )

        output = VerificationOutput(
            incident_id=incident_id,
            verification_status=status,
            verified=verified,
            confidence=confidence,
            confidence_threshold=self.confidence_threshold,
            verified_facts=verified_facts,
            unverified_claims=unverified_claims,
            contradictions=contradictions,
            evidence_ids=[e.evidence_id for e in collected_evidence],
            evidence_summary=summary,
            missing_information=list(set(missing_operational_info)),
            source_count=source_count,
            stale_evidence_detected=stale_detected,
            tool_execution_status=tool_status,
            verification_timestamp=now,
            is_simulation=True,
        )

        return output, collected_evidence

    async def process(self, state: Any) -> dict[str, Any]:
        """LangGraph StateGraph processing protocol."""
        state_dict = state if isinstance(state, dict) else {}
        inc_context = (
            state_dict.get("incident") or state_dict.get("perception_output") or state_dict
        )

        image_bytes = state_dict.get("image_bytes")
        image_base64 = state_dict.get("image_base64")
        existing_evidence = state_dict.get("evidence") or []

        # Convert raw dict evidence if needed
        typed_evidence: list[EvidenceItem] = []
        for e in existing_evidence:
            if isinstance(e, EvidenceItem):
                typed_evidence.append(e)
            elif isinstance(e, dict):
                try:
                    typed_evidence.append(EvidenceItem.model_validate(e))
                except Exception:
                    pass

        verification_output, new_evidence = await self.verify(
            incident=inc_context,
            image_bytes=image_bytes,
            image_base64=image_base64,
            existing_evidence=typed_evidence,
        )

        status_str = "VERIFIED" if verification_output.verified else "UNVERIFIED"

        return {
            "current_status": status_str,
            "verification": verification_output,
            "verification_result": verification_output.to_verification_result(),
            "verification_confidence": verification_output.confidence,
            "evidence": new_evidence,
            "evidence_trail": new_evidence,  # Retained for backward test compatibility
            "metadata": {
                "verification_status": verification_output.verification_status,
                "evidence_ids": verification_output.evidence_ids,
                "tool_execution_status": verification_output.tool_execution_status,
            },
        }

    # -------------------------------------------------------------------------
    # Tool Execution Helper Methods (Isolated & Error-Tolerant)
    # -------------------------------------------------------------------------
    async def _gather_weather_evidence(
        self, lat: float, lon: float, tool_status: dict[str, str]
    ) -> EvidenceItem | None:
        """Queries meteorological stream gauge tool."""
        try:
            res = await self.tool_registry.execute("weather", {"latitude": lat, "longitude": lon})
            if res.success and res.output:
                tool_status["weather"] = "SUCCESS"
                payload = (
                    res.output.model_dump(mode="json")
                    if hasattr(res.output, "model_dump")
                    else dict(res.output)
                )
                return EvidenceItem(
                    source_id="SG-RIVER-401",
                    source_type="WATER_SENSOR",
                    confidence=0.95,
                    data=payload,
                    observed_at=datetime.now(UTC),
                    verified=True,
                )
            error_msg = res.error.message if res.error else "Execution failed"
            tool_status["weather"] = f"ERROR: {error_msg}"
            self._logger.warning(
                f"Weather tool failed: {error_msg}. Continuing without weather telemetry."
            )
        except Exception as exc:
            tool_status["weather"] = f"EXCEPTION: {exc}"
            self._logger.error(f"Weather tool exception: {exc}. Continuing partial verification.")
        return None

    async def _gather_reports_evidence(
        self, lat: float, lon: float, tool_status: dict[str, str]
    ) -> EvidenceItem | None:
        """Queries localized citizen dispatches within radius."""
        try:
            res = await self.tool_registry.execute(
                "incident_reports",
                {"latitude": lat, "longitude": lon, "radius_km": 5.0},
            )
            if res.success and res.output:
                payload = (
                    res.output.model_dump(mode="json")
                    if hasattr(res.output, "model_dump")
                    else dict(res.output)
                )
                total_reports = int(payload.get("total_reports", 0))
                if total_reports == 0:
                    tool_status["incident_reports"] = "NO_REPORTS_IN_RADIUS"
                    return None

                tool_status["incident_reports"] = "SUCCESS"
                return EvidenceItem(
                    source_id="CITIZEN-DISPATCH-FEED",
                    source_type="CITIZEN_REPORT",
                    confidence=0.90,
                    data=payload,
                    observed_at=datetime.now(UTC),
                    verified=True,
                )
            error_msg = res.error.message if res.error else "Execution failed"
            tool_status["incident_reports"] = f"ERROR: {error_msg}"
            self._logger.warning(f"Incident reports tool failed: {error_msg}. Continuing.")
        except Exception as exc:
            tool_status["incident_reports"] = f"EXCEPTION: {exc}"
            self._logger.error(f"Incident reports tool exception: {exc}. Continuing.")
        return None

    async def _gather_geolocation_evidence(
        self,
        landmark: str | None,
        lat: float,
        lon: float,
        tool_status: dict[str, str],
    ) -> EvidenceItem | None:
        """Cross-references reported location against spatial registry."""
        query = landmark or "City Hospital"
        try:
            res = await self.tool_registry.execute(
                "geolocation", {"query_address_or_landmark": query}
            )
            if res.success and res.output:
                tool_status["geolocation"] = "SUCCESS"
                payload = (
                    res.output.model_dump(mode="json")
                    if hasattr(res.output, "model_dump")
                    else dict(res.output)
                )
                return EvidenceItem(
                    source_id="GEO-SURVEY-GIS",
                    source_type="RADAR",
                    confidence=0.95,
                    data=payload,
                    observed_at=datetime.now(UTC),
                    verified=True,
                )
            error_msg = res.error.message if res.error else "Execution failed"
            tool_status["geolocation"] = f"ERROR: {error_msg}"
        except Exception as exc:
            tool_status["geolocation"] = f"EXCEPTION: {exc}"
            self._logger.error(f"Geolocation tool exception: {exc}")
        return None

    async def _gather_image_evidence(
        self,
        image_bytes: bytes | None,
        image_base64: str | None,
        tool_status: dict[str, str],
    ) -> EvidenceItem | None:
        """Processes visual traffic camera or citizen photo if provided."""
        raw_b64 = image_base64
        if not raw_b64 and image_bytes:
            raw_b64 = base64.b64encode(image_bytes).decode("utf-8")

        if not raw_b64:
            tool_status["image_analysis"] = "NOT_REQUESTED_NO_MEDIA"
            return None

        try:
            res = await self.tool_registry.execute(
                "image_analysis",
                {
                    "image_bytes_base64": raw_b64,
                    "prompt": "Analyze water depth, passable vehicles, and submerged infrastructure.",
                },
            )
            if res.success and res.output:
                tool_status["image_analysis"] = "SUCCESS"
                payload = (
                    res.output.model_dump(mode="json")
                    if hasattr(res.output, "model_dump")
                    else dict(res.output)
                )
                conf = getattr(res.output, "confidence", 0.90)
                return EvidenceItem(
                    source_id="TRAFFIC-CAM-CCTV",
                    source_type="TRAFFIC_CAMERA",
                    confidence=conf,
                    data=payload,
                    observed_at=datetime.now(UTC),
                    verified=True,
                )
            error_msg = res.error.message if res.error else "Execution failed"
            tool_status["image_analysis"] = f"ERROR: {error_msg}"
        except Exception as exc:
            tool_status["image_analysis"] = f"EXCEPTION: {exc}"
            self._logger.error(f"Image analysis tool exception: {exc}")
        return None

    # -------------------------------------------------------------------------
    # Cross-Checking & Contradiction Detection Rules
    # -------------------------------------------------------------------------
    def _cross_check_weather_and_severity(
        self,
        severity: str,
        collected_evidence: list[EvidenceItem],
        verified_facts: list[VerifiedFact],
        contradictions: list[ContradictionItem],
    ) -> None:
        """Cross-checks weather flood levels against reported severity."""
        weather_items = [e for e in collected_evidence if e.source_type == "WATER_SENSOR"]
        if not weather_items:
            return

        w_item = weather_items[0]
        data = w_item.data
        flood_level = str(data.get("flood_level", "")).upper()
        rainfall_rate = float(data.get("rainfall_rate_mm_hr", 0.0))

        # Check for contradiction: Report claims CRITICAL/SEVERE flood, but sensor indicates dry/low
        if severity in ("CRITICAL", "SEVERE") and (flood_level == "LOW" and rainfall_rate < 5.0):
            contradictions.append(
                ContradictionItem(
                    factor="weather",
                    reported_claim=f"Reported {severity} flooding",
                    observed_telemetry=(
                        f"Stream gauge reports dry conditions: flood_level={flood_level}, "
                        f"rainfall_rate={rainfall_rate}mm/hr"
                    ),
                    evidence_id=w_item.evidence_id,
                    severity="SEVERE",
                )
            )
        elif flood_level in ("HIGH", "MED") or rainfall_rate > 25.0:
            verified_facts.append(
                VerifiedFact(
                    claim=(
                        f"Elevated meteorological flood surge confirmed: flood_level={flood_level}, "
                        f"rainfall_rate={rainfall_rate}mm/hr"
                    ),
                    evidence_ids=[w_item.evidence_id],
                    source_types=["WATER_SENSOR"],
                    confidence=w_item.confidence,
                )
            )

    def _cross_check_incident_reports(
        self,
        landmark: str | None,
        collected_evidence: list[EvidenceItem],
        verified_facts: list[VerifiedFact],
        contradictions: list[ContradictionItem],
        unverified_claims: list[str],
        missing_info: list[str],
    ) -> None:
        """Corroborates localized citizen reports and highway summaries."""
        rep_items = [e for e in collected_evidence if e.source_type == "CITIZEN_REPORT"]
        if not rep_items:
            return

        rep = rep_items[0]
        data = rep.data
        total_reports = int(data.get("total_reports", 0))
        summary = str(data.get("summary", ""))

        if total_reports == 0:
            unverified_claims.append("Zero corroborating citizen reports in 5km radius")
            missing_info.append("citizen_field_corroboration")
        else:
            verified_facts.append(
                VerifiedFact(
                    claim=(
                        f"Corroborated by {total_reports} independent citizen/field reports. "
                        f"Summary: {summary[:120]}"
                    ),
                    evidence_ids=[rep.evidence_id],
                    source_types=["CITIZEN_REPORT"],
                    confidence=rep.confidence,
                )
            )

    def _cross_check_geolocation(
        self,
        reported_lat: float,
        reported_lon: float,
        collected_evidence: list[EvidenceItem],
        verified_facts: list[VerifiedFact],
        contradictions: list[ContradictionItem],
    ) -> None:
        """Validates reported landmark and coordinates."""
        geo_items = [
            e for e in collected_evidence if e.source_type == "RADAR" and "resolved_name" in e.data
        ]
        if not geo_items:
            return

        g_item = geo_items[0]
        data = g_item.data
        res_name = data.get("resolved_name", "Target Facility")
        g_lat = float(data.get("latitude", reported_lat))
        g_lon = float(data.get("longitude", reported_lon))

        # Check coordinate drift: difference > 0.15 degrees (~16 km)
        lat_diff = abs(reported_lat - g_lat)
        lon_diff = abs(reported_lon - g_lon)
        if lat_diff > 0.15 or lon_diff > 0.15:
            contradictions.append(
                ContradictionItem(
                    factor="location",
                    reported_claim=f"Coordinates ({reported_lat:.4f}, {reported_lon:.4f})",
                    observed_telemetry=f"Facility '{res_name}' resolved at ({g_lat:.4f}, {g_lon:.4f})",
                    evidence_id=g_item.evidence_id,
                    severity="SEVERE",
                )
            )
        else:
            verified_facts.append(
                VerifiedFact(
                    claim=f"Spatial location verified: '{res_name}' at ({g_lat:.4f}, {g_lon:.4f})",
                    evidence_ids=[g_item.evidence_id],
                    source_types=["RADAR"],
                    confidence=g_item.confidence,
                )
            )

    def _cross_check_image_evidence(
        self,
        severity: str,
        collected_evidence: list[EvidenceItem],
        verified_facts: list[VerifiedFact],
        contradictions: list[ContradictionItem],
    ) -> None:
        """Cross-checks visual traffic camera analysis against reported severity."""
        img_items = [e for e in collected_evidence if e.source_type == "TRAFFIC_CAMERA"]
        if not img_items:
            return

        img = img_items[0]
        data = img.data
        depth = float(data.get("water_depth_estimate_inches", 0.0))
        impassable = bool(data.get("vehicles_impassable", False))

        if severity in ("CRITICAL", "SEVERE") and depth < 2.0 and not impassable:
            contradictions.append(
                ContradictionItem(
                    factor="visual_passability",
                    reported_claim="Roadway impassable due to deep flooding",
                    observed_telemetry=f"Camera analysis indicates dry/minor water depth: {depth} in",
                    evidence_id=img.evidence_id,
                    severity="SEVERE",
                )
            )
        else:
            verified_facts.append(
                VerifiedFact(
                    claim=f"Visual flood depth confirmed: {depth:.1f} inches, vehicle impassability: {impassable}",
                    evidence_ids=[img.evidence_id],
                    source_types=["TRAFFIC_CAMERA"],
                    confidence=img.confidence,
                )
            )

    # -------------------------------------------------------------------------
    # Deterministic Confidence Calculation Policy
    # -------------------------------------------------------------------------
    def _calculate_confidence(
        self,
        evidence_items: list[EvidenceItem],
        contradictions: list[ContradictionItem],
        missing_info: list[str],
        stale_detected: bool,
    ) -> float:
        """Deterministic policy formula for multi-source confidence calculation."""
        if not evidence_items:
            return 0.0

        SOURCE_WEIGHTS = {
            "WATER_SENSOR": 0.35,
            "CITIZEN_REPORT": 0.30,
            "TRAFFIC_CAMERA": 0.20,
            "RADAR": 0.15,
        }

        total_weight_queried = 0.0
        accumulated_score = 0.0
        for item in evidence_items:
            weight = SOURCE_WEIGHTS.get(item.source_type, 0.20)
            total_weight_queried += weight
            freshness = 0.6 if stale_detected else 1.0
            accumulated_score += weight * item.confidence * freshness

        weighted_reliability = (
            (accumulated_score / total_weight_queried) if total_weight_queried > 0 else 0.0
        )

        # Scale based on independent source count
        count = len(evidence_items)
        if count == 1:
            base_confidence = min(0.50, weighted_reliability * 0.50)
        elif count == 2:
            base_confidence = min(0.80, weighted_reliability * 0.78)
        else:
            base_confidence = min(1.0, 0.80 + (weighted_reliability * 0.18))

        # Contradiction penalties
        severe_count = sum(1 for c in contradictions if c.severity == "SEVERE")
        mod_count = sum(1 for c in contradictions if c.severity == "MODERATE")
        contra_penalty = (severe_count * 0.35) + (mod_count * 0.15)

        # Missing operational info penalty
        missing_penalty = min(0.15, len(missing_info) * 0.03)

        final_score = max(0.0, min(1.0, base_confidence - contra_penalty - missing_penalty))
        return round(final_score, 2)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _extract_incident_context(
        self,
        incident: IncidentData | PerceptionOutput | dict[str, Any],
        perception_output: PerceptionOutput | None,
    ) -> tuple[str, float, float, str | None, str, str, list[str]]:
        """Safely normalizes incident identifier, coordinates, landmark, and text."""
        inc_id = "inc-synthetic-01"
        lat = 8.5241
        lon = 76.9366
        landmark: str | None = "City Hospital"
        severity = "CRITICAL"
        raw_text = ""
        missing_info: list[str] = []

        if perception_output:
            inc_id = perception_output.incident_id
            severity = perception_output.severity
            raw_text = perception_output.raw_report
            missing_info = list(perception_output.missing_information)
            if perception_output.location.latitude is not None:
                lat = perception_output.location.latitude
            if perception_output.location.longitude is not None:
                lon = perception_output.location.longitude
            if perception_output.location.primary_landmark:
                landmark = perception_output.location.primary_landmark
        elif isinstance(incident, PerceptionOutput):
            inc_id = incident.incident_id
            severity = incident.severity
            raw_text = incident.raw_report
            missing_info = list(incident.missing_information)
            if incident.location.latitude is not None:
                lat = incident.location.latitude
            if incident.location.longitude is not None:
                lon = incident.location.longitude
            if incident.location.primary_landmark:
                landmark = incident.location.primary_landmark
        elif isinstance(incident, IncidentData):
            inc_id = incident.incident_id
            severity = incident.severity
            raw_text = incident.description
            lat = incident.location.latitude
            lon = incident.location.longitude
            landmark = incident.location.address_reference
            missing_info = incident.raw_payload.get("missing_information", [])
        elif isinstance(incident, dict):
            inc_id = incident.get("incident_id", "inc-synthetic-01")
            severity = incident.get("severity", "CRITICAL")
            raw_text = (
                incident.get("description")
                or incident.get("raw_report")
                or incident.get("raw_user_report")
                or ""
            )
            loc = incident.get("location")
            if isinstance(loc, dict):
                lat = float(loc.get("latitude", 8.5241))
                lon = float(loc.get("longitude", 76.9366))
                landmark = loc.get("primary_landmark") or loc.get("address_reference")
            missing_info = incident.get("missing_information", [])

        if not raw_text:
            raw_text = f"Reported flooding near {landmark or 'hospital'}."

        return inc_id, lat, lon, landmark, severity, raw_text, missing_info

    def _synthesize_summary(
        self,
        status: str,
        confidence: float,
        source_count: int,
        verified_facts: list[VerifiedFact],
        contradictions: list[ContradictionItem],
        unverified_claims: list[str],
        tool_status: dict[str, str],
    ) -> str:
        """Builds a deterministic, transparent evidence summary without LLM hallucination."""
        lines = [
            f"Multi-source verification outcome: {status} (confidence: {confidence:.2f}, threshold: {self.confidence_threshold:.2f}).",
            f"Queried {source_count} independent empirical source(s).",
        ]

        if verified_facts:
            facts_str = "; ".join(f.claim for f in verified_facts)
            lines.append(f"Corroborated Facts: {facts_str}.")

        if contradictions:
            contra_str = "; ".join(
                f"{c.factor.upper()}: {c.observed_telemetry}" for c in contradictions
            )
            lines.append(f"Detected Discrepancies: {contra_str}.")

        if unverified_claims:
            lines.append(f"Unverified: {'; '.join(unverified_claims)}.")

        failures = [k for k, v in tool_status.items() if v.startswith(("ERROR", "EXCEPTION"))]
        if failures:
            lines.append(f"Partial telemetry failures recorded: {', '.join(failures)}.")

        return " ".join(lines)
