"""Unit and Mocked LLM Tests for NEXUS Perception Agent."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import errors, types
from pydantic import ValidationError

from agents.perception import (
    IncidentClassification,
    LocationDetails,
    PerceptionAgent,
    PerceptionAPIError,
    PerceptionConfigurationError,
    PerceptionOutput,
    PerceptionValidationError,
    TemporalDetails,
)
from agents.schemas import IncidentData


# -----------------------------------------------------------------------------
# Fixtures & Sample Payloads
# -----------------------------------------------------------------------------
@pytest.fixture
def hospital_flooding_sample_json() -> str:
    """Realistic Gemini JSON response conforming to PerceptionOutput schema."""
    return json.dumps(
        {
            "incident_id": "inc-hospital-01",
            "incident_type": "FLOODING",
            "classification": {
                "primary_type": "FLOODING",
                "secondary_tags": [
                    "waterlogging",
                    "submerged_road",
                    "access_blocked",
                ],
            },
            "severity": "CRITICAL",
            "location": {
                "raw_location": "near City Hospital",
                "primary_landmark": "City Hospital",
                "specific_zone": "emergency entrance",
                "city": "Metropolis",
                "latitude": None,
                "longitude": None,
                "address_reference": "Hospital Ingress Corridor",
            },
            "time": {
                "extracted_time_str": "10:32 AM",
                "is_ongoing": True,
                "relative_time_indicator": "morning active",
            },
            "impact_summary": (
                "Ambulance access severely impeded by localized waterlogging; "
                "emergency entrance unreachable for standard units."
            ),
            "affected_infrastructure": [
                "City Hospital",
                "City Hospital Emergency Entrance",
            ],
            "missing_information": [
                "exact_gps_coordinates",
                "water_depth_inches",
                "vehicle_passability_metrics",
                "casualty_count",
            ],
            "confidence": 0.94,
            "has_image": False,
            "image_analysis": None,
            "raw_report": (
                "Heavy waterlogging reported near City Hospital at 10:32 AM. "
                "Ambulances may be unable to reach the emergency entrance."
            ),
            "is_simulation": True,
            "extracted_at": "2026-10-01T10:32:00Z",
        }
    )


def create_mock_genai_client(return_text: str) -> MagicMock:
    """Creates a mock google-genai Client returning specified text."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = return_text

    mock_client.aio = MagicMock()
    mock_client.aio.models = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    return mock_client


# -----------------------------------------------------------------------------
# 1. Schema Validation Unit Tests
# -----------------------------------------------------------------------------
def test_perception_schema_validation_valid():
    """Verify PerceptionOutput instantiation with valid strict fields."""
    output = PerceptionOutput(
        incident_type="FLOODING",
        classification=IncidentClassification(
            primary_type="FLOODING",
            secondary_tags=["waterlogging"],
        ),
        severity="SEVERE",
        location=LocationDetails(
            raw_location="City Hospital",
            primary_landmark="City Hospital",
            latitude=8.5241,
            longitude=76.9366,
        ),
        time=TemporalDetails(
            extracted_time_str="10:32 AM",
            is_ongoing=True,
        ),
        impact_summary="Flooding blocking emergency lane",
        missing_information=["water_depth_inches"],
        confidence=0.91,
        raw_report="Report text",
    )
    assert output.confidence == 0.91
    assert output.severity == "SEVERE"
    assert output.location.latitude == 8.5241
    assert output.is_simulation is True


def test_perception_schema_validation_rejects_out_of_bounds_confidence():
    """Confidence score must be constrained between 0.0 and 1.0."""
    with pytest.raises(ValidationError):
        PerceptionOutput(
            incident_type="FLOODING",
            classification=IncidentClassification(primary_type="FLOODING"),
            severity="SEVERE",
            location=LocationDetails(raw_location="X"),
            time=TemporalDetails(),
            impact_summary="summary",
            confidence=1.5,  # Invalid: > 1.0
            raw_report="test",
        )


