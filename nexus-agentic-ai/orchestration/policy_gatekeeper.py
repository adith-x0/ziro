"""NEXUS Deterministic Policy Gatekeeper.

Enforces non-negotiable safety guardrails across operational actions.
Never permits an LLM to self-authorize medium or high-risk operational state mutations.

Strict Policy:
- READ_ONLY: AUTO
- ROUTE_CALCULATION: AUTO
- RESOURCE_RESERVATION: HUMAN_APPROVAL
- PUBLIC_ALERT: HUMAN_APPROVAL
- MEDICAL_DECISION: DENY / HUMAN_ONLY
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from orchestration.mvp_models import ActionDAGItem, ApprovalRecord


class PolicyGatekeeper:
    """Authoritative deterministic policy barrier."""

    # Categorization of action types into governance tiers
    POLICY_RULES: dict[str, Literal["AUTO", "HUMAN_APPROVAL", "DENY"]] = {
        "VERIFY_INCIDENT": "AUTO",
        "SELECT_AMBULANCE": "AUTO",
        "SELECT_SAFE_ROUTE": "AUTO",
        "RESERVE_AMBULANCE": "HUMAN_APPROVAL",
        "NOTIFY_HOSPITAL": "AUTO",
        "REROUTE_CORRIDOR": "AUTO",
        "PUBLIC_ALERT": "HUMAN_APPROVAL",
        "MEDICAL_DECISION": "DENY",
    }

    RISK_LEVEL_MAP: dict[str, str] = {
        "VERIFY_INCIDENT": "LOW",
        "SELECT_AMBULANCE": "LOW",
        "SELECT_SAFE_ROUTE": "LOW",
        "RESERVE_AMBULANCE": "MEDIUM",
        "NOTIFY_HOSPITAL": "LOW",
        "REROUTE_CORRIDOR": "LOW",
        "PUBLIC_ALERT": "MEDIUM",
        "MEDICAL_DECISION": "HIGH",
    }

    @classmethod
    def evaluate_action(
        cls, action: ActionDAGItem, incident_id: str
    ) -> tuple[Literal["AUTO", "HUMAN_APPROVAL", "DENY"], ApprovalRecord | None]:
        """Deterministically evaluates action permissions and returns governance decision."""
        decision = cls.POLICY_RULES.get(action.action_type, "HUMAN_APPROVAL")
        risk_level = cls.RISK_LEVEL_MAP.get(action.action_type, "MEDIUM")

        # Deterministically override action properties
        action.risk_level = risk_level  # type: ignore

        if decision == "AUTO":
            action.requires_approval = False
            action.status = "APPROVED"
            return "AUTO", None

        elif decision == "HUMAN_APPROVAL":
            action.requires_approval = True
            action.status = "PENDING"
            approval = ApprovalRecord(
                approval_id=f"appr-{uuid.uuid4().hex[:8]}",
                incident_id=incident_id,
                action_id=action.action_id,
                action_type=action.action_type,
                target_entity=action.target_entity,
                risk_level=risk_level,
                status="PENDING",
                reason="Resource allocation changes operational state and commits emergency vehicles.",
                supporting_evidence_count=3,
                requested_at=datetime.now(UTC),
            )
            return "HUMAN_APPROVAL", approval

        else:  # DENY
            action.requires_approval = False
            action.status = "REJECTED"
            return "DENY", None

    @classmethod
    def evaluate_plan(
        cls, actions: list[ActionDAGItem], incident_id: str
    ) -> tuple[list[ActionDAGItem], list[ApprovalRecord], bool]:
        """Evaluates all actions in an action DAG.

        Returns: (evaluated_actions, pending_approvals, requires_human_approval)
        """
        evaluated_actions: list[ActionDAGItem] = []
        pending_approvals: list[ApprovalRecord] = []
        requires_approval = False

        for act in actions:
            decision, approval = cls.evaluate_action(act, incident_id)
            evaluated_actions.append(act)
            if decision == "HUMAN_APPROVAL" and approval is not None:
                pending_approvals.append(approval)
                requires_approval = True

        return evaluated_actions, pending_approvals, requires_approval
