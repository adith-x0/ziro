from orchestration.risk_gate import DeterministicRiskGate, RiskTier
from orchestration.state import ActionItem


def test_high_risk_actions_require_approval():
    """Verify high-risk actions are deterministically assigned Tier 4 and require approval."""
    high_risk_actions = [
        "CLOSE_PRIMARY_ARTERY",
        "REROUTE_TRAUMA_PATIENTS",
    ]
    for action_type in high_risk_actions:
        action = ActionItem(
            action_id="act-test",
            sequence_order=1,
            action_type=action_type,  # type: ignore[arg-type]
            target_entity="Hospital District",
            risk_tier="TIER_1_AUTO",  # Initial dummy tier
            description="Test high risk action",
            execution_payload={},
            approval_required=False,
            approval_status="AUTO_APPROVED",
        )
        tier, needs_approval = DeterministicRiskGate.evaluate_action(action)
        assert tier == RiskTier.TIER_4_HIGH
        assert needs_approval is True


def test_low_risk_actions_auto_approved():
    """Verify informational and advisory actions do not halt the system."""
    action = ActionItem(
        action_id="act-test-vms",
        sequence_order=1,
        action_type="UPDATE_VARIABLE_MESSAGE_SIGN",
        target_entity="Sign VMS-10",
        risk_tier="TIER_1_AUTO",
        description="Update highway advisory sign",
        execution_payload={"text": "Caution High Water Ahead"},
        approval_required=False,
        approval_status="PENDING",
    )
    tier, needs_approval = DeterministicRiskGate.evaluate_action(action)
    assert tier == RiskTier.TIER_2_LOW
    assert needs_approval is False


def test_plan_evaluation_approval_flag():
    """Verify plan containing mixed actions correctly flags overall approval requirement."""
    plan = [
        ActionItem(
            action_id="act-1",
            sequence_order=1,
            action_type="UPDATE_VARIABLE_MESSAGE_SIGN",
            target_entity="VMS-1",
            risk_tier="TIER_1_AUTO",
            description="Inform drivers",
            execution_payload={},
            approval_required=False,
            approval_status="PENDING",
        ),
        ActionItem(
            action_id="act-2",
            sequence_order=2,
            action_type="CLOSE_PRIMARY_ARTERY",
            target_entity="Metropolitan Pkwy",
            risk_tier="TIER_1_AUTO",
            description="Road closure",
            execution_payload={},
            approval_required=False,
            approval_status="PENDING",
        ),
    ]
    evaluated_plan, requires_approval = DeterministicRiskGate.evaluate_plan(plan)
    assert requires_approval is True
    assert evaluated_plan[0].approval_status == "AUTO_APPROVED"
    assert evaluated_plan[1].approval_status == "PENDING"
    assert evaluated_plan[1].risk_tier == RiskTier.TIER_4_HIGH.value
