from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from tools.base import BaseTool


class WeatherSensorInput(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    radius_km: float = Field(default=2.5, ge=0.5, le=10.0)


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

    def __init__(self) -> None:
        super().__init__(
            name="weather_sensor_tool",
            description="Fetches live telemetry from IoT stream gauges and precipitation stations.",
        )

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        _ = WeatherSensorInput(**kwargs)
        # Mock simulated reading near St. Jude Memorial Hospital (River Road station)
        reading = SensorReading(
            sensor_id="SG-RIVER-401",
            sensor_type="stream_gauge",
            current_water_level_inches=32.4,
            flood_stage_threshold_inches=24.0,
            is_flooding=True,
            precipitation_rate_in_per_hr=2.1,
            timestamp=datetime.now(UTC),
        )
        return reading.model_dump(mode="json")
