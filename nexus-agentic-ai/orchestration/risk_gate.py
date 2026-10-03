from enum import StrEnum

from orchestration.state import ActionItem


class RiskTier(StrEnum):
    TIER_1_AUTO = "TIER_1_AUTO"
    TIER_2_LOW = "TIER_2_LOW"
    TIER_3_MEDIUM = "TIER_3_MEDIUM"
    TIER_4_HIGH = "TIER_4_HIGH"


class DeterministicRiskGate:
    """Deterministic Safety Engine.

    Categorizes proposed operational interventions into strict safety tiers.
    Never relies on stochastic LLM judgments for life-safety actions.
    """

    # Actions that unconditionally require human approval
    HIGH_RISK_ACTION_TYPES = {
        "CLOSE_PRIMARY_ARTERY",
        "REROUTE_TRAUMA_PATIENTS",
    }

    MEDIUM_RISK_ACTION_TYPES = {
        "DEPLOY_ROAD_BLOCK_BARRIER",
        "DISPATCH_HIGH_WATER_EMS",
        "RESERVE_AMBULANCE",
        "ACTIVATE_SECONDARY_DETOUR",
    }

    LOW_RISK_ACTION_TYPES = {
        "UPDATE_VARIABLE_MESSAGE_SIGN",
        "NOTIFY_HOSPITAL_TRAUMA_BAY",
        "ISSUE_PUBLIC_TRAVEL_ADVISORY",
    }

    @classmethod
    def evaluate_action(cls, action: ActionItem) -> tuple[RiskTier, bool]:
        """Evaluates an action and returns its RiskTier and whether approval is required."""
        if action.action_type in cls.HIGH_RISK_ACTION_TYPES:
            return RiskTier.TIER_4_HIGH, True
        if action.action_type in cls.MEDIUM_RISK_ACTION_TYPES:
            return RiskTier.TIER_3_MEDIUM, True
        if action.action_type in cls.LOW_RISK_ACTION_TYPES:
            return RiskTier.TIER_2_LOW, False
        return RiskTier.TIER_1_AUTO, False

    @classmethod
    def evaluate_plan(cls, actions: list[ActionItem]) -> tuple[list[ActionItem], bool]:
        """Evaluates all actions in a plan and determines overall approval requirement.

        Strictly deterministic: overwrites any attempted LLM policy bypasses.
        """
        requires_approval = False
        evaluated_actions: list[ActionItem] = []

        for action in actions:
            tier, needs_approval = cls.evaluate_action(action)
            action.risk_tier = tier.value
            action.approval_required = needs_approval
            # Deterministically enforce PENDING status if approval required
            if needs_approval and action.approval_status != "APPROVED":
                action.approval_status = "PENDING"
            elif not needs_approval:
                action.approval_status = "AUTO_APPROVED"

            if needs_approval:
                requires_approval = True
            evaluated_actions.append(action)

        return evaluated_actions, requires_approval

    @classmethod
    def validate_execution_permission(
        cls, action: ActionItem, decision_token: str | None = None
    ) -> None:
        """Validates that an action is legally permitted to execute.

        Raises PermissionError if an action requiring approval is not approved or lacks token.
        Raises RuntimeError if an action was already executed (duplicate execution prevention).
        """
        if action.executed:
            raise RuntimeError(
                f"Action {action.action_id} ({action.action_type}) has already executed. "
                "Duplicate execution prevented."
            )

        tier, needs_approval = cls.evaluate_action(action)
        if needs_approval:
            if action.approval_status != "APPROVED":
                raise PermissionError(
                    f"Policy violation: Action {action.action_id} of risk tier {tier.value} "
                    f"({action.action_type}) cannot execute without explicit human commander approval!"
                )
            if not decision_token:
                raise PermissionError(
                    f"Policy violation: Action {action.action_id} requires a valid signed "
                    "commander authorization token to execute!"
                )