def test_perception_schema_validation_rejects_invalid_severity():
    """Severity must be one of MINOR, MODERATE, SEVERE, CRITICAL."""
    with pytest.raises(ValidationError):
        PerceptionOutput(
            incident_type="FLOODING",
            classification=IncidentClassification(primary_type="FLOODING"),
            severity="CATASTROPHIC",  # Invalid literal
            location=LocationDetails(raw_location="X"),
            time=TemporalDetails(),
            impact_summary="summary",
            confidence=0.8,
            raw_report="test",
        )


# -----------------------------------------------------------------------------
# 2. Example Hospital Flooding Input (Mocked LLM)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_example_hospital_flooding_input_mocked_llm(
    hospital_flooding_sample_json: str,
):
    """Test standard hackathon scenario prompt with mocked Gemini client."""
    mock_client = create_mock_genai_client(hospital_flooding_sample_json)

    agent = PerceptionAgent(
        api_key="mock-api-key",
        model="gemini-2.5-flash",
        client=mock_client,
    )

    prompt = (
        "Heavy waterlogging reported near City Hospital at 10:32 AM. "
        "Ambulances may be unable to reach the emergency entrance."
    )

    result = await agent.perceive(prompt)

    # Verify structured extractions
    assert result.incident_type == "FLOODING"
    assert result.classification.primary_type == "FLOODING"
    assert result.severity == "CRITICAL"
    assert result.location.primary_landmark == "City Hospital"
    assert result.location.specific_zone == "emergency entrance"
    assert result.time.extracted_time_str == "10:32 AM"
    assert result.time.is_ongoing is True
    assert result.confidence >= 0.85
    assert result.is_simulation is True

    # Verify missing information identified
    assert "exact_gps_coordinates" in result.missing_information
    assert "water_depth_inches" in result.missing_information

    # Verify Gemini was invoked with correct config and system prompt
    call_args = mock_client.aio.models.generate_content.call_args
    assert call_args is not None
    config = call_args.kwargs.get("config")
    assert config is not None
    assert config.response_mime_type == "application/json"
    assert config.response_schema == PerceptionOutput


# -----------------------------------------------------------------------------
# 3. Multimodal Image Ingestion (Mocked LLM)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_multimodal_image_input_mocked_llm(
    hospital_flooding_sample_json: str,
):
    """Test that image bytes and metadata are formatted into Gemini parts."""
    mock_client = create_mock_genai_client(hospital_flooding_sample_json)
    agent = PerceptionAgent(client=mock_client)

    fake_image_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    image_meta = {"camera_id": "CAM-HOSP-01", "resolution": "1920x1080"}

    result = await agent.perceive(
        text_report="Water level rising near ambulance depot.",
        image_bytes=fake_image_bytes,
        image_mime_type="image/png",
        image_metadata=image_meta,
    )

    assert result.has_image is True

    # Check that generate_content received both prompt and types.Part
    call_args = mock_client.aio.models.generate_content.call_args
    contents = call_args.kwargs.get("contents")
    assert len(contents) == 2
    assert "Attached Image Metadata" in contents[0]
    assert isinstance(contents[1], types.Part)


# -----------------------------------------------------------------------------
# 4. Missing Information Guardrails
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_information_guardrail_injection():
    """Agent ensures essential missing fields are added even if LLM omitted them."""
    # LLM returns payload with no missing_information listed
    incomplete_json = json.dumps(
        {
            "incident_id": "inc-002",
            "incident_type": "FLOODING",
            "classification": {"primary_type": "FLOODING", "secondary_tags": []},
            "severity": "MODERATE",
            "location": {
                "raw_location": "Main Street",
                "latitude": None,
                "longitude": None,
            },
            "time": {"extracted_time_str": None, "is_ongoing": True},
            "impact_summary": "Puddle on road",
            "affected_infrastructure": [],
            "missing_information": [],  # Empty from LLM
            "confidence": 0.70,
            "has_image": False,
            "raw_report": "Water on Main Street.",
            "is_simulation": True,
            "extracted_at": "2026-10-01T12:00:00Z",
        }
    )

    mock_client = create_mock_genai_client(incomplete_json)
    agent = PerceptionAgent(client=mock_client)

    result = await agent.perceive("Water on Main Street.")

    # Guardrails must have injected missing coordinates and depth
    assert "exact_gps_coordinates" in result.missing_information
    assert "water_depth_measurement" in result.missing_information


