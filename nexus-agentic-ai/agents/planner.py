import uuid
from typing import Any

from agents.base import BaseAgent
from orchestration.risk_gate import DeterministicRiskGate
from orchestration.state import ActionItem


class PlanSynthesisAgent(BaseAgent):
    """Synthesizes structured operational action plans across municipal agencies."""

    def __init__(self) -> None:
        super().__init__(
            name="PlanSynthesisAgent",
            role="Operational action plan synthesis and sequencing",
        )
        self.risk_gate = DeterministicRiskGate()

    async def process(self, state: Any) -> dict[str, Any]:
        """Synthesize response plan DAG and evaluate deterministic safety policy."""
        route_id = state.get("selected_primary_route_id", "ROUTE-BETA-SAFE")
        iteration = state.get("replan_iteration_count", 0)

        # Plan v1 vs Plan v2 (replanned route)
        if "GAMMA" in route_id or iteration > 0:
            vms_msg = "METRO & INDUSTRIAL FLOODED - EMS DETOUR VIA NORTH RIDGE"
            ambulance_orders = (
                "Dispatch Medic-Rescue 44 via Route Gamma (North Ridge Overpass) to St. Jude ER."
            )
            hospital_note = "INBOUND_VIA_NORTH_RIDGE_GATE"
        else:
            vms_msg = "METRO PKWY FLOODED - EMS DETOUR VIA INDUSTRIAL"
            ambulance_orders = (
                "Dispatch Medic-Rescue 44 via Route Beta (Industrial Way) to St. Jude ER."
            )
            hospital_note = "INBOUND_VIA_REAR_BAY"

        actions: list[ActionItem] = [
            ActionItem(
                action_id=f"act-vms-{uuid.uuid4().hex[:6]}",
                sequence_order=1,
                action_type="UPDATE_VARIABLE_MESSAGE_SIGN",
                target_entity="Sign VMS-I80-04 (Westbound)",
                risk_tier="TIER_2_LOW",
                description=f"Update digital highway signage: {vms_msg}",
                execution_payload={"sign_id": "VMS-I80-04", "message": vms_msg},
                approval_required=False,
                approval_status="AUTO_APPROVED",
            ),
            ActionItem(
                action_id=f"act-close-{uuid.uuid4().hex[:6]}",
                sequence_order=2,
                action_type="CLOSE_PRIMARY_ARTERY",
                target_entity="Metropolitan Parkway (Mile 4.0 to 6.2)",
                risk_tier="TIER_4_HIGH",
                description="Deploy physical barriers to close Metropolitan Parkway and halt civilian traffic.",
                execution_payload={
                    "closure_start": "Mile 4.0",
                    "closure_end": "Mile 6.2",
                    "divert_to": route_id,
                },
                approval_required=True,
                approval_status="PENDING",
            ),
            ActionItem(
                action_id=f"act-reserve-{uuid.uuid4().hex[:6]}",
                sequence_order=3,
                action_type="RESERVE_AMBULANCE",
                target_entity="Medic-Rescue 44",
                risk_tier="TIER_3_MEDIUM",
                description="Reserve and assign Medic-Rescue 44 (Ford F-550 High-Water 4x4) for St. Jude trauma corridor.",
                execution_payload={
                    "unit_id": "MEDIC-RESCUE-44",
                    "assigned_corridor": route_id,
                    "orders": ambulance_orders,
                },
                approval_required=True,
                approval_status="PENDING",
            ),
            ActionItem(
                action_id=f"act-notify-{uuid.uuid4().hex[:6]}",
                sequence_order=4,
                action_type="NOTIFY_HOSPITAL_TRAUMA_BAY",
                target_entity="St. Jude Hospital ER Charge Nurse",
                risk_tier="TIER_2_LOW",
                description="Notify trauma intake that ambulances are inbound via designated corridor.",
                execution_payload={
                    "facility_id": "FAC-HOSP-STJUDE",
                    "alert": hospital_note,
                },
                approval_required=False,
                approval_status="AUTO_APPROVED",
            ),
        ]

        # Deterministic Risk Evaluation - cannot be bypassed by LLM
        evaluated_actions, requires_approval = self.risk_gate.evaluate_plan(actions)

        new_status = "AWAITING_APPROVAL" if requires_approval else "PLAN_SYNTHESIZED"

        return {
            "current_status": new_status,
            "action_plan": evaluated_actions,
            "requires_human_approval": requires_approval,
        }
