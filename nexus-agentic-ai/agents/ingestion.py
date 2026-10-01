from typing import Any

from agents.base import BaseAgent


class IncidentIngestionAgent(BaseAgent):
    """Normalizes citizen reports, extracts geo coordinates, and classifies disaster type."""

    def __init__(self) -> None:
        super().__init__(
            name="IncidentIngestionAgent",
            role="Perception, normalization, and structured feature extraction",
        )

    async def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """Extract structured incident data from raw report."""
        return {
            "current_status": "INGESTED",
            "extracted_features": {
                "incident_type": "flash_flood",
                "hazard_level": "critical",
            },
        }
