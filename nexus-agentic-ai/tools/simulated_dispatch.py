import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from tools.base import BaseTool


class DispatchCommand(BaseModel):
    unit_id: str
    incident_id: str
    destination: str
    target_route_id: str
    operational_orders: str


class DispatchReceipt(BaseModel):
    dispatch_id: str
    unit_id: str
    status: Literal["en_route", "acknowledged", "failed"]
    timestamp: datetime
    tracking_token: str


class SimulatedDispatchTool(BaseTool):
    """Actuator tool that dispatches simulated emergency units."""

    def __init__(self) -> None:
        super().__init__(
            name="simulated_dispatch_tool",
            description=(
                "Transmits dispatch orders to simulated field units and receives tracking receipt."
            ),
        )

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        cmd = DispatchCommand(**kwargs)
        receipt = DispatchReceipt(
            dispatch_id=f"dsp-{uuid.uuid4().hex[:8]}",
            unit_id=cmd.unit_id,
            status="en_route",
            timestamp=datetime.now(UTC),
            tracking_token=f"trk-{uuid.uuid4().hex[:12]}",
        )
        return receipt.model_dump(mode="json")