# -----------------------------------------------------------------------------
# 5. Retry Policy on Transient Network / API Failures
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_retry_policy_recovers_from_transient_failure(
    hospital_flooding_sample_json: str,
):
    """Verifies that tenacity retries on transient errors and succeeds."""
    mock_client = MagicMock()
    mock_client.aio = MagicMock()
    mock_client.aio.models = MagicMock()

    mock_success = MagicMock()
    mock_success.text = hospital_flooding_sample_json

    # 1st call: transient 503 ServerError
    # 2nd call: success
    transient_error = errors.ServerError(503, "Service Temporarily Unavailable")
    mock_client.aio.models.generate_content = AsyncMock(side_effect=[transient_error, mock_success])

    agent = PerceptionAgent(
        client=mock_client,
        max_retries=3,
        retry_delay=0.05,  # Fast for test
    )

    result = await agent.perceive("Heavy waterlogging reported near City Hospital.")
    assert result.incident_type == "FLOODING"
    assert mock_client.aio.models.generate_content.call_count == 2


@pytest.mark.asyncio
async def test_retry_policy_exhaustion_raises_perception_api_error():
    """Verifies that PerceptionAPIError is raised after exhausting retries."""
    mock_client = MagicMock()
    mock_client.aio = MagicMock()
    mock_client.aio.models = MagicMock()

    server_error = errors.ServerError(500, "Internal Server Error")
    mock_client.aio.models.generate_content = AsyncMock(side_effect=server_error)

    agent = PerceptionAgent(
        client=mock_client,
        max_retries=2,
        retry_delay=0.01,
    )

    with pytest.raises(PerceptionAPIError) as exc_info:
        await agent.perceive("Flooding near hospital.")
    assert "after 2 attempts" in str(exc_info.value)


# -----------------------------------------------------------------------------
# 6. Malformed JSON & Markdown Code Fence Handling
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_markdown_code_fence_cleaning(hospital_flooding_sample_json: str):
    """Verifies agent cleanly strips ```json code fences if returned by LLM."""
    fenced_text = f"```json\n{hospital_flooding_sample_json}\n```"
    mock_client = create_mock_genai_client(fenced_text)

    agent = PerceptionAgent(client=mock_client)
    result = await agent.perceive("Flooding near City Hospital.")
    assert result.incident_type == "FLOODING"


@pytest.mark.asyncio
async def test_malformed_llm_json_raises_perception_validation_error():
    """Verifies that non-JSON or schema-violating output raises PerceptionValidationError."""
    mock_client = create_mock_genai_client("Not a valid json response from LLM")
    agent = PerceptionAgent(client=mock_client)

    with pytest.raises(PerceptionValidationError):
        await agent.perceive("Flooding near hospital.")


# -----------------------------------------------------------------------------
# 7. BaseAgent & LangGraph State Integration
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_process_method_integrates_with_base_agent(
    hospital_flooding_sample_json: str,
):
    """Verifies process(state) conforms to LangGraph state transitions."""
    mock_client = create_mock_genai_client(hospital_flooding_sample_json)
    agent = PerceptionAgent(client=mock_client)

    state_input = {
        "raw_user_report": (
            "Heavy waterlogging reported near City Hospital at 10:32 AM. "
            "Ambulances may be unable to reach the emergency entrance."
        )
    }

    result_state = await agent.process(state_input)

    assert result_state["current_status"] == "PERCEIVED"
    assert "perception_output" in result_state
    assert isinstance(result_state["incident"], IncidentData)
    assert result_state["incident"].severity == "CRITICAL"
    assert result_state["incident"].location.address_reference == "City Hospital"


