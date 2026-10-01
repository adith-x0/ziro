from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from tools.base import BaseTool


class SignageUpdateInput(BaseModel):
    sign_id: str
    headline: str = Field(..., max_length=24)
    sub_message: str = Field(..., max_length=24)
    action_recommendation: str = Field(..., max_length=32)
    activate_flashing_beacon: bool = True


class SignageUpdateReceipt(BaseModel):
    sign_id: str
    applied_headline: str
    status: Literal["active", "offline"]
    updated_at: datetime


class InfrastructureSignageTool(BaseTool):
    """Actuator tool to update simulated Dynamic Variable Message Signs (VMS)."""

    def __init__(self) -> None:
        super().__init__(
            name="infrastructure_signage_tool",
            description="Updates simulated road corridor variable message signs with detours.",
        )

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        payload = SignageUpdateInput(**kwargs)
        receipt = SignageUpdateReceipt(
            sign_id=payload.sign_id,
            applied_headline=payload.headline,
            status="active",
            updated_at=datetime.now(UTC),
        )
        return receipt.model_dump(mode="json")
