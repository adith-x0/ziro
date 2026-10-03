"""NEXUS Perception Agent.

First-contact ingestion, parsing, multimodal perception, and structured triage of real-world emergency reports.
Powered by Google Gemini via the modern google-genai SDK (genai.Client) with strict Pydantic v2 validation.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from agents.base import BaseAgent
from agents.schemas import IncidentData, IncidentLocation

try:
    from app.config import settings
except ImportError:
    try:
        from backend.app.config import settings  # type: ignore[no-redef]
    except ImportError:
        settings = None  # type: ignore[assignment]


# -----------------------------------------------------------------------------
# Perception Exceptions
# -----------------------------------------------------------------------------
class PerceptionError(Exception):
    """Base exception for NEXUS Perception Agent operations."""


class PerceptionAPIError(PerceptionError):
    """Raised when Gemini API encounters fatal errors or exhausts retry limits."""


class PerceptionValidationError(PerceptionError):
    """Raised when Gemini response fails Pydantic schema validation."""


class PerceptionConfigurationError(PerceptionError):
    """Raised when credentials or models are misconfigured and fallback is disabled."""


# -----------------------------------------------------------------------------
# Structured Pydantic Schemas for Perception Output
# -----------------------------------------------------------------------------
class LocationDetails(BaseModel):
    """Extracted geographic and spatial landmark details."""

    model_config = ConfigDict(populate_by_name=True)

    raw_location: str = Field(
        ..., description="Raw text segment describing the location in the report"
    )
    primary_landmark: str | None = Field(
        default=None,
        description="Primary facility, hospital, or landmark identified (e.g. City Hospital)",
    )
    specific_zone: str | None = Field(
        default=None,
        description="Sub-zone, wing, or access point (e.g. emergency entrance, north access road)",
    )
    city: str | None = Field(
        default=None, description="City, municipality, or district if specified"
    )
    latitude: float | None = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Latitude in decimal degrees if explicitly stated",
    )
    longitude: float | None = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Longitude in decimal degrees if explicitly stated",
    )
    address_reference: str | None = Field(
        default=None, description="Street address, avenue, or intersection reference"
    )


class TemporalDetails(BaseModel):
    """Extracted time markers and temporal indicators."""

    model_config = ConfigDict(populate_by_name=True)

    extracted_time_str: str | None = Field(
        default=None, description="Explicit time mentioned in report (e.g. '10:32 AM')"
    )
    is_ongoing: bool = Field(
        default=True,
        description="Whether the incident represents an active ongoing condition",
    )
    relative_time_indicator: str | None = Field(
        default=None,
        description="Temporal descriptors such as 'just reported', 'morning', 'recent'",
    )


class IncidentClassification(BaseModel):
    """Detailed category breakdown and hazard descriptors."""

    model_config = ConfigDict(populate_by_name=True)

    primary_type: Literal[
        "FLOODING",
        "INFRASTRUCTURE_FAILURE",
        "ROAD_BLOCKAGE",
        "HAZMAT_SPILL",
        "MASS_CASUALTY",
        "MEDICAL_EMERGENCY",
        "POWER_OUTAGE",
        "OTHER",
    ] = Field(..., description="High-level category of emergency incident")
    secondary_tags: list[str] = Field(
        default_factory=list,
        description="Descriptive tags (e.g. ['waterlogging', 'submerged_road', 'access_blocked'])",
    )


class PerceptionOutput(BaseModel):
    """Standardized, validated output contract produced by NEXUS Perception Agent."""

    model_config = ConfigDict(populate_by_name=True)

    incident_id: str = Field(
        default_factory=lambda: f"inc-{uuid.uuid4().hex[:8]}",
        description="Unique identifier for the perceived incident",
    )
    incident_type: str = Field(..., description="Canonical incident type string, e.g. FLOODING")
    classification: IncidentClassification = Field(
        ..., description="Primary classification and secondary tags"
    )
    severity: Literal["MINOR", "MODERATE", "SEVERE", "CRITICAL"] = Field(
        ...,
        description="Severity category based on life-safety and infrastructure impact",
    )
    location: LocationDetails = Field(
        ..., description="Extracted geographic and spatial landmark details"
    )
    time: TemporalDetails = Field(..., description="Extracted temporal markers and ongoing status")
    impact_summary: str = Field(
        ...,
        description="Concise assessment of immediate operational impact or threat",
    )
    affected_infrastructure: list[str] = Field(
        default_factory=list,
        description="Critical facilities or infrastructure threatened or blocked",
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Crucial emergency parameters missing from report (e.g. exact_coordinates, water_depth, casualty_count)",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Model confidence score for the extraction fidelity (0.0 to 1.0)",
    )
    has_image: bool = Field(
        default=False, description="Whether image evidence accompanied the report"
    )
    image_analysis: str | None = Field(
        default=None, description="Summary of visual analysis if image was provided"
    )
    raw_report: str = Field(..., description="Original raw report text processed by the agent")
    is_simulation: bool = Field(
        default=True,
        description="Strictly true for all NEXUS mock/simulation processing",
    )
    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when perception extraction completed",
    )

    def to_incident_data(
        self,
        default_latitude: float = 8.5241,
        default_longitude: float = 76.9366,
    ) -> IncidentData:
        """Converts perception output to standardized NEXUS IncidentData for state pipelines."""
        lat = self.location.latitude if self.location.latitude is not None else default_latitude
        lon = self.location.longitude if self.location.longitude is not None else default_longitude

        category = self.classification.primary_type
        if category not in (
            "FLOODING",
            "INFRASTRUCTURE_FAILURE",
            "SUPPLY_CHAIN_DISRUPTION",
            "HAZMAT_SPILL",
            "MASS_CASUALTY",
            "OTHER",
        ):
            category = "OTHER"

        return IncidentData(
            incident_id=self.incident_id,
            description=self.raw_report,
            category=category,  # type: ignore[arg-type]
            severity=self.severity,
            location=IncidentLocation(
                latitude=lat,
                longitude=lon,
                address_reference=self.location.primary_landmark or self.location.raw_location,
            ),
            reported_at=self.extracted_at,
            reporter_type="CITIZEN",
            affected_radius_meters=500.0,
            raw_payload={
                "impact_summary": self.impact_summary,
                "missing_information": self.missing_information,
                "confidence": self.confidence,
                "affected_infrastructure": self.affected_infrastructure,
                "time": self.time.model_dump(),
                "has_image": self.has_image,
                "image_analysis": self.image_analysis,
                "is_simulation": self.is_simulation,
            },
        )


# -----------------------------------------------------------------------------
# System Prompt
# -----------------------------------------------------------------------------
PERCEPTION_SYSTEM_PROMPT = """You are the NEXUS Perception & Triage Agent, an expert multimodal operational agent in an autonomous real-world emergency response network.

