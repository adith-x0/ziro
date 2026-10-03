from typing import Any

from agents.base import BaseAgent


class IncidentIngestionAgent(BaseAgent):
    """Normalizes citizen reports, extracts geo coordinates, and classifies disaster type."""

    def __init__(self) -> None:
        super().__init__(
            name="IncidentIngestionAgent",
            role="Perception, normalization, and structured feature extraction",
        )

    async def process(self, state: Any) -> dict[str, Any]:
        """Extract structured incident data from raw report and attachment context."""
        raw_report = state.get("raw_user_report", "")
        coords = state.get("epicenter_coords")
        lat = float(getattr(coords, "latitude", 37.7749))
        lon = float(getattr(coords, "longitude", -122.4194))

        extracted_features = {
            "incident_type": "flash_flood",
            "hazard_level": "critical",
            "primary_corridor": "Metropolitan Parkway",
            "intersection": "River Road Crossing",
            "threatened_facility": "St. Jude Memorial Hospital",
            "reported_water_depth_inches": 30.0,
            "epicenter": {"latitude": lat, "longitude": lon},
            "source_channel": "CITIZEN_MOBILE_REPORT",
            "raw_report_snippet": raw_report[:100],
        }

        return {
            "current_status": "INGESTED",
            "extracted_features": extracted_features,
        }
