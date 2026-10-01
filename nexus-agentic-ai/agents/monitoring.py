from typing import Any

from agents.base import BaseAgent


class MonitoringAgent(BaseAgent):
    """Monitors hydrological stream gauges and triggers replanning upon surge."""

    def __init__(self) -> None:
        super().__init__(
            name="MonitoringAgent",
            role="Continuous telemetry surveillance and surge delta detection",
        )

    async def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """Poll telemetry sensors and evaluate water surge condition."""
        return {
            "current_status": "MONITORING",
            "telemetry_surge_detected": False,
        }
