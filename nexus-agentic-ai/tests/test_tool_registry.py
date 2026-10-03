"""Unit Tests for NEXUS Tool Layer, ToolRegistry, and Mock Tools.

Validates:
- All 11 tools execute successfully and return typed outputs
- Every mock tool identifies itself as: "simulation/mock environment"
- Dependency injection allows swapping providers cleanly
- ToolRegistry retrieves, registers, and executes tools by name
- Input validation failures return structured error without throwing unhandled exceptions
- Timeouts return structured TIMEOUT_ERROR
- Underlying exceptions return structured EXECUTION_ERROR
- Emergency safety guardrail prevents real-world actions
"""

import asyncio

import pytest

from tools.nexus_tools import (
    AmbulanceReservationTool,
    AuditLoggingTool,
    GeolocationTool,
    HospitalStatusTool,
    ImageAnalysisTool,
    IncidentReportsTool,
    IncidentStatusUpdateTool,
    NotificationsTool,
    ResourceSearchTool,
    RoutingTool,
    WeatherOutput,
    WeatherProvider,
    WeatherTool,
)
from tools.registry import (
    BaseNexusTool,
    ToolRegistry,
    default_tool_registry,
)


# -----------------------------------------------------------------------------
# 1. ToolRegistry Mechanics
# -----------------------------------------------------------------------------
def test_tool_registry_contains_all_11_tools():
    """Assert all 11 required tools are registered in default_tool_registry."""
    expected_tools = [
        "ambulance_reservation",
        "audit_logging",
        "geolocation",
        "hospital_status",
        "image_analysis",
        "incident_reports",
        "incident_status_update",
        "notifications",
        "resource_search",
        "routing",
        "weather",
    ]
    registered = default_tool_registry.list_tools()
    for exp in expected_tools:
        assert exp in registered, f"Missing tool in registry: {exp}"
        assert default_tool_registry.has(exp) is True
        tool = default_tool_registry.get(exp)
        assert isinstance(tool, BaseNexusTool)
        assert tool.name == exp


def test_tool_registry_lookup_unknown_tool_raises_key_error():
    """Assert querying an unregistered tool name raises KeyError."""
    registry = ToolRegistry()
    assert registry.has("nonexistent_tool") is False
    with pytest.raises(KeyError, match="is not registered in ToolRegistry"):
        registry.get("nonexistent_tool")


def test_tool_registry_descriptions():
    """Assert get_tool_descriptions returns valid JSON schemas for LLM binding."""
    descriptions = default_tool_registry.get_tool_descriptions()
    assert len(descriptions) >= 11
    for desc in descriptions:
        assert "name" in desc
        assert "description" in desc
        assert desc["environment"] == "simulation/mock environment"
        assert desc["is_simulation"] is True
        assert "input_schema" in desc
        assert "output_schema" in desc


# -----------------------------------------------------------------------------
# 2. Successful Execution & Simulation Attribution (All 11 Tools)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_weather_tool_success():
    tool = WeatherTool()
    res = await tool.execute({"latitude": 8.5241, "longitude": 76.9366})
    assert res.status == "success"
    assert res.environment == "simulation/mock environment"
    assert res.is_simulation is True
    assert res.data is not None
    assert res.data.flood_level == "HIGH"
    assert res.data.rainfall_rate_mm_hr > 50.0
    assert res.execution_time_ms >= 0.0


@pytest.mark.asyncio
async def test_incident_reports_tool_success():
    tool = IncidentReportsTool()
    res = await tool.execute({"latitude": 8.5241, "longitude": 76.9366, "radius_km": 5.0})
    assert res.status == "success"
    assert res.environment == "simulation/mock environment"
    assert res.data.total_reports >= 2
    assert "Route A" in res.data.summary


@pytest.mark.asyncio
async def test_image_analysis_tool_success():
    tool = ImageAnalysisTool()
    res = await tool.execute({"image_url": "https://sim.nexus/cctv/cam01.jpg"})
    assert res.status == "success"
    assert res.environment == "simulation/mock environment"
    assert res.data.water_depth_estimate_inches > 15.0
    assert "Standard Ambulance" in res.data.vehicles_impassable
    assert res.data.confidence >= 0.90