# -----------------------------------------------------------------------------
# 8. IncidentData Conversion
# -----------------------------------------------------------------------------
def test_to_incident_data_conversion(hospital_flooding_sample_json: str):
    """Verifies conversion from PerceptionOutput to IncidentData."""
    output = PerceptionOutput.model_validate_json(hospital_flooding_sample_json)
    inc_data = output.to_incident_data(default_latitude=8.5241, default_longitude=76.9366)

    assert isinstance(inc_data, IncidentData)
    assert inc_data.category == "FLOODING"
    assert inc_data.severity == "CRITICAL"
    assert inc_data.location.latitude == 8.5241
    assert inc_data.location.longitude == 76.9366
    assert inc_data.raw_payload["confidence"] == 0.94


# -----------------------------------------------------------------------------
# 9. Deterministic Fallback Mode (Offline / No Key)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_deterministic_fallback_when_no_api_key():
    """Verifies fallback parser activates when no key or client is provided."""
    agent = PerceptionAgent(
        api_key="",
        client=None,
        fallback_on_missing_key=True,
    )

    prompt = (
        "Heavy waterlogging reported near City Hospital at 10:32 AM. "
        "Ambulances may be unable to reach the emergency entrance."
    )

    result = await agent.perceive(prompt)

    assert result.incident_type == "FLOODING"
    assert result.severity == "CRITICAL"
    assert result.location.primary_landmark == "City Hospital"
    assert result.location.specific_zone == "emergency entrance"
    assert result.time.extracted_time_str == "10:32 AM"
    assert "exact_gps_coordinates" in result.missing_information
    assert result.confidence > 0.8
    assert result.is_simulation is True


@pytest.mark.asyncio
async def test_configuration_error_when_fallback_disabled_and_no_key():
    """Verifies PerceptionConfigurationError is raised when fallback is disabled."""
    agent = PerceptionAgent(
        api_key="",
        client=None,
        fallback_on_missing_key=False,
    )

    with pytest.raises(PerceptionConfigurationError):
        await agent.perceive("Flooding near hospital.")


# -----------------------------------------------------------------------------
# 10. Environment API Key Resolution
# -----------------------------------------------------------------------------
def test_gemini_client_reads_api_key_from_environment(monkeypatch):
    """Confirm PerceptionAgent automatically reads GEMINI_API_KEY from environment."""
    test_key = "AIzaSyTestMockEnvKeyForVerification12345"
    monkeypatch.setenv("GEMINI_API_KEY", test_key)

    agent = PerceptionAgent(client=None)
    assert agent.api_key == test_key
    assert agent._client is not None


# -----------------------------------------------------------------------------
# 11. Live Gemini API Integration (Optional/Environment Dependent)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_live_gemini_api_integration_if_key_present():
    """Verify live Gemini API integration when GEMINI_API_KEY is present in environment."""
    env_key = os.getenv("GEMINI_API_KEY", "")
    if not env_key or not env_key.strip():
        pytest.skip("GEMINI_API_KEY not set in environment.")

    agent = PerceptionAgent(
        api_key=env_key,
        model="gemini-3.8-flash",
        client=None,
    )
    prompt = (
        "Heavy waterlogging reported near City Hospital at 10:32 AM. "
        "Ambulances may be unable to reach the emergency entrance."
    )
    try:
        result = await agent.perceive(prompt)
        assert result.incident_type is not None
        assert result.severity in ("CRITICAL", "SEVERE", "MODERATE", "MINOR")
        assert result.confidence >= 0.0
        assert result.is_simulation is True
    except (PerceptionAPIError, errors.ServerError, errors.ClientError) as err:
        pytest.skip(f"Live Gemini API temporarily unavailable or quota-limited: {err}")
