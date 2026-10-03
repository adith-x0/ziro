from typing import Any

from agents.base import BaseAgent
from orchestration.state import RouteOption
from tools.resource_inventory import ResourceInventoryTool
from tools.routing_engine import RoutingEngineTool


class ResourceRoutingAgent(BaseAgent):
    """Finds specialized rescue vehicles and computes safe non-flooded detour routes."""

    def __init__(self) -> None:
        super().__init__(
            name="ResourceRoutingAgent",
            role="Fleet inventory matching and safe graph route discovery",
        )
        self.inventory_tool = ResourceInventoryTool()
        self.routing_tool = RoutingEngineTool()

    async def process(self, state: Any) -> dict[str, Any]:
        """Discover fleet units and compute safe routing corridors."""
        coords = state.get("epicenter_coords")
        lat = float(getattr(coords, "latitude", 37.7749))
        lon = float(getattr(coords, "longitude", -122.4194))

        # 1. Discover high-clearance ambulances
        fleet_res = await self.inventory_tool.run(
            resource_type="high_water_ambulance",
            near_latitude=lat,
            near_longitude=lon,
            max_distance_km=15.0,
        )
        available_fleet = fleet_res.get("resources", [])

        # 2. Check for route avoidances (e.g. from compromised routes in state)
        avoid_segments = ["Metropolitan_Parkway"]
        for route in state.get("active_routes", []):
            if getattr(route, "is_compromised", False):
                avoid_segments.append(getattr(route, "route_id", ""))
                avoid_segments.append("Industrial_Way")

        # 3. Calculate safe route via routing engine
        depot_coords = (37.7680, -122.4100)
        hospital_coords = (37.7760, -122.4210)
        route_res = await self.routing_tool.run(
            origin_coords=depot_coords,
            destination_coords=hospital_coords,
            vehicle_clearance_inches=34.0,
            avoid_segments=avoid_segments,
        )

        waypoints_list = [list(wp) for wp in route_res.get("waypoints", [])]
        route_option = RouteOption(
            route_id=route_res.get("route_id", "ROUTE-BETA-SAFE"),
            origin="Central Fleet Depot",
            destination="St. Jude Hospital ER Access",
            waypoints=waypoints_list,
            total_distance_km=route_res.get("total_distance_km", 6.4),
            estimated_transit_time_min=route_res.get("estimated_transit_time_minutes", 11.2),
            max_water_clearance_supported_inches=24.0
            if "BETA" in route_res.get("route_id", "")
            else 48.0,
            is_compromised=False,
        )

        return {
            "current_status": "ROUTED",
            "available_fleet": available_fleet,
            "active_routes": [route_option],
            "selected_primary_route_id": route_option.route_id,
        }
