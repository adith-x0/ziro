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
        all_inventory: list[ResourceInventoryItem] = [
            ResourceInventoryItem(
                unit_id="MEDIC-RESCUE-44",
                unit_name="Medic-Rescue 44 (Ford F-550 High-Water 4x4)",
                resource_type="high_water_ambulance",
                station_id="DEPOT-CENTRAL",
                distance_km=3.8,
                estimated_eta_minutes=8.0,
                status="available",
            ),
            ResourceInventoryItem(
                unit_id="MEDIC-RESCUE-12",
                unit_name="Medic-Rescue 12 (Freightliner M2 Severe-Duty)",
                resource_type="high_water_ambulance",
                station_id="DEPOT-CENTRAL",
                distance_km=4.2,
                estimated_eta_minutes=9.5,
                status="available",
            ),
            ResourceInventoryItem(
                unit_id="BARRIER-CREW-01",
                unit_name="Public Works Rapid Barrier Unit 1",
                resource_type="traffic_barrier_crew",
                station_id="DEPOT-CENTRAL",
                distance_km=5.2,
                estimated_eta_minutes=12.0,
                status="available",
            ),
            ResourceInventoryItem(
                unit_id="PUMP-FLOOD-03",
                unit_name="Mobile High-Volume Flood Pump 03 (5000 GPM)",
                resource_type="mobile_water_pump",
                station_id="DEPOT-CENTRAL",
                distance_km=4.0,
                estimated_eta_minutes=10.0,
                status="available",
            ),
            ResourceInventoryItem(
                unit_id="SANDBAG-UNIT-01",
                unit_name="Emergency Sandbag Staging Unit 1",
                resource_type="sandbag_unit",
                station_id="DEPOT-EAST",
                distance_km=6.1,
                estimated_eta_minutes=15.0,
                status="available",
            ),
        ]
        # Strictly filter by requested resource type to prevent fabricated resources
        matched = [
            item
            for item in all_inventory
            if item.resource_type == query.resource_type
            and item.distance_km <= query.max_distance_km
        ]
        return {"resources": [item.model_dump(mode="json") for item in matched]}
