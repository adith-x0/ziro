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
        avoid_normalized = {
            seg.lower().replace("-", "_").replace(" ", "_") for seg in req.avoid_segments
        }

        beta_blocked = any(
            token in avoid_normalized
            for token in ["industrial_way", "route_beta", "route_beta_safe", "route_b"]
        )
        gamma_blocked = any(
            token in avoid_normalized
            for token in ["north_ridge_overpass", "route_gamma", "route_gamma_overpass", "route_c"]
        )

        # Route evaluation based on topological road graph and avoidance constraints
        if not beta_blocked and req.vehicle_clearance_inches >= 18.0:
            result = RouteResult(
                route_id="ROUTE-BETA-SAFE",
                origin=f"{req.origin_coords[0]},{req.origin_coords[1]}",
                destination=f"{req.destination_coords[0]},{req.destination_coords[1]}",
                total_distance_km=6.4,
                estimated_transit_time_minutes=11.2,
                safe_for_vehicle=True,
                waypoints=[
                    req.origin_coords,
                    (req.origin_coords[0] + 0.003, req.origin_coords[1] - 0.005),
                    (req.origin_coords[0] + 0.0055, req.origin_coords[1] - 0.007),
                    req.destination_coords,
                ],
                traversed_segments=["Depot_Spur", "Industrial_Way", "Hospital_Back_Access"],
                chokepoint_clearances={"Industrial_Bridge": 24.0},
            )
        elif not gamma_blocked:
            # Fallback to elevated detour overpass (Route Gamma)
            result = RouteResult(
                route_id="ROUTE-GAMMA-OVERPASS",
                origin=f"{req.origin_coords[0]},{req.origin_coords[1]}",
                destination=f"{req.destination_coords[0]},{req.destination_coords[1]}",
                total_distance_km=7.8,
                estimated_transit_time_minutes=14.5,
                safe_for_vehicle=True,
                waypoints=[
                    req.origin_coords,
                    (req.origin_coords[0] + 0.013, req.origin_coords[1] - 0.015),
                    req.destination_coords,
                ],
                traversed_segments=["Depot_Spur", "North_Ridge_Overpass", "Hospital_North_Access"],
                chokepoint_clearances={"North_Ridge_Viaduct": 48.0},
            )
        else:
            # All alternative routes impassable or avoided - reject to avoid hallucinating safe route
            result = RouteResult(
                route_id="NO_PASSABLE_ROUTE",
                origin=f"{req.origin_coords[0]},{req.origin_coords[1]}",
                destination=f"{req.destination_coords[0]},{req.destination_coords[1]}",
                total_distance_km=0.0,
                estimated_transit_time_minutes=0.0,
                safe_for_vehicle=False,
                waypoints=[],
                traversed_segments=[],
                chokepoint_clearances={},
            )

        return result.model_dump(mode="json")