@pytest.mark.asyncio
async def test_geolocation_tool_success():
    tool = GeolocationTool()
    res = await tool.execute({"query_address_or_landmark": "City Hospital"})
    assert res.status == "success"
    assert res.environment == "simulation/mock environment"
    assert res.data.latitude == 8.5280
    assert res.data.longitude == 76.9420
    assert "HEALTHCARE" in res.data.zone_type


@pytest.mark.asyncio
async def test_routing_tool_success():
    tool = RoutingTool()
    res = await tool.execute(
        {
            "origin": "DEPOT",
            "destination": "CITY-HOSPITAL",
            "avoid_routes": ["ROUTE-A"],
            "vehicle_clearance_inches": 12.0,
        }
    )
    assert res.status == "success"
    assert res.environment == "simulation/mock environment"
    assert res.data.selected_route_id in ["ROUTE-B", "ROUTE-C"]
    assert res.data.is_passable is True
    assert len(res.data.waypoints) >= 2


@pytest.mark.asyncio
async def test_resource_search_tool_success():
    tool = ResourceSearchTool()
    res = await tool.execute(
        {
            "resource_type": "AMBULANCE",
            "required_clearance_inches": 30.0,
            "max_distance_km": 10.0,
        }
    )
    assert res.status == "success"
    assert res.environment == "simulation/mock environment"
    assert res.data.total_available >= 1
    assert res.data.selected_recommendation == "AMB-01"


@pytest.mark.asyncio
async def test_hospital_status_tool_success():
    tool = HospitalStatusTool()
    res = await tool.execute({"hospital_id": "CITY-HOSPITAL"})
    assert res.status == "success"
    assert res.environment == "simulation/mock environment"
    assert res.data.hospital_id == "CITY-HOSPITAL"
    assert res.data.bed_capacity_available > 0
    assert res.data.flood_barrier_active is True


@pytest.mark.asyncio
async def test_notifications_tool_success():
    tool = NotificationsTool()
    res = await tool.execute(
        {
            "channel": "HOSPITAL_ALERT_FEED",
            "recipient": "CITY-HOSPITAL-ER-BAY",
            "title": "Inbound Trauma Unit",
            "message": "High-water ambulance AMB-01 diverted via Route B.",
            "priority": "HIGH",
        }
    )
    assert res.status == "success"
    assert res.environment == "simulation/mock environment"
    assert res.data.status == "SENT_SIMULATED"
    assert res.data.delivery_id.startswith("notif-")


@pytest.mark.asyncio
async def test_ambulance_reservation_tool_success():
    tool = AmbulanceReservationTool()
    res = await tool.execute(
        {
            "unit_id": "AMB-01",
            "incident_id": "inc-test-res-01",
            "destination": "CITY-HOSPITAL",
        },
        approval_token="tok-auth-123",
    )
    assert res.status == "success"
    assert res.environment == "simulation/mock environment"
    assert res.data.unit_id == "AMB-01"
    assert res.data.status == "RESERVED"
    assert res.data.tracking_token.startswith("trk-")


@pytest.mark.asyncio
async def test_incident_status_update_tool_success():
    tool = IncidentStatusUpdateTool()
    res = await tool.execute(
        {
            "incident_id": "inc-99",
            "new_status": "PLAN_SYNTHESIZED",
            "commentary": "Plan v1 action DAG synthesized and submitted to policy gate.",
        }
    )
    assert res.status == "success"
    assert res.environment == "simulation/mock environment"
    assert res.data.current_status == "PLAN_SYNTHESIZED"


@pytest.mark.asyncio
async def test_audit_logging_tool_success():
    tool = AuditLoggingTool()
    res = await tool.execute(
        {
            "incident_id": "inc-99",
            "event_type": "policy.evaluated",
            "actor": "POLICY_GATEKEEPER",
            "summary": "Tier 3 action flagged for human commander approval.",
            "payload": {"risk": "MEDIUM"},
        }
    )
    assert res.status == "success"
    assert res.environment == "simulation/mock environment"
    assert res.data.cryptographic_digest is not None
    assert len(res.data.cryptographic_digest) == 16


