from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from tools.base import BaseTool


class TrafficCameraInput(BaseModel):
    corridor_name: str
    latitude: float
    longitude: float


class CameraAnalysisOutput(BaseModel):
    camera_id: str
    corridor: str
    image_url: str
    visual_flood_depth_estimate_inches: float
    passable_by_sedan: bool
    passable_by_high_clearance_ambulance: bool
    congestion_level: Literal["clear", "moderate", "gridlock"]
    timestamp: datetime


class TrafficCameraTool(BaseTool):
    """Tool to analyze CCTV feeds for water depth and passability."""

    def __init__(self) -> None:
        super().__init__(
            name="traffic_camera_tool",
            description=(
                "Retrieves CCTV frame and visual water depth estimate along arterial corridors."
            ),
        )

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        params = TrafficCameraInput(**kwargs)
        analysis = CameraAnalysisOutput(
            camera_id="CAM-METRO-08",
            corridor=params.corridor_name,
            image_url="https://simulated-cctv.nexus-ops.org/cam-metro-08.jpg",
            visual_flood_depth_estimate_inches=28.5,
            passable_by_sedan=False,
            passable_by_high_clearance_ambulance=True,
            congestion_level="gridlock",
            timestamp=datetime.now(UTC),
        )
        return analysis.model_dump(mode="json")
