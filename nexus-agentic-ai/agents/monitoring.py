from typing import Any

from agents.base import BaseAgent
from tools.weather_sensor import WeatherSensorTool


class MonitoringAgent(BaseAgent):
    """Monitors hydrological stream gauges and triggers replanning upon surge."""

    def __init__(self) -> None:
        super().__init__(
            name="MonitoringAgent",
            role="Continuous telemetry surveillance and surge delta detection",
        )
        self.weather_tool = WeatherSensorTool()

    async def process(self, state: Any) -> dict[str, Any]:
        """Poll telemetry sensors along active detour and detect water surge condition."""
        monitored_sensors = state.get("monitored_sensor_ids") or ["SG-INDUSTRIAL-202"]

        # Check telemetry on active route sensor
        reading = await self.weather_tool.run(
            corridor="Industrial Way", sensor_id=monitored_sensors[0]
        )
        water_level = reading.get("current_water_level_inches", 8.5)
        threshold = reading.get("flood_stage_threshold_inches", 20.0)

        # Delta analysis: if water level >= threshold or flooding active
        surge_detected = water_level >= threshold or reading.get("is_flooding", False)

        new_status = "REPLANNING" if surge_detected else "MONITORING"

        return {
            "current_status": new_status,
            "monitored_sensor_ids": monitored_sensors,
            "telemetry_surge_detected": surge_detected,
        }