Your mission is to perform first-contact ingestion, parsing, feature extraction, and triage on raw incident reports (text and optional imagery) with extreme precision and zero hallucination.

CORE EXTRACTION RULES:
1. INCIDENT TYPE CLASSIFICATION:
   - Identify the primary disaster/hazard category: FLOODING, INFRASTRUCTURE_FAILURE, ROAD_BLOCKAGE, HAZMAT_SPILL, MASS_CASUALTY, MEDICAL_EMERGENCY, POWER_OUTAGE, or OTHER.
   - Extract secondary hazard tags (e.g. ['waterlogging', 'submerged_corridor', 'hospital_access_cut']).

2. SEVERITY ASSESSMENT:
   - CRITICAL: Direct threat to life, vital medical facilities cut off (e.g. hospital emergency ingress blocked, ambulances blocked), mass casualties imminent.
   - SEVERE: Major arterial corridors submerged, deep water impassable to standard vehicles, critical utilities disrupted.
   - MODERATE: Localized road inundation, passable with caution, property damage risk without immediate life hazard.
   - MINOR: Nuisance ponding, minor gutter overflow, minimal operational delay.

3. SPATIAL EXTRACTION (NEVER FABRICATE COORDINATES):
   - Extract landmarks (e.g. 'City Hospital', 'Memorial Trauma Center').
   - Extract specific access points or zones (e.g. 'emergency entrance', 'ambulance bay', 'Route B crossing').
   - DO NOT fabricate GPS coordinates (latitude/longitude) unless explicitly provided in text or metadata. Leave as null if absent.

4. TEMPORAL EXTRACTION:
   - Extract exact timestamps or time strings mentioned (e.g. '10:32 AM').
   - Determine if the hazard is active/ongoing.

