from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from tools.base import BaseTool


class WeatherSensorInput(BaseModel):
    latitude: float = Field(default=37.7749, ge=-90.0, le=90.0)
    longitude: float = Field(default=-122.4194, ge=-180.0, le=180.0)
    radius_km: float = Field(default=2.5, ge=0.5, le=10.0)
    sensor_id: str | None = None
    corridor: str | None = None


class SensorReading(BaseModel):
    sensor_id: str
    sensor_type: Literal["stream_gauge", "precipitation_radar", "soil_moisture"]
    current_water_level_inches: float
    flood_stage_threshold_inches: float
    is_flooding: bool
    precipitation_rate_in_per_hr: float
    timestamp: datetime


class WeatherSensorTool(BaseTool):
    """Tool to query IoT stream gauges and precipitation stations."""

    # Active dynamic state registry for simulated physical sensors
    _sensor_registry: dict[str, dict[str, Any]] = {
        "SG-RIVER-401": {
            "sensor_id": "SG-RIVER-401",
            "sensor_type": "stream_gauge",
            "current_water_level_inches": 32.4,
            "flood_stage_threshold_inches": 24.0,
            "is_flooding": True,
            "precipitation_rate_in_per_hr": 2.1,
        },
        "SG-INDUSTRIAL-202": {
            "sensor_id": "SG-INDUSTRIAL-202",
            "sensor_type": "stream_gauge",
            "current_water_level_inches": 8.5,
            "flood_stage_threshold_inches": 20.0,
            "is_flooding": False,
            "precipitation_rate_in_per_hr": 0.4,
        },
        "SG-RIDGE-101": {
            "sensor_id": "SG-RIDGE-101",
            "sensor_type": "stream_gauge",
            "current_water_level_inches": 2.0,
            "flood_stage_threshold_inches": 36.0,
            "is_flooding": False,
            "precipitation_rate_in_per_hr": 0.1,
        },
    }

    def __init__(self) -> None:
        super().__init__(
            name="weather_sensor_tool",
            description="Fetches live telemetry from IoT stream gauges and precipitation stations.",
        )

    @classmethod
    def set_sensor_reading(
        cls, sensor_id: str, water_level_inches: float, precipitation_rate: float = 2.5
    ) -> None:
        """Inject physical sensor change into simulated IoT network."""
        if sensor_id in cls._sensor_registry:
            entry = cls._sensor_registry[sensor_id]
            entry["current_water_level_inches"] = water_level_inches
            entry["precipitation_rate_in_per_hr"] = precipitation_rate
            entry["is_flooding"] = water_level_inches >= entry["flood_stage_threshold_inches"]

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        inp = WeatherSensorInput(**kwargs)
        target_id = inp.sensor_id or "SG-RIVER-401"
        if inp.corridor and "industrial" in inp.corridor.lower():
            target_id = "SG-INDUSTRIAL-202"
        elif inp.corridor and "ridge" in inp.corridor.lower():
            target_id = "SG-RIDGE-101"

        data = self._sensor_registry.get(target_id, self._sensor_registry["SG-RIVER-401"]).copy()
        data["timestamp"] = datetime.now(UTC)

        reading = SensorReading(**data)
        return reading.model_dump(mode="json")
