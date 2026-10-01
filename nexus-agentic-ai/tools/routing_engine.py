from typing import Any

from pydantic import BaseModel, Field

from tools.base import BaseTool


class RouteRequest(BaseModel):
    origin_coords: tuple[float, float]
    destination_coords: tuple[float, float]
    vehicle_clearance_inches: float
    avoid_segments: list[str] = Field(default_factory=list)


class RouteResult(BaseModel):
    route_id: str
    origin: str
    destination: str
    total_distance_km: float
    estimated_transit_time_minutes: float
    safe_for_vehicle: bool
    waypoints: list[tuple[float, float]]
    traversed_segments: list[str]
    chokepoint_clearances: dict[str, float]


class RoutingEngineTool(BaseTool):
    """Tool to calculate safe topological routes avoiding flooded road segments."""

    def __init__(self) -> None:
        super().__init__(
            name="safe_routing_engine",
            description="Calculates shortest safe emergency route bypassing flooded nodes.",
        )

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        req = RouteRequest(**kwargs)
        # Mock calculation: selects Route Beta (Industrial Corridor bypass)
        result = RouteResult(
            route_id="ROUTE-BETA-SAFE",
            origin=f"{req.origin_coords[0]},{req.origin_coords[1]}",
            destination=f"{req.destination_coords[0]},{req.destination_coords[1]}",
            total_distance_km=6.4,
            estimated_transit_time_minutes=11.5,
            safe_for_vehicle=True,
            waypoints=[
                req.origin_coords,
                (req.origin_coords[0] + 0.01, req.origin_coords[1] - 0.02),
                req.destination_coords,
            ],
            traversed_segments=["Depot_Spur", "Industrial_Way", "Hospital_Back_Access"],
            chokepoint_clearances={"Industrial_Bridge": 36.0},
        )
        return result.model_dump(mode="json")