5. IDENTIFY MISSING INFORMATION (MANDATORY):
   - Emergency response coordinators require specific missing operational data to dispatch assets safely.
   - You MUST enumerate missing variables in `missing_information`, such as:
     * 'exact_gps_coordinates' (if no explicit lat/lon provided)
     * 'water_depth_inches' (if depth is not measured/stated)
     * 'vehicle_passability_metrics' (if vehicle clearance threshold is not stated)
     * 'casualty_count' (if victim injuries or trapped counts are unmentioned)
     * 'obstruction_spread_meters' (if length of flooded street is unknown)

6. CONFIDENCE CALIBRATION:
   - Score confidence between 0.0 and 1.0:
     * 0.85 - 1.0: Explicit landmark, explicit time, clear severity, high detail.
     * 0.65 - 0.84: Good context but missing exact metrics or precise coordinates.
     * Below 0.65: Vague location, ambiguous hazard, or second-hand rumor.

7. OUTPUT SCHEMA:
   - Output valid JSON conforming strictly to the requested schema.
   - Always flag `is_simulation: true`.
"""


# -----------------------------------------------------------------------------
# NEXUS Perception Agent Implementation
# -----------------------------------------------------------------------------
class PerceptionAgent(BaseAgent):
    """Multimodal incident perception, feature extraction, and triage agent using Google GenAI SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client: genai.Client | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        fallback_on_missing_key: bool = True,
    ) -> None:
        super().__init__(
            name="PerceptionAgent",
            role="Multimodal incident perception, feature extraction, and triage",
        )
        # 1. Credentials & Configuration
        if api_key is not None:
            resolved_key = api_key
        else:
            resolved_key = (
                os.getenv("GEMINI_API_KEY") or (settings.gemini_api_key if settings else "") or ""
            )
        self.api_key = resolved_key.strip()
        self.model_name = (
            model or (settings.gemini_flash_model if settings else "") or "gemini-2.5-flash"
        )
        self.max_retries = max(1, max_retries)
        self.retry_delay = max(0.1, retry_delay)
        self.fallback_on_missing_key = fallback_on_missing_key
        self._logger = logging.getLogger("nexus.agents.perception")

        # 2. Dependency Injection for GenAI Client
        if client is not None:
            self._client: genai.Client | None = client
        elif self.api_key:
            self._client = genai.Client(api_key=self.api_key)
        else:
            self._client = None

    async def perceive(
        self,
        text_report: str,
        image_bytes: bytes | None = None,
        image_base64: str | None = None,
        image_mime_type: str = "image/jpeg",
        image_metadata: dict[str, Any] | None = None,
    ) -> PerceptionOutput:
        """Processes raw report text and optional imagery into a validated PerceptionOutput."""
        if not text_report or not text_report.strip():
            raise PerceptionError("text_report must be a non-empty string.")

        # If no client and fallback enabled, run deterministic perception
        if self._client is None:
            if self.fallback_on_missing_key:
                self._logger.info(
                    "[PerceptionAgent] No Gemini client/API key detected. Executing deterministic simulation triage."
                )
                return self._deterministic_fallback_perception(
                    text_report=text_report,
                    image_bytes=image_bytes,
                    image_base64=image_base64,
                    image_metadata=image_metadata,
                )
            raise PerceptionConfigurationError(
                "Gemini API key is required but not provided, and fallback is disabled."
            )

        # Build multimodal contents list
        contents: list[Any] = []
        user_prompt = f"Analyze the following incident report:\n\n{text_report.strip()}"
        if image_metadata:
            user_prompt += f"\n\nAttached Image Metadata: {json.dumps(image_metadata)}"
        contents.append(user_prompt)

        # Attach image bytes if provided
        raw_image_data: bytes | None = image_bytes
        if raw_image_data is None and image_base64:
            try:
                raw_image_data = base64.b64decode(image_base64)
            except Exception as b64_err:
                self._logger.warning(f"Failed to decode base64 image data: {b64_err}")

        if raw_image_data is not None:
            image_part = types.Part.from_bytes(
                data=raw_image_data,
                mime_type=image_mime_type,
            )
            contents.append(image_part)

        # Call Gemini with retry policy
        response = await self._call_gemini_with_retry(contents)

        # Parse and validate response text with Pydantic
        raw_text = response.text or ""
        clean_text = self._clean_json_markdown(raw_text)

        try:
            parsed_output = PerceptionOutput.model_validate_json(clean_text)
        except ValidationError as val_err:
            self._logger.error(
                f"Perception output failed Pydantic validation: {val_err}. Raw text: {raw_text}"
            )
            raise PerceptionValidationError(
                f"LLM output failed Pydantic schema validation: {val_err}"
            ) from val_err

        # Post-validation safety guardrails
        parsed_output.raw_report = text_report
        parsed_output.has_image = raw_image_data is not None
        self._enforce_missing_info_guardrails(parsed_output, text_report)

        return parsed_output

    async def process(self, state: Any) -> dict[str, Any]:
        """LangGraph state node interface for perception pipeline."""
        raw_report = ""
        image_bytes = None
        image_metadata = None

        if isinstance(state, dict):
            raw_report = (
                state.get("raw_report")
                or state.get("raw_user_report")
                or state.get("description")
                or ""
            )
            image_bytes = state.get("image_bytes")
            image_metadata = state.get("image_metadata")
            if not raw_report and "incident" in state:
                inc = state["incident"]
                if isinstance(inc, dict):
                    raw_report = inc.get("description", "")
                elif hasattr(inc, "description"):
                    raw_report = inc.description
        elif hasattr(state, "description"):
            raw_report = getattr(state, "description", "")

        if not raw_report:
            raw_report = "Heavy waterlogging reported near City Hospital. Ambulances unable to access entrance."

        perception = await self.perceive(
            text_report=raw_report,
            image_bytes=image_bytes,
            image_metadata=image_metadata,
        )

        incident_data = perception.to_incident_data()
        return {
            "current_status": "PERCEIVED",
            "perception_output": perception.model_dump(),
            "incident": incident_data,
        }

    # -------------------------------------------------------------------------
    # Internal Helpers: Retry, Cleaning, Fallback
    # -------------------------------------------------------------------------
    async def _call_gemini_with_retry(
        self,
        contents: list[Any],
    ) -> types.GenerateContentResponse:
        """Invokes Gemini API with exponential backoff on transient errors."""
        assert self._client is not None

        def _is_retryable(exc: BaseException) -> bool:
            if isinstance(exc, (TimeoutError, asyncio.TimeoutError, ConnectionError)):
                return True
            if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
                return True
            if isinstance(exc, errors.ServerError):
                return True
            if isinstance(exc, errors.APIError):
                code = getattr(exc, "code", None)
                if code in (429, 500, 502, 503, 504):
                    return True
            return False

        retrier = AsyncRetrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=self.retry_delay, min=self.retry_delay, max=10.0),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )

        try:
            async for attempt in retrier:
                with attempt:
                    try:
                        self._logger.info(
                            f"Invoking Gemini ({self.model_name}) perception, attempt {attempt.retry_state.attempt_number}..."
                        )
                        return await self._client.aio.models.generate_content(
                            model=self.model_name,
                            contents=contents,
                            config=types.GenerateContentConfig(
                                system_instruction=PERCEPTION_SYSTEM_PROMPT,
                                temperature=0.1,
                                response_mime_type="application/json",
                                response_schema=PerceptionOutput,
                            ),
                        )
                    except Exception as exc:
                        if _is_retryable(exc):
                            self._logger.warning(
                                f"Transient Gemini failure on attempt {attempt.retry_state.attempt_number}: {exc}. Retrying..."
                            )
                        else:
                            self._logger.error(f"Non-retryable Gemini error encountered: {exc}")
                        raise
        except Exception as exc:
            raise PerceptionAPIError(
                f"Failed to query Gemini perception model after {self.max_retries} attempts: {exc}"
            ) from exc

        raise PerceptionAPIError("Gemini invocation completed without response.")

    @staticmethod
    def _clean_json_markdown(text: str) -> str:
        """Strips markdown code fences from response text if present."""
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return cleaned.strip()

    @staticmethod
    def _enforce_missing_info_guardrails(output: PerceptionOutput, raw_text: str) -> None:
        """Ensures essential missing operational parameters are flagged."""
        lower_raw = raw_text.lower()

        # 1. Exact coordinates
        if (
            output.location.latitude is None or output.location.longitude is None
        ) and "exact_gps_coordinates" not in output.missing_information:
            output.missing_information.append("exact_gps_coordinates")

        # 2. Water depth measurement
        depth_indicators = ["inch", "meter", "cm", "feet", "depth"]
        if not any(ind in lower_raw for ind in depth_indicators) and not any(
            "depth" in m.lower() for m in output.missing_information
        ):
            output.missing_information.append("water_depth_measurement")

        # 3. Vehicle clearance passability
        if (
            "clearance" not in lower_raw
            and "passable" not in lower_raw
            and not any("passability" in m.lower() for m in output.missing_information)
        ):
            output.missing_information.append("vehicle_passability_metrics")

    def _deterministic_fallback_perception(
        self,
        text_report: str,
        image_bytes: bytes | None = None,
        image_base64: str | None = None,
        image_metadata: dict[str, Any] | None = None,
    ) -> PerceptionOutput:
        """Deterministic simulation extractor for local offline and credential-less execution."""
        lower = text_report.lower()

        # 1. Incident Type
        if any(w in lower for w in ("flood", "waterlog", "inundat", "submerg")):
            primary_type = "FLOODING"
            secondary_tags = ["waterlogging", "submerged_road"]
        elif any(w in lower for w in ("bridge", "collapse", "road broken", "sinkhole")):
            primary_type = "INFRASTRUCTURE_FAILURE"
            secondary_tags = ["structural_damage"]
        else:
            primary_type = "OTHER"
            secondary_tags = ["unclassified_hazard"]

        # 2. Severity
        severity: Literal["MINOR", "MODERATE", "SEVERE", "CRITICAL"]
        if any(
            w in lower
            for w in (
                "hospital",
                "emergency entrance",
                "unable to reach",
                "ambulance",
                "critical",
                "fatal",
            )
        ):
            severity = "CRITICAL"
        elif any(w in lower for w in ("heavy", "severe", "blocked", "trapped")):
            severity = "SEVERE"
        elif any(w in lower for w in ("moderate", "rising")):
            severity = "MODERATE"
        else:
            severity = "MINOR"

        # 3. Landmark & Location
        primary_landmark = None
        if "city hospital" in lower:
            primary_landmark = "City Hospital"
        elif "hospital" in lower:
            primary_landmark = "Regional Hospital"

        specific_zone = None
        if "emergency entrance" in lower:
            specific_zone = "emergency entrance"
        elif "access road" in lower:
            specific_zone = "access road"

        # 4. Time
        time_match = re.search(r"\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\b", text_report)
        extracted_time_str = time_match.group(0) if time_match else None

        # 5. Missing Information
        missing = [
            "exact_gps_coordinates",
            "water_depth_measurement",
            "vehicle_passability_metrics",
            "casualty_count",
        ]

        # 6. Infrastructure & Impact
        affected_infra = []
        if primary_landmark:
            affected_infra.append(primary_landmark)
        if specific_zone:
            affected_infra.append(f"{primary_landmark or 'Facility'} {specific_zone}")

        impact_summary = (
            "Ambulance access severely impeded by localized water accumulation; "
            "emergency ingress potentially compromised."
        )

        has_img = (
            (image_bytes is not None) or (image_base64 is not None) or (image_metadata is not None)
        )
        img_analysis = (
            "Simulation image analysis confirms standing water exceeding standard passenger vehicle clearance."
            if has_img
            else None
        )

        return PerceptionOutput(
            incident_type=primary_type,
            classification=IncidentClassification(
                primary_type=primary_type,  # type: ignore[arg-type]
                secondary_tags=secondary_tags,
            ),
            severity=severity,
            location=LocationDetails(
                raw_location=text_report[:60],
                primary_landmark=primary_landmark,
                specific_zone=specific_zone,
                address_reference="Emergency Access Corridor",
                latitude=None,
                longitude=None,
            ),
            time=TemporalDetails(
                extracted_time_str=extracted_time_str,
                is_ongoing=True,
                relative_time_indicator="active",
            ),
            impact_summary=impact_summary,
            affected_infrastructure=affected_infra,
            missing_information=missing,
            confidence=0.88,
            has_image=has_img,
            image_analysis=img_analysis,
            raw_report=text_report,
            is_simulation=True,
        )
