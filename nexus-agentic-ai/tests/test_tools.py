import pytest

from tools.infrastructure_signage import InfrastructureSignageTool
from tools.resource_inventory import ResourceInventoryTool
from tools.routing_engine import RoutingEngineTool
from tools.simulated_dispatch import SimulatedDispatchTool
from tools.traffic_camera import TrafficCameraTool
from tools.weather_sensor import WeatherSensorTool


@pytest.mark.asyncio
async def test_weather_sensor_tool():
    """Verify WeatherSensorTool returns valid reading and measures latency."""
    tool = WeatherSensorTool()
    result = await tool.execute_with_timing(latitude=37.7749, longitude=-122.4194)
    assert result["status"] == "success"
    assert result["tool_name"] == "weather_sensor_tool"
    assert "execution_time_ms" in result
    assert result["data"]["is_flooding"] is True
    assert result["data"]["current_water_level_inches"] > 24.0


@pytest.mark.asyncio
async def test_traffic_camera_tool():
    """Verify TrafficCameraTool execution."""
    tool = TrafficCameraTool()
    result = await tool.execute_with_timing(
        corridor_name="Metropolitan Parkway", latitude=37.7749, longitude=-122.4194
    )
    assert result["status"] == "success"
    assert result["data"]["passable_by_sedan"] is False
    assert result["data"]["passable_by_high_clearance_ambulance"] is True


@pytest.mark.asyncio
async def test_routing_engine_tool():
    """Verify RoutingEngineTool computes safe route."""
    tool = RoutingEngineTool()
    result = await tool.execute_with_timing(
        origin_coords=(37.768, -122.41),
        destination_coords=(37.776, -122.421),
        vehicle_clearance_inches=24.0,
    )
    assert result["status"] == "success"
    assert result["data"]["safe_for_vehicle"] is True
    assert len(result["data"]["waypoints"]) >= 2


@pytest.mark.asyncio
async def test_resource_inventory_tool():
    """Verify ResourceInventoryTool queries available units."""
    tool = ResourceInventoryTool()
    result = await tool.execute_with_timing(
        resource_type="high_water_ambulance",
        near_latitude=37.7749,
        near_longitude=-122.4194,
    )
    assert result["status"] == "success"
    assert len(result["data"]["resources"]) > 0


@pytest.mark.asyncio
async def test_simulated_dispatch_tool():
    """Verify SimulatedDispatchTool returns tracking token."""
    tool = SimulatedDispatchTool()
    result = await tool.execute_with_timing(
        unit_id="MEDIC-RESCUE-44",
        incident_id="inc-100",
        destination="St. Jude Hospital",
        target_route_id="ROUTE-BETA-SAFE",
        operational_orders="Rendezvous at ER trauma bay",
    )
    assert result["status"] == "success"
    assert result["data"]["status"] == "en_route"
    assert "tracking_token" in result["data"]


@pytest.mark.asyncio
async def test_infrastructure_signage_tool():
    """Verify InfrastructureSignageTool updates VMS sign."""
    tool = InfrastructureSignageTool()
    result = await tool.execute_with_timing(
        sign_id="VMS-I80-04",
        headline="METRO PKWY FLOODED",
        sub_message="USE INDUSTRIAL WAY",
        action_recommendation="EMS ONLY HIGH CLEARANCE",
    )
    assert result["status"] == "success"
    assert result["data"]["status"] == "active"
