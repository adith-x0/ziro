"""NEXUS Safety Agent and Deterministic Policy Gatekeeper.

The final deterministic authority over whether a proposed action or plan is
permitted to proceed. Operates completely independently of LLMs and Gemini.

Mandates:
1. Zero LLM reasoning for policy decisions: Gemini cannot lower risk, bypass approval,
   or permit prohibited actions.
2. Least-privilege tool authorization.
3. Risk escalation only: never downgrades risk tiers.
4. Cryptographic approval token binding:
   incident_id + plan_id + action_id + plan_version + action_parameters_hash
5. Stale and contradictory evidence protection.
6. Resource and route grounding against simulation environment.
7. Fail-closed error handling: unexpected exceptions result strictly in DENY or
   BLOCKED_PENDING_INFORMATION.
8. Structured audit event generation for every evaluation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from agents.base import BaseAgent
from agents.planning import (
    ROLLBACK_MAPPING,
    ActionRiskLevel,
    PlanAction,
    PlanActionType,
    PlanningOutput,
)
from agents.safety_policy import (
    ACTION_ALLOWED_TOOLS_MAP,
    ApprovalRequirement,
    ApprovalStatus,
    DeterministicSafetyPolicy,
    SafetyDecision,
    SafetyPolicyRuleId,
    compute_action_parameters_hash,
)
from agents.schemas import (
    ApprovalRecordData,
    NexusBaseSchema,
    PlanActionItem,
    PlanData,
    RiskAssessmentData,
)
from tools.registry import ToolRegistry, default_tool_registry

logger = logging.getLogger("nexus.safety.agent")


# -----------------------------------------------------------------------------
# Structured Safety Schemas
# -----------------------------------------------------------------------------
class SafetyEvaluationOutput(NexusBaseSchema):
    """Authoritative deterministic safety evaluation of a single operational action."""

    evaluation_id: str = Field(
        default_factory=lambda: f"eval-{uuid.uuid4().hex[:8]}",
        description="Unique safety evaluation identifier",
    )
    incident_id: str = Field(..., description="Target incident identifier")
    plan_id: str = Field(..., description="Originating plan identifier")
    action_id: str = Field(..., description="Target action identifier")
    decision: SafetyDecision = Field(
        ...,
        description="Deterministic decision: ALLOW, ALLOW_WITH_APPROVAL, DENY, BLOCKED_PENDING_INFORMATION",
    )
    risk_level: ActionRiskLevel = Field(
        ..., description="Deterministic escalated risk level: LOW, MEDIUM, HIGH, HUMAN_ONLY"
    )
    requires_human_approval: bool = Field(
        ..., description="True if human commander authorization is mandatory"
    )
    policy_rule_ids: list[str] = Field(
        default_factory=list, description="Explicit policy rules triggered during evaluation"
    )
    violations: list[str] = Field(
        default_factory=list, description="Fatal policy violations preventing execution"
    )
    warnings: list[str] = Field(
        default_factory=list, description="Non-fatal operational advisories"
    )
    evidence_ids: list[str] = Field(
        default_factory=list, description="Grounding evidence IDs backing the action"
    )
    allowed_tools: list[str] = Field(
        default_factory=list, description="Whitelist of tools authorized for this action type"
    )
    denied_tools: list[str] = Field(
        default_factory=list, description="Disallowed tools rejected during evaluation"
    )
    parameter_validation: dict[str, Any] = Field(
        default_factory=dict, description="Validated and sanitized parameters"
    )
    approval_status: ApprovalStatus = Field(
        default=ApprovalStatus.NOT_REQUIRED, description="Current authorization status"
    )
    rollback_requirement: str | None = Field(
        default=None, description="Rollback protocol if action is reversible"
    )
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp of deterministic evaluation",
    )
    # Additional audit and binding fields
    action_parameters_hash: str = Field(
        default="", description="Deterministic SHA-256 parameter digest"
    )
    plan_version: int = Field(default=1, ge=1, description="Plan iteration version")
    explanation: str = Field(default="", description="Concise human-readable rationale")
    approval_id: str | None = Field(default=None, description="Linked approval requirement ID")


class SafetyAuditEvent(NexusBaseSchema):
    """Structured, immutable audit event recorded for every safety evaluation."""

    event_id: str = Field(default_factory=lambda: f"audit-saf-{uuid.uuid4().hex[:8]}")
    evaluation_id: str
    incident_id: str
    plan_id: str
    plan_version: int
    action_id: str
    decision: SafetyDecision
    risk_level: ActionRiskLevel
    policy_rule_ids: list[str]
    violations: list[str]
    evidence_ids: list[str]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# -----------------------------------------------------------------------------
# Safety Agent Implementation
# -----------------------------------------------------------------------------
class SafetyAgent(BaseAgent):
    """Autonomous Deterministic Safety Policy Gatekeeper.

    Evaluates proposed action DAGs and individual actions against deterministic
    safety policies, evidence grounding, resource availability, route clearance,
    and cryptographic approval tokens.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        policy: DeterministicSafetyPolicy | None = None,
    ) -> None:
        super().__init__(name="SafetyAgent", role="Deterministic Safety Policy Gatekeeper")
        self.tool_registry = tool_registry or default_tool_registry
        self.policy = policy or DeterministicSafetyPolicy(tool_registry=self.tool_registry)
        self.audit_log: list[SafetyAuditEvent] = []

    def get_audit_events(self) -> list[SafetyAuditEvent]:
        """Returns all recorded safety audit events."""
        return list(self.audit_log)

    def evaluate_action(
        self,
        action: PlanAction,
        state: Any,
        plan: PlanningOutput | PlanData | None = None,
        approval_token: str
        | ApprovalRecordData
        | ApprovalRequirement
        | dict[str, Any]
        | None = None,
    ) -> SafetyEvaluationOutput:
        """Deterministically evaluates a discrete operational action against policy rules.

        Strictly enforces the Fail-Closed principle: any unexpected exception returns
        DENY or BLOCKED_PENDING_INFORMATION.
        """
        # Top-level fail-closed catch-all
        try:
            return self._evaluate_action_internal(
                action=action,
                state=state,
                plan=plan,
                approval_token=approval_token,
            )
        except Exception as ex:
            logger.exception("Fail-closed interceptor triggered in evaluate_action: %s", ex)
            return SafetyEvaluationOutput(
                incident_id=self._extract_incident_id(state, plan),
                plan_id=getattr(plan, "plan_id", "PLAN-UNKNOWN") if plan else "PLAN-UNKNOWN",
                action_id=action.action_id,
                decision=SafetyDecision.DENY,
                risk_level=ActionRiskLevel.HUMAN_ONLY,
                requires_human_approval=True,
                policy_rule_ids=[SafetyPolicyRuleId.RULE_FAIL_CLOSED.value],
                violations=[f"Fail-closed interceptor triggered: {type(ex).__name__}: {str(ex)}"],
                warnings=[],
                evidence_ids=list(action.evidence_ids),
                allowed_tools=[],
                denied_tools=[action.required_tool],
                parameter_validation={},
                approval_status=ApprovalStatus.REJECTED,
                rollback_requirement=None,
                action_parameters_hash=compute_action_parameters_hash(action.parameters),
                plan_version=getattr(plan, "plan_version", 1) if plan else 1,
                explanation=f"Action denied by fail-closed safety interceptor due to unexpected internal exception: {str(ex)}",
            )

    def _evaluate_action_internal(
        self,
        action: PlanAction,
        state: Any,
        plan: PlanningOutput | PlanData | None = None,
        approval_token: str
        | ApprovalRecordData
        | ApprovalRequirement
        | dict[str, Any]
        | None = None,
    ) -> SafetyEvaluationOutput:
        """Internal deterministic rule-evaluation pipeline."""
        incident_id = self._extract_incident_id(state, plan)
        plan_id = getattr(plan, "plan_id", "PLAN-UNKNOWN") if plan else "PLAN-UNKNOWN"
        plan_version = getattr(plan, "plan_version", 1) if plan else 1

        policy_rules: list[str] = []
        violations: list[str] = []
        warnings: list[str] = []
        denied_tools: list[str] = []

        raw_parameters = dict(action.parameters)
        param_hash = compute_action_parameters_hash(raw_parameters)

        # ---------------------------------------------------------------------
        # 1. Prohibited Actions Check
        # ---------------------------------------------------------------------
        is_prohibited, prohib_violations = self.policy.check_prohibited_action(
            action_type=action.action_type.value
            if isinstance(action.action_type, PlanActionType)
            else str(action.action_type),
            required_tool=action.required_tool,
            parameters=raw_parameters,
        )
        if is_prohibited:
            policy_rules.append(SafetyPolicyRuleId.RULE_SEC_01_PROHIBITED.value)
            violations.extend(prohib_violations)
            denied_tools.append(action.required_tool)

            return self._record_and_build_output(
                incident_id=incident_id,
                plan_id=plan_id,
                plan_version=plan_version,
                action_id=action.action_id,
                decision=SafetyDecision.DENY,
                risk_level=ActionRiskLevel.HUMAN_ONLY,
                requires_approval=True,
                policy_rules=policy_rules,
                violations=violations,
                warnings=warnings,
                evidence_ids=action.evidence_ids,
                allowed_tools=[],
                denied_tools=denied_tools,
                param_validation={},
                approval_status=ApprovalStatus.REJECTED,
                rollback_req=None,
                param_hash=param_hash,
                explanation="Action rejected: Prohibited real-world or irreversible operation.",
            )

        # ---------------------------------------------------------------------
        # 2. Tool Authorization Check
        # ---------------------------------------------------------------------
        action_type_str = (
            action.action_type.value
            if isinstance(action.action_type, PlanActionType)
            else str(action.action_type)
        )
        tool_authorized, tool_violations = self.policy.check_tool_authorization(
            action_type=action_type_str,
            tool_name=action.required_tool,
        )
        allowed_tools_for_action = ACTION_ALLOWED_TOOLS_MAP.get(action_type_str, [])

        if not tool_authorized:
            policy_rules.append(SafetyPolicyRuleId.RULE_TOOL_01_AUTH.value)
            violations.extend(tool_violations)
            denied_tools.append(action.required_tool)

            return self._record_and_build_output(
                incident_id=incident_id,
                plan_id=plan_id,
                plan_version=plan_version,
                action_id=action.action_id,
                decision=SafetyDecision.DENY,
                risk_level=ActionRiskLevel.HIGH,
                requires_approval=True,
                policy_rules=policy_rules,
                violations=violations,
                warnings=warnings,
                evidence_ids=action.evidence_ids,
                allowed_tools=allowed_tools_for_action,
                denied_tools=denied_tools,
                param_validation={},
                approval_status=ApprovalStatus.REJECTED,
                rollback_req=None,
                param_hash=param_hash,
                explanation=f"Action denied: Unauthorized tool '{action.required_tool}'.",
            )

        # ---------------------------------------------------------------------
        # 3. Parameter Validation Check
        # ---------------------------------------------------------------------
        params_valid, validated_params, param_violations = self.policy.validate_parameters(
            action_type=action_type_str,
            parameters=raw_parameters,
        )
        if not params_valid:
            policy_rules.append(SafetyPolicyRuleId.RULE_PARAM_01_VALID.value)
            violations.extend(param_violations)

            return self._record_and_build_output(
                incident_id=incident_id,
                plan_id=plan_id,
                plan_version=plan_version,
                action_id=action.action_id,
                decision=SafetyDecision.DENY,
                risk_level=ActionRiskLevel.HIGH,
                requires_approval=True,
                policy_rules=policy_rules,
                violations=violations,
                warnings=warnings,
                evidence_ids=action.evidence_ids,
                allowed_tools=allowed_tools_for_action,
                denied_tools=denied_tools,
                param_validation={},
                approval_status=ApprovalStatus.REJECTED,
                rollback_req=None,
                param_hash=param_hash,
                explanation="Action denied: Parameters violate strict schema bounds.",
            )

        # ---------------------------------------------------------------------
        # 4. Prompt Injection Defense Check
        # ---------------------------------------------------------------------
        has_injection, inj_warnings = self.policy.check_prompt_injection(
            parameters=validated_params,
            state=state,
            action_description=getattr(action, "description", None),
        )
        if has_injection:
            policy_rules.append(SafetyPolicyRuleId.RULE_INJ_01_PROMPT_DEFENSE.value)
            warnings.extend(inj_warnings)

        # ---------------------------------------------------------------------
        # 5. Risk Escalation Check (Never Downgrades)
        # ---------------------------------------------------------------------
        final_risk, was_escalated = self.policy.determine_escalated_risk(
            action_type=action_type_str,
            proposed_risk=action.risk_level,
        )
        if was_escalated:
            policy_rules.append(SafetyPolicyRuleId.RULE_RISK_01_ESCALATE.value)
            warnings.append(
                f"Policy escalated risk from '{action.risk_level}' to mandatory '{final_risk}'."
            )

        requires_approval = self.policy.is_approval_mandatory(final_risk)
        if requires_approval and not action.requires_approval:
            policy_rules.append(SafetyPolicyRuleId.RULE_APPR_01_REQUIREMENT.value)
            warnings.append("Policy mandated human approval requirement for elevated risk.")

        # ---------------------------------------------------------------------
        # 6. Resource Safety Check
        # ---------------------------------------------------------------------
        res_safe, res_violations = self.policy.check_resource_safety(
            action=action,
            parameters=validated_params,
            state=state,
        )
        if not res_safe:
            policy_rules.append(SafetyPolicyRuleId.RULE_RES_01_SAFETY.value)
            violations.extend(res_violations)
            return self._record_and_build_output(
                incident_id=incident_id,
                plan_id=plan_id,
                plan_version=plan_version,
                action_id=action.action_id,
                decision=SafetyDecision.DENY,
                risk_level=final_risk,
                requires_approval=requires_approval,
                policy_rules=policy_rules,
                violations=violations,
                warnings=warnings,
                evidence_ids=action.evidence_ids,
                allowed_tools=allowed_tools_for_action,
                denied_tools=denied_tools,
                param_validation=validated_params,
                approval_status=ApprovalStatus.REJECTED,
                rollback_req=None,
                param_hash=param_hash,
                explanation="Action denied: Resource does not exist, is fabricated, or is busy.",
            )

        # ---------------------------------------------------------------------
        # 7. Route Safety Check
        # ---------------------------------------------------------------------
        rt_safe, rt_uncertain, rt_violations = self.policy.check_route_safety(
            action=action,
            parameters=validated_params,
            state=state,
        )
        if rt_uncertain and final_risk in (ActionRiskLevel.MEDIUM, ActionRiskLevel.HIGH):
            policy_rules.append(SafetyPolicyRuleId.RULE_RT_01_SAFETY.value)
            warnings.extend(rt_violations)
            return self._record_and_build_output(
                incident_id=incident_id,
                plan_id=plan_id,
                plan_version=plan_version,
                action_id=action.action_id,
                decision=SafetyDecision.BLOCKED_PENDING_INFORMATION,
                risk_level=final_risk,
                requires_approval=requires_approval,
                policy_rules=policy_rules,
                violations=[],
                warnings=warnings,
                evidence_ids=action.evidence_ids,
                allowed_tools=allowed_tools_for_action,
                denied_tools=denied_tools,
                param_validation=validated_params,
                approval_status=ApprovalStatus.PENDING,
                rollback_req=None,
                param_hash=param_hash,
                explanation="Action blocked: Route corridor status is uncertain / at risk.",
            )
        elif not rt_safe:
            policy_rules.append(SafetyPolicyRuleId.RULE_RT_01_SAFETY.value)
            violations.extend(rt_violations)
            return self._record_and_build_output(
                incident_id=incident_id,
                plan_id=plan_id,
                plan_version=plan_version,
                action_id=action.action_id,
                decision=SafetyDecision.DENY,
                risk_level=final_risk,
                requires_approval=requires_approval,
                policy_rules=policy_rules,
                violations=violations,
                warnings=warnings,
                evidence_ids=action.evidence_ids,
                allowed_tools=allowed_tools_for_action,
                denied_tools=denied_tools,
                param_validation=validated_params,
                approval_status=ApprovalStatus.REJECTED,
                rollback_req=None,
                param_hash=param_hash,
                explanation="Action denied: Route corridor is BLOCKED or fabricated.",
            )

        # ---------------------------------------------------------------------
        # 8. Plan Integrity Check
        # ---------------------------------------------------------------------
        plan_intact, plan_violations = self.policy.check_plan_integrity(
            action=action,
            plan=plan,
            state=state,
        )
        if not plan_intact:
            policy_rules.append(SafetyPolicyRuleId.RULE_PLAN_01_INTEGRITY.value)
            violations.extend(plan_violations)

            # Determine whether violation is a hard deny or blocked dependency
            is_dep_error = any("Prerequisite dependency" in v for v in plan_violations)
            decision = (
                SafetyDecision.BLOCKED_PENDING_INFORMATION if is_dep_error else SafetyDecision.DENY
            )

            return self._record_and_build_output(
                incident_id=incident_id,
                plan_id=plan_id,
                plan_version=plan_version,
                action_id=action.action_id,
                decision=decision,
                risk_level=final_risk,
                requires_approval=requires_approval,
                policy_rules=policy_rules,
                violations=violations,
                warnings=warnings,
                evidence_ids=action.evidence_ids,
                allowed_tools=allowed_tools_for_action,
                denied_tools=denied_tools,
                param_validation=validated_params,
                approval_status=ApprovalStatus.REJECTED
                if decision == SafetyDecision.DENY
                else ApprovalStatus.PENDING,
                rollback_req=None,
                param_hash=param_hash,
                explanation=f"Action halted due to plan integrity failure: {plan_violations[0]}",
            )

        # ---------------------------------------------------------------------
        # 9. Evidence Freshness & Contradictions Check
        # ---------------------------------------------------------------------
        ev_fresh, stale_ids, missing_ids = self.policy.check_evidence_freshness(
            action=action,
            state=state,
        )
        if not ev_fresh:
            policy_rules.append(SafetyPolicyRuleId.RULE_EVID_01_FRESHNESS.value)
            if stale_ids:
                warnings.append(
                    f"Evidence IDs {stale_ids} are stale (> {self.policy.max_evidence_age_seconds}s) and require refresh."
                )
            if missing_ids:
                warnings.append("Action lacks required grounding evidence IDs.")

            return self._record_and_build_output(
                incident_id=incident_id,
                plan_id=plan_id,
                plan_version=plan_version,
                action_id=action.action_id,
                decision=SafetyDecision.BLOCKED_PENDING_INFORMATION,
                risk_level=final_risk,
                requires_approval=requires_approval,
                policy_rules=policy_rules,
                violations=[],
                warnings=warnings,
                evidence_ids=action.evidence_ids,
                allowed_tools=allowed_tools_for_action,
                denied_tools=denied_tools,
                param_validation=validated_params,
                approval_status=ApprovalStatus.PENDING,
                rollback_req=None,
                param_hash=param_hash,
                explanation="Action blocked pending fresh telemetry: Required evidence is stale or ungrounded.",
            )

        has_contras, contras = self.policy.check_evidence_contradictions(
            action=action,
            state=state,
        )
        if has_contras:
            policy_rules.append(SafetyPolicyRuleId.RULE_EVID_02_CONTRADICTION.value)
            # LOW read-only actions can proceed with warning; MEDIUM/HIGH must block
            if final_risk in (ActionRiskLevel.MEDIUM, ActionRiskLevel.HIGH):
                warnings.append(f"Unresolved contradictions in incident evidence: {contras[0]}.")
                return self._record_and_build_output(
                    incident_id=incident_id,
                    plan_id=plan_id,
                    plan_version=plan_version,
                    action_id=action.action_id,
                    decision=SafetyDecision.BLOCKED_PENDING_INFORMATION,
                    risk_level=final_risk,
                    requires_approval=requires_approval,
                    policy_rules=policy_rules,
                    violations=[],
                    warnings=warnings,
                    evidence_ids=action.evidence_ids,
                    allowed_tools=allowed_tools_for_action,
                    denied_tools=denied_tools,
                    param_validation=validated_params,
                    approval_status=ApprovalStatus.PENDING,
                    rollback_req=None,
                    param_hash=param_hash,
                    explanation="Action blocked: Critical evidence contradictions detected in state telemetry.",
                )
            else:
                warnings.append(f"Contradictions detected in state telemetry: {contras[0]}.")

        # ---------------------------------------------------------------------
        # 10. Human-In-The-Loop Approval & Token Binding Check
        # ---------------------------------------------------------------------
        rollback_info = ROLLBACK_MAPPING.get(action.action_type, (False, None))
        rollback_req = rollback_info[1] if rollback_info[0] else None

        if final_risk == ActionRiskLevel.HUMAN_ONLY:
            policy_rules.append(SafetyPolicyRuleId.RULE_APPR_01_REQUIREMENT.value)
            violations.append(
                f"Action '{action.action_id}' is HUMAN_ONLY and cannot be executed autonomously."
            )
            return self._record_and_build_output(
                incident_id=incident_id,
                plan_id=plan_id,
                plan_version=plan_version,
                action_id=action.action_id,
                decision=SafetyDecision.DENY,
                risk_level=final_risk,
                requires_approval=True,
                policy_rules=policy_rules,
                violations=violations,
                warnings=warnings,
                evidence_ids=action.evidence_ids,
                allowed_tools=allowed_tools_for_action,
                denied_tools=denied_tools,
                param_validation=validated_params,
                approval_status=ApprovalStatus.REJECTED,
                rollback_req=rollback_req,
                param_hash=param_hash,
                explanation="Action denied: HUMAN_ONLY actions require direct human intervention.",
            )

        if not requires_approval:
            # LOW read-only actions do not require approval
            policy_rules.append(SafetyPolicyRuleId.RULE_APPR_01_REQUIREMENT.value)
            return self._record_and_build_output(
                incident_id=incident_id,
                plan_id=plan_id,
                plan_version=plan_version,
                action_id=action.action_id,
                decision=SafetyDecision.ALLOW,
                risk_level=final_risk,
                requires_approval=False,
                policy_rules=policy_rules,
                violations=[],
                warnings=warnings,
                evidence_ids=action.evidence_ids,
                allowed_tools=allowed_tools_for_action,
                denied_tools=denied_tools,
                param_validation=validated_params,
                approval_status=ApprovalStatus.NOT_REQUIRED,
                rollback_req=rollback_req,
                param_hash=param_hash,
                explanation="Action approved: Low risk read-only operational step.",
            )

        # MEDIUM or HIGH risk requires verified token
        token_input = approval_token or validated_params.get("approval_token")

        if not token_input:
            # No token presented -> Awaiting commander approval
            policy_rules.append(SafetyPolicyRuleId.RULE_APPR_01_REQUIREMENT.value)
            return self._record_and_build_output(
                incident_id=incident_id,
                plan_id=plan_id,
                plan_version=plan_version,
                action_id=action.action_id,
                decision=SafetyDecision.ALLOW_WITH_APPROVAL,
                risk_level=final_risk,
                requires_approval=True,
                policy_rules=policy_rules,
                violations=[],
                warnings=warnings,
                evidence_ids=action.evidence_ids,
                allowed_tools=allowed_tools_for_action,
                denied_tools=denied_tools,
                param_validation=validated_params,
                approval_status=ApprovalStatus.PENDING,
                rollback_req=rollback_req,
                param_hash=param_hash,
                explanation="Action staged: Requires human commander approval before execution.",
            )

        # Token presented: verify cryptographic and state binding
        token_valid, tid, token_violations = self.policy.verify_approval_token(
            token_or_record=token_input,
            expected_incident_id=incident_id,
            expected_plan_id=plan_id,
            expected_action_id=action.action_id,
            expected_plan_version=plan_version,
            expected_param_hash=param_hash,
        )

        if token_valid:
            policy_rules.append(SafetyPolicyRuleId.RULE_APPR_02_TOKEN_BINDING.value)
            # Record token as consumed to prevent replay attacks
            if tid:
                self.policy.record_consumed_token(tid)

            return self._record_and_build_output(
                incident_id=incident_id,
                plan_id=plan_id,
                plan_version=plan_version,
                action_id=action.action_id,
                decision=SafetyDecision.ALLOW,
                risk_level=final_risk,
                requires_approval=True,
                policy_rules=policy_rules,
                violations=[],
                warnings=warnings,
                evidence_ids=action.evidence_ids,
                allowed_tools=allowed_tools_for_action,
                denied_tools=denied_tools,
                param_validation=validated_params,
                approval_status=ApprovalStatus.APPROVED,
                rollback_req=rollback_req,
                param_hash=param_hash,
                explanation="Action authorized: Valid cryptographic commander approval token verified.",
                approval_id=tid,
            )
        else:
            # Token failed binding verification
            policy_rules.append(SafetyPolicyRuleId.RULE_APPR_02_TOKEN_BINDING.value)
            violations.extend(token_violations)
            return self._record_and_build_output(
                incident_id=incident_id,
                plan_id=plan_id,
                plan_version=plan_version,
                action_id=action.action_id,
                decision=SafetyDecision.DENY,
                risk_level=final_risk,
                requires_approval=True,
                policy_rules=policy_rules,
                violations=violations,
                warnings=warnings,
                evidence_ids=action.evidence_ids,
                allowed_tools=allowed_tools_for_action,
                denied_tools=denied_tools,
                param_validation=validated_params,
                approval_status=ApprovalStatus.REJECTED,
                rollback_req=rollback_req,
                param_hash=param_hash,
                explanation=f"Action denied: Approval token rejected - {token_violations[0]}",
                approval_id=tid,
            )

    def evaluate_plan(
        self,
        plan: PlanningOutput | PlanData,
        state: Any,
        approval_tokens: dict[str, Any] | None = None,
    ) -> list[SafetyEvaluationOutput]:
        """Evaluates every discrete action in a proposed plan DAG."""
        tokens_map = approval_tokens or {}
        evaluations: list[SafetyEvaluationOutput] = []

        actions = getattr(plan, "actions", [])
        for act in actions:
            if isinstance(act, PlanAction):
                act_obj = act
            elif (
                isinstance(act, PlanActionItem)
                or hasattr(act, "sequence")
                or (isinstance(act, dict) and "sequence" in act)
            ):
                act_dict = act.model_dump() if hasattr(act, "model_dump") else dict(act)
                act_type_val = act_dict.get("action_type", "CALCULATE_ROUTE")
                allowed_tools = ACTION_ALLOWED_TOOLS_MAP.get(act_type_val, ["routing"])
                req_tool = allowed_tools[0] if allowed_tools else "routing"
                target_ent = act_dict.get("target_entity", "")
                params = dict(act_dict.get("parameters", {}))
                if not params:
                    inc_id = self._extract_incident_id(state, plan)
                    if act_type_val == "RESERVE_SIMULATED_RESOURCE":
                        params = {"resource_id": target_ent or "AMB-01", "incident_id": inc_id}
                    elif act_type_val == "UPDATE_SIMULATED_ROAD_STATUS":
                        params = {
                            "road_id": target_ent or "ROUTE-B",
                            "new_status": "SAFE",
                            "incident_id": inc_id,
                        }
                    elif act_type_val == "CALCULATE_ROUTE":
                        params = {"origin": "DEPOT", "destination": target_ent or "CITY-HOSPITAL"}
                    elif act_type_val == "SEND_SIMULATED_NOTIFICATION":
                        params = {"message": "Operational alert", "incident_id": inc_id}
                    else:
                        params = {"incident_id": inc_id}
                act_obj = PlanAction(
                    action_id=act_dict.get("action_id", f"act-{uuid.uuid4().hex[:6]}"),
                    action_type=act_type_val,
                    description=act_dict.get("description")
                    or f"Operational action {act_dict.get('action_id')}",
                    required_tool=act_dict.get("required_tool") or req_tool,
                    parameters=params,
                    risk_level=act_dict.get("risk_level", "LOW"),
                    requires_approval=act_dict.get("requires_approval", False),
                    evidence_ids=act_dict.get("evidence_ids", ["ev-radar-01"]),
                )
            else:
                act_obj = PlanAction.model_validate(
                    act.model_dump() if hasattr(act, "model_dump") else act
                )
            act_token = tokens_map.get(act_obj.action_id)
            eval_out = self.evaluate_action(
                action=act_obj,
                state=state,
                plan=plan,
                approval_token=act_token,
            )
            evaluations.append(eval_out)

        return evaluations

    async def process(self, state: Any) -> dict[str, Any]:
        """Processes NexusState, performs deterministic safety gate evaluation, and updates state."""
        plan = getattr(state, "plan", None) if hasattr(state, "plan") else None
        if isinstance(state, dict):
            plan = state.get("plan")

        if not plan:
            logger.warning("No plan present in NexusState for safety evaluation.")
            return {}

        evaluations = self.evaluate_plan(plan=plan, state=state)

        # Determine overall plan risk
        highest_weight = 1
        overall_risk = "LOW"
        high_risk_actions: list[str] = []
        rules_triggered: set[str] = set()
        approval_mandatory = False
        pending_approvals: list[SafetyEvaluationOutput] = []

        weight_map = {
            ActionRiskLevel.LOW: 1,
            ActionRiskLevel.MEDIUM: 2,
            ActionRiskLevel.HIGH: 3,
            ActionRiskLevel.HUMAN_ONLY: 4,
        }

        for ev in evaluations:
            w = weight_map.get(ev.risk_level, 1)
            if w > highest_weight:
                highest_weight = w
                overall_risk = (
                    ev.risk_level.value if hasattr(ev.risk_level, "value") else str(ev.risk_level)
                )

            if ev.risk_level in (
                ActionRiskLevel.MEDIUM,
                ActionRiskLevel.HIGH,
                ActionRiskLevel.HUMAN_ONLY,
            ):
                high_risk_actions.append(ev.action_id)

            if ev.requires_human_approval and ev.approval_status != ApprovalStatus.APPROVED:
                approval_mandatory = True
                pending_approvals.append(ev)

            rules_triggered.update(ev.policy_rule_ids)

        risk_data = RiskAssessmentData(
            overall_risk_level=overall_risk,  # type: ignore
            human_approval_required=approval_mandatory,
            high_risk_actions=high_risk_actions,
            policy_rules_triggered=sorted(list(rules_triggered)),
            justification=f"Deterministic policy evaluation assessed {len(evaluations)} actions; {len(high_risk_actions)} require oversight.",
        )

        approval_record = None
        if pending_approvals:
            first_pending = pending_approvals[0]
            approval_record = ApprovalRecordData(
                action_id=first_pending.action_id,
                action_type="OPERATIONAL_ACTION",
                target_entity=first_pending.action_id,
                risk_level=first_pending.risk_level.value
                if hasattr(first_pending.risk_level, "value")
                else str(first_pending.risk_level),  # type: ignore
                status="PENDING",
                reason=first_pending.explanation,
                incident_id=first_pending.incident_id,
                plan_id=first_pending.plan_id,
                plan_version=first_pending.plan_version,
                action_parameters_hash=first_pending.action_parameters_hash,
            )

        return {
            "risk_assessment": risk_data.model_dump(mode="json"),
            "approval": approval_record.model_dump(mode="json") if approval_record else None,
            "safety_evaluations": [e.model_dump(mode="json") for e in evaluations],
        }

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------
    def _extract_incident_id(self, state: Any, plan: Any) -> str:
        """Extracts incident identifier from plan or state."""
        if plan and getattr(plan, "incident_id", None):
            return str(plan.incident_id)

        incident_state = getattr(state, "incident", None) if hasattr(state, "incident") else None
        if isinstance(state, dict):
            incident_state = state.get("incident")

        if incident_state:
            inc_id = getattr(incident_state, "incident_id", None) or incident_state.get(
                "incident_id"
            )
            if inc_id:
                return str(inc_id)

        return "INCIDENT-UNKNOWN"

    def _record_and_build_output(
        self,
        incident_id: str,
        plan_id: str,
        plan_version: int,
        action_id: str,
        decision: SafetyDecision,
        risk_level: ActionRiskLevel,
        requires_approval: bool,
        policy_rules: list[str],
        violations: list[str],
        warnings: list[str],
        evidence_ids: list[str],
        allowed_tools: list[str],
        denied_tools: list[str],
        param_validation: dict[str, Any],
        approval_status: ApprovalStatus,
        rollback_req: str | None,
        param_hash: str,
        explanation: str,
        approval_id: str | None = None,
    ) -> SafetyEvaluationOutput:
        """Constructs SafetyEvaluationOutput and records structured audit event."""
        eval_id = f"eval-{uuid.uuid4().hex[:8]}"

        output = SafetyEvaluationOutput(
            evaluation_id=eval_id,
            incident_id=incident_id,
            plan_id=plan_id,
            action_id=action_id,
            decision=decision,
            risk_level=risk_level,
            requires_human_approval=requires_approval,
            policy_rule_ids=policy_rules,
            violations=violations,
            warnings=warnings,
            evidence_ids=list(evidence_ids),
            allowed_tools=allowed_tools,
            denied_tools=denied_tools,
            parameter_validation=param_validation,
            approval_status=approval_status,
            rollback_requirement=rollback_req,
            action_parameters_hash=param_hash,
            plan_version=plan_version,
            explanation=explanation,
            approval_id=approval_id,
        )

        audit_event = SafetyAuditEvent(
            evaluation_id=eval_id,
            incident_id=incident_id,
            plan_id=plan_id,
            plan_version=plan_version,
            action_id=action_id,
            decision=decision,
            risk_level=risk_level,
            policy_rule_ids=policy_rules,
            violations=violations,
            evidence_ids=list(evidence_ids),
        )
        self.audit_log.append(audit_event)

        return output
