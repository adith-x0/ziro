from typing import Any, Literal

from pydantic import BaseModel

from tools.base import BaseTool


class ResourceQueryInput(BaseModel):
    resource_type: Literal[
        "high_water_ambulance",
        "mobile_water_pump",
        "traffic_barrier_crew",
        "sandbag_unit",
    ]
    near_latitude: float
    near_longitude: float
    max_distance_km: float = 15.0


class ResourceInventoryItem(BaseModel):
    unit_id: str
    unit_name: str
    resource_type: str
    station_id: str
    distance_km: float
    estimated_eta_minutes: float
    status: Literal["available", "dispatched", "maintenance"]


class ResourceInventoryTool(BaseTool):
    """Tool to query municipal depot inventory for specialized emergency units."""

    def __init__(self) -> None:
        super().__init__(
            name="resource_inventory_tool",
            description=(
                "Queries regional fleet depots for available high-clearance units and equipment."
            ),
        )

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        query = ResourceQueryInput(**kwargs)
        items: list[ResourceInventoryItem] = [
            ResourceInventoryItem(
                unit_id="MEDIC-RESCUE-44",
                unit_name="High-Water Rescue Unit 44 (Ford F-550 4x4)",
                resource_type=query.resource_type,
                station_id="STATION-12-DOWNTOWN",
                distance_km=3.8,
                estimated_eta_minutes=8.0,
                status="available",
            ),
            ResourceInventoryItem(
                unit_id="BARRIER-CREW-02",
                unit_name="Public Works Rapid Barrier Unit 2",
                resource_type=query.resource_type,
                station_id="DEPOT-CENTRAL",
                distance_km=5.2,
                estimated_eta_minutes=12.0,
                status="available",
            ),
        ]
        return {"resources": [item.model_dump(mode="json") for item in items]}