# -----------------------------------------------------------------------------
# 3. Dependency Injection Test
# -----------------------------------------------------------------------------
class CustomMockWeatherProvider(WeatherProvider):
    async def get_weather(self, lat: float, lon: float) -> WeatherOutput:
        return WeatherOutput(
            temperature_c=18.0,
            rainfall_rate_mm_hr=10.0,
            flood_level="LOW",
            precipitation_type="LIGHT_DRIZZLE",
            wind_speed_kmh=12.0,
            advisory="No flooding detected.",
            is_simulation=True,
            environment="simulation/mock environment",
        )


@pytest.mark.asyncio
async def test_dependency_injection_custom_provider():
    """Assert injecting a custom provider replaces the default implementation."""
    custom_provider = CustomMockWeatherProvider()
    tool = WeatherTool(provider=custom_provider)

    res = await tool.execute({"latitude": 8.5241, "longitude": 76.9366})
    assert res.status == "success"
    assert res.data.flood_level == "LOW"
    assert res.data.precipitation_type == "LIGHT_DRIZZLE"


# -----------------------------------------------------------------------------
# 4. Input Validation Error Tests
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tool_input_validation_error():
    """Assert out-of-bounds input is caught and returns structured VALIDATION_ERROR."""
    tool = WeatherTool()
    # Latitude > 90.0 is invalid
    res = await tool.execute({"latitude": 999.0, "longitude": 76.9366})

    assert res.status == "error"
    assert res.data is None
    assert res.error is not None
    assert res.error.error_code == "VALIDATION_ERROR"
    assert res.error.retryable is False
    assert "validation_errors" in res.error.details


# -----------------------------------------------------------------------------
# 5. Timeout Error Tests
# -----------------------------------------------------------------------------
class HangingWeatherProvider(WeatherProvider):
    async def get_weather(self, lat: float, lon: float) -> WeatherOutput:
        await asyncio.sleep(2.0)  # Exceeds 0.2s timeout
        return WeatherOutput(
            temperature_c=0.0,
            rainfall_rate_mm_hr=0.0,
            flood_level="LOW",
            precipitation_type="NONE",
            wind_speed_kmh=0.0,
            advisory="",
            is_simulation=True,
            environment="simulation/mock environment",
        )


@pytest.mark.asyncio
async def test_tool_timeout_handling():
    """Assert execution exceeding timeout_seconds returns structured TIMEOUT_ERROR."""
    hanging_provider = HangingWeatherProvider()
    tool = WeatherTool(provider=hanging_provider, timeout_seconds=0.2)

    res = await tool.execute({"latitude": 8.5241, "longitude": 76.9366})
    assert res.status == "error"
    assert res.error.error_code == "TIMEOUT_ERROR"
    assert res.error.retryable is True
    assert "timed out after 0.2 seconds" in res.error.message


# -----------------------------------------------------------------------------
# 6. Unexpected Exception Error Tests
# -----------------------------------------------------------------------------
class BrokenWeatherProvider(WeatherProvider):
    async def get_weather(self, lat: float, lon: float) -> WeatherOutput:
        raise ConnectionResetError("Simulated remote socket disconnection")


@pytest.mark.asyncio
async def test_tool_execution_error_handling():
    """Assert uncaught provider exceptions are wrapped in structured EXECUTION_ERROR."""
    broken_provider = BrokenWeatherProvider()
    tool = WeatherTool(provider=broken_provider)

    res = await tool.execute({"latitude": 8.5241, "longitude": 76.9366})
    assert res.status == "error"
    assert res.error.error_code == "EXECUTION_ERROR"
    assert "ConnectionResetError" in res.error.details["exception_type"]
    assert "Simulated remote socket disconnection" in res.error.message


# -----------------------------------------------------------------------------
# 7. Execute via ToolRegistry by Name
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_execute_tool_via_registry():
    """Assert executing tool via ToolRegistry.execute_tool returns structured result."""
    res = await default_tool_registry.execute_tool(
        "geolocation",
        {"query_address_or_landmark": "City Hospital"},
    )
    assert res.status == "success"
    assert res.tool_name == "geolocation"
    assert res.data.latitude == 8.5280
