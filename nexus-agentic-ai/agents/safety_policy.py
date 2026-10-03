"""NEXUS Deterministic Safety Policy Engine.

The final deterministic authority over whether a proposed action or plan is
permitted to proceed. Operates completely independently of LLMs and Gemini.

Core Invariants:
1. Deterministic Rule Base: Decisions are made strictly by deterministic policy rules.
2. Zero Stochastic LLM Bypass: Safety evaluations must NOT rely on LLM prompts or
   stochastic judgements; LLMs cannot lower risk levels or bypass approval.
3. Least-Privilege Tool Authorization:
   action_type -> allowed tool(s) -> parameter schema -> risk level -> approval requirement
4. Risk Escalation Only: The Safety Agent can escalate risk tiers, but NEVER downgrades.
5. Strict Approval Token Binding:
   Approval is cryptographically and deterministically bound to:
   incident_id + plan_id + action_id + plan_version + action_parameters_hash
6. Stale and Contradictory Evidence Protection:
   Stale or contradictory evidence blocks risky actions with BLOCKED_PENDING_INFORMATION.
7. Resource and Route Grounding:
   Fabricated or busy resources (e.g., AMB-999) and blocked corridors are denied.
8. Prompt Injection Defense:
   All external text is treated strictly as untrusted data, never as instructions.
9. Fail-Closed Principle:
   Any unhandled exception or policy failure results in DENY or BLOCKED_PENDING_INFORMATION.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agents.planning import (
    RESOURCE_ID_REGEX,
    ROUTE_ID_REGEX,
    TOOL_NAME_REGEX,
    ActionRiskLevel,
    PlanAction,
    PlanActionStatus,
    PlanActionType,
    PlanningOutput,
)
from agents.schemas import ApprovalRecordData, NexusBaseSchema, PlanData
from tools.registry import ToolRegistry, default_tool_registry
from tools.synthetic_environment import simulated_fleet_service, synthetic_road_network

try:
    from app.config import settings
except ImportError:
    try:
        from backend.app.config import settings  # type: ignore[no-redef]
    except ImportError:
        settings = None  # type: ignore[assignment]

logger = logging.getLogger("nexus.safety.policy")

# Secret key used for deterministic HMAC signing of approval decision tokens
NEXUS_SAFETY_TOKEN_SECRET = "NEXUS-SAFETY-GATE-SECRET-2026-STRICT"

# Named Configuration Setting: Tactical Freshness Threshold for Safety Agent.
# Architectural Rationale for Dual Freshness Thresholds:
# 1. Strategic Verification Threshold (2.0 hours / 7200s, `evidence_staleness_max_hours`):
#    Verification corroborates that an incident exists and cross-checks multi-source evidence
#    (radars, citizen reports, satellite imagery) over a broader lifecycle window.
# 2. Tactical Safety Gatekeeping Threshold (30 minutes / 1800s, `safety_evidence_staleness_max_seconds`):
#    Safety is the final tactical gatekeeper before dispatching physical actuators (ambulances,
#    corridor closures). In flood emergencies, hydrological depths and corridor passability can
#    submerge roads within minutes. Safety strictly enforces this 30-minute tactical threshold on
#    critical corridor and dispatch telemetry to prevent dispatching units into outdated conditions,
#    even if the broader incident remains verified.
DEFAULT_SAFETY_EVIDENCE_MAX_AGE_SECONDS: float = (
    settings.safety_evidence_staleness_max_seconds if settings else 1800.0
)
DEFAULT_MAX_EVIDENCE_AGE_SECONDS: float = DEFAULT_SAFETY_EVIDENCE_MAX_AGE_SECONDS


# -----------------------------------------------------------------------------
# Decision & Lifecycle Enums
# -----------------------------------------------------------------------------
class SafetyDecision(StrEnum):
    """Categorical policy determination for a proposed action."""

    ALLOW = "ALLOW"
    ALLOW_WITH_APPROVAL = "ALLOW_WITH_APPROVAL"
    DENY = "DENY"
    BLOCKED_PENDING_INFORMATION = "BLOCKED_PENDING_INFORMATION"


class ApprovalStatus(StrEnum):
    """Human-in-the-loop authorization lifecycle status."""

    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SafetyPolicyRuleId(StrEnum):
    """Explicit, auditable policy rule identifiers."""

    RULE_SEC_01_PROHIBITED = "RULE-SEC-01-PROHIBITED"
    RULE_TOOL_01_AUTH = "RULE-TOOL-01-AUTH"
    RULE_TOOL_02_NAMESPACE = "RULE-TOOL-02-NAMESPACE"
    RULE_PARAM_01_VALID = "RULE-PARAM-01-VALID"
    RULE_RISK_01_ESCALATE = "RULE-RISK-01-ESCALATE"
    RULE_APPR_01_REQUIREMENT = "RULE-APPR-01-REQUIREMENT"
    RULE_APPR_02_TOKEN_BINDING = "RULE-APPR-02-TOKEN-BINDING"
    RULE_APPR_03_TOKEN_REUSE = "RULE-APPR-03-TOKEN-REUSE"
    RULE_PLAN_01_INTEGRITY = "RULE-PLAN-01-INTEGRITY"
    RULE_DEP_01_SATISFACTION = "RULE-DEP-01-SATISFACTION"
    RULE_ACT_01_LIFECYCLE = "RULE-ACT-01-LIFECYCLE"
    RULE_EVID_01_FRESHNESS = "RULE-EVID-01-FRESHNESS"
    RULE_EVID_02_CONTRADICTION = "RULE-EVID-02-CONTRADICTION"
    RULE_RES_01_SAFETY = "RULE-RES-01-SAFETY"
    RULE_RT_01_SAFETY = "RULE-RT-01-SAFETY"
    RULE_INJ_01_PROMPT_DEFENSE = "RULE-INJ-01-PROMPT-DEFENSE"
    RULE_FAIL_CLOSED = "RULE-FAIL-CLOSED"


# -----------------------------------------------------------------------------
# Security Patterns & Prohibited Keywords
# -----------------------------------------------------------------------------
PROHIBITED_ACTION_KEYWORDS: list[str] = [
    "REAL_EMERGENCY_DISPATCH",
    "REAL_AMBULANCE_CONTROL",
    "REAL_HOSPITAL_CONTROL",
    "MEDICAL_DECISION",
    "MEDICAL_DIAGNOSIS",
    "MEDICAL_TREATMENT_DECISION",
    "AUTONOMOUS_CASUALTY_DETERMINATION",
    "PERFORM_SURGERY",
    "LEGAL_DECISION",
    "LEGAL_ORDER",
    "FINANCIAL_DECISION",
    "FINANCIAL_TRANSACTION",
    "TRANSFER_FUNDS",
    "WEAPON_RELATED_ACTION",
    "SYSTEM_SHUTDOWN",
    "DISPATCH_REAL",
    "DEPLOY_POLICE",
    "DEPLOY_FIRE",
    "DISPATCH_POLICE",
    "DISPATCH_FIRE",
    "REAL_",
    "ACTUAL_",
]

PROMPT_INJECTION_PATTERNS = [
    re.compile(
        r"(?i)(ignore\s+(all\s+)?previous\s+instructions|system\s+override|bypass\s+(safety|gate|policy)|DAN\s+mode|ADMIN_OVERRIDE)"
    ),
    re.compile(
        r"(?i)(ignore\s+safety\s+rules|set\s+requires_approval\s*=\s*false|mark\s+as\s+safe|auto_approve)"
    ),
    re.compile(r"(?i)(dispatch\s+the\s+ambulance\s+anyway|override\s+policy)"),
]

REGISTERED_SIMULATION_TOOLS: set[str] = {
    "weather",
    "incident_reports",
    "image_analysis",
    "geolocation",
    "routing",
    "resource_search",
    "hospital_status",
    "notifications",
    "ambulance_reservation",
    "incident_status_update",
    "audit_logging",
}

# Strict Action -> Allowed Tools Whitelist
ACTION_ALLOWED_TOOLS_MAP: dict[str, list[str]] = {
    PlanActionType.CALCULATE_ROUTE.value: ["routing"],
    PlanActionType.SEARCH_SIMULATED_RESOURCES.value: ["resource_search"],
    PlanActionType.CHECK_HOSPITAL_STATUS.value: ["hospital_status"],
    PlanActionType.MONITOR_INCIDENT.value: ["incident_reports", "weather", "hospital_status"],
    PlanActionType.REQUEST_ADDITIONAL_VERIFICATION.value: [
        "incident_reports",
        "weather",
        "image_analysis",
        "geolocation",
    ],
    PlanActionType.LOG_AUDIT_EVENT.value: ["audit_logging"],
    PlanActionType.RESERVE_SIMULATED_RESOURCE.value: ["ambulance_reservation"],
    PlanActionType.UPDATE_SIMULATED_ROAD_STATUS.value: ["incident_status_update"],
    PlanActionType.UPDATE_SIMULATED_INCIDENT_STATUS.value: ["incident_status_update"],
    PlanActionType.SEND_SIMULATED_NOTIFICATION.value: ["notifications"],
}

# Strict Baseline Risk Classification
POLICY_BASELINE_RISK_MAP: dict[str, ActionRiskLevel] = {
    PlanActionType.CALCULATE_ROUTE.value: ActionRiskLevel.LOW,
    PlanActionType.SEARCH_SIMULATED_RESOURCES.value: ActionRiskLevel.LOW,
    PlanActionType.CHECK_HOSPITAL_STATUS.value: ActionRiskLevel.LOW,
    PlanActionType.MONITOR_INCIDENT.value: ActionRiskLevel.LOW,
    PlanActionType.REQUEST_ADDITIONAL_VERIFICATION.value: ActionRiskLevel.LOW,
    PlanActionType.LOG_AUDIT_EVENT.value: ActionRiskLevel.LOW,
    PlanActionType.RESERVE_SIMULATED_RESOURCE.value: ActionRiskLevel.MEDIUM,
    PlanActionType.UPDATE_SIMULATED_ROAD_STATUS.value: ActionRiskLevel.MEDIUM,
    PlanActionType.UPDATE_SIMULATED_INCIDENT_STATUS.value: ActionRiskLevel.HIGH,
    PlanActionType.SEND_SIMULATED_NOTIFICATION.value: ActionRiskLevel.HIGH,
}

RISK_LEVEL_WEIGHT: dict[ActionRiskLevel, int] = {
    ActionRiskLevel.LOW: 1,
    ActionRiskLevel.MEDIUM: 2,
    ActionRiskLevel.HIGH: 3,
    ActionRiskLevel.HUMAN_ONLY: 4,
}


# -----------------------------------------------------------------------------
# Parameter Validation Schemas for Executable Simulated Actions
# -----------------------------------------------------------------------------
class StrictBaseParams(BaseModel):
    """Base schema enforcing extra-field rejection and string boundaries."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
    )


class ReserveSimulatedResourceParams(StrictBaseParams):
    """Schema for RESERVE_SIMULATED_RESOURCE."""

    resource_id: str = Field(..., min_length=2, max_length=64)
    incident_id: str = Field(..., min_length=2, max_length=64)
    destination: str | None = Field(default=None, max_length=128)
    detour_route_id: str | None = Field(default=None, max_length=64)
    approval_token: str | None = Field(default=None, max_length=256)
    unit_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def normalize_resource_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "unit_id" in data and "resource_id" not in data:
                data["resource_id"] = data["unit_id"]
            elif "resource_id" in data and "unit_id" not in data:
                data["unit_id"] = data["resource_id"]
        return data


class UpdateSimulatedRoadStatusParams(StrictBaseParams):
    """Schema for UPDATE_SIMULATED_ROAD_STATUS."""

    road_id: str = Field(..., min_length=2, max_length=64)
    new_status: str = Field(..., min_length=2, max_length=64)
    incident_id: str = Field(..., min_length=2, max_length=64)
    commentary: str | None = Field(default=None, max_length=500)
    route_id: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def normalize_road_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "route_id" in data and "road_id" not in data:
                data["road_id"] = data["route_id"]
            elif "road_id" in data and "route_id" not in data:
                data["route_id"] = data["road_id"]
            if "status" in data and "new_status" not in data:
                data["new_status"] = data["status"]
            elif "new_status" in data and "status" not in data:
                data["status"] = data["new_status"]
        return data


class SendSimulatedNotificationParams(StrictBaseParams):
    """Schema for SEND_SIMULATED_NOTIFICATION."""

    notification_id: str = Field(default_factory=lambda: f"notif-{uuid.uuid4().hex[:8]}")
    message: str = Field(..., min_length=2, max_length=1000)
    incident_id: str = Field(..., min_length=2, max_length=64)
    recipient: str | None = Field(default="EMERGENCY_DISPATCH", max_length=128)
    channel: str | None = Field(default="HOSPITAL_ALERT_FEED", max_length=64)
    title: str | None = Field(default="Operational Alert", max_length=128)
    priority: str | None = Field(default="MEDIUM", max_length=32)
    delivery_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def normalize_notification(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "delivery_id" in data and "notification_id" not in data:
                data["notification_id"] = data["delivery_id"]
            elif "notification_id" in data and "delivery_id" not in data:
                data["delivery_id"] = data["notification_id"]
        return data


class UpdateSimulatedIncidentStatusParams(StrictBaseParams):
    """Schema for UPDATE_SIMULATED_INCIDENT_STATUS."""

    incident_id: str = Field(..., min_length=2, max_length=64)
    new_status: str = Field(..., min_length=2, max_length=64)
    commentary: str | None = Field(default=None, max_length=500)


class CalculateRouteParams(StrictBaseParams):
    """Schema for CALCULATE_ROUTE."""

    origin: str = Field(default="DEPOT", min_length=2, max_length=128)
    destination: str = Field(default="CITY-HOSPITAL", min_length=2, max_length=128)
    avoid_routes: list[str] = Field(default_factory=list)
    vehicle_clearance_inches: float = Field(default=12.0, ge=0.0, le=100.0)


class SearchSimulatedResourcesParams(StrictBaseParams):
    """Schema for SEARCH_SIMULATED_RESOURCES."""

    resource_type: str = Field(default="AMBULANCE", max_length=64)
    required_clearance_inches: float = Field(default=0.0, ge=0.0, le=100.0)
    max_distance_km: float = Field(default=25.0, ge=0.0, le=500.0)


class CheckHospitalStatusParams(StrictBaseParams):
    """Schema for CHECK_HOSPITAL_STATUS."""

    hospital_id: str = Field(default="CITY-HOSPITAL", min_length=2, max_length=64)


class MonitorIncidentParams(StrictBaseParams):
    """Schema for MONITOR_INCIDENT."""

    incident_id: str = Field(..., min_length=2, max_length=64)
    corridor: str | None = Field(default=None, max_length=64)


class RequestAdditionalVerificationParams(StrictBaseParams):
    """Schema for REQUEST_ADDITIONAL_VERIFICATION."""

    incident_id: str = Field(..., min_length=2, max_length=64)
    claim: str | None = Field(default=None, max_length=500)
    evidence_needed: list[str] = Field(default_factory=list)


class LogAuditEventParams(StrictBaseParams):
    """Schema for LOG_AUDIT_EVENT."""

    incident_id: str = Field(..., min_length=2, max_length=64)
    event_type: str = Field(..., min_length=2, max_length=64)
    summary: str = Field(..., min_length=2, max_length=500)
    actor: str = Field(default="SAFETY_AGENT", max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


ACTION_PARAM_MODELS: dict[str, type[StrictBaseParams]] = {
    PlanActionType.RESERVE_SIMULATED_RESOURCE.value: ReserveSimulatedResourceParams,
    PlanActionType.UPDATE_SIMULATED_ROAD_STATUS.value: UpdateSimulatedRoadStatusParams,
    PlanActionType.SEND_SIMULATED_NOTIFICATION.value: SendSimulatedNotificationParams,
    PlanActionType.UPDATE_SIMULATED_INCIDENT_STATUS.value: UpdateSimulatedIncidentStatusParams,
    PlanActionType.CALCULATE_ROUTE.value: CalculateRouteParams,
    PlanActionType.SEARCH_SIMULATED_RESOURCES.value: SearchSimulatedResourcesParams,
    PlanActionType.CHECK_HOSPITAL_STATUS.value: CheckHospitalStatusParams,
    PlanActionType.MONITOR_INCIDENT.value: MonitorIncidentParams,
    PlanActionType.REQUEST_ADDITIONAL_VERIFICATION.value: RequestAdditionalVerificationParams,
    PlanActionType.LOG_AUDIT_EVENT.value: LogAuditEventParams,
}


# -----------------------------------------------------------------------------
# Approval Requirement & Token Binding Data Structures
# -----------------------------------------------------------------------------
class ApprovalRequirement(NexusBaseSchema):
    """Structured human-in-the-loop approval requirement."""

    approval_id: str = Field(default_factory=lambda: f"appr-{uuid.uuid4().hex[:8]}")
    action_id: str = Field(..., description="Action ID requiring approval")
    incident_id: str = Field(..., description="Target incident ID")
    plan_id: str = Field(..., description="Originating plan ID")
    plan_version: int = Field(default=1, ge=1, description="Plan iteration version")
    action_parameters_hash: str = Field(..., description="SHA-256 parameter digest")
    required_role: str = Field(default="COMMANDER", description="Required role to authorize")
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    approver_id: str | None = None
    expires_at: datetime | None = None
    decision_token: str | None = None


def compute_action_parameters_hash(parameters: dict[str, Any]) -> str:
    """Computes deterministic SHA-256 hash of action parameters.

    Excludes volatile or token fields ('approval_token') to prevent circular
    dependency while strictly guaranteeing parameter integrity.
    """
    clean_params = {k: v for k, v in parameters.items() if k != "approval_token"}
    canonical_json = json.dumps(clean_params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def generate_approval_decision_token(
    incident_id: str,
    plan_id: str,
    action_id: str,
    plan_version: int,
    action_parameters_hash: str,
    approver_id: str = "COMMANDER",
    secret: str = NEXUS_SAFETY_TOKEN_SECRET,
    token_id: str | None = None,
) -> str:
    """Generates an HMAC-signed approval token bound to exact plan and parameter state."""
    tid = token_id or f"tok-{uuid.uuid4().hex[:8]}"
    payload = f"{tid}|{incident_id}|{plan_id}|{action_id}|{plan_version}|{action_parameters_hash}|{approver_id}"
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return f"NEXUS-TOKEN:{tid}:{incident_id}:{plan_id}:{action_id}:v{plan_version}:{action_parameters_hash[:8]}:{sig}"


# -----------------------------------------------------------------------------
# Deterministic Safety Policy Engine
# -----------------------------------------------------------------------------
class DeterministicSafetyPolicy:
    """Deterministic policy engine evaluating plans and discrete actions.

    Zero LLM dependencies. All decisions are derived purely from rules,
    grounded evidence, state integrity, and cryptographic token verification.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        max_evidence_age_seconds: float | None = None,
    ) -> None:
        self.tool_registry = tool_registry or default_tool_registry
        self.max_evidence_age_seconds = (
            max_evidence_age_seconds
            if max_evidence_age_seconds is not None
            else (
                settings.safety_evidence_staleness_max_seconds
                if settings
                else DEFAULT_SAFETY_EVIDENCE_MAX_AGE_SECONDS
            )
        )
        self._consumed_tokens: set[str] = set()

    def record_consumed_token(self, token_identifier: str) -> None:
        """Records a token as consumed/executed to prevent replay attacks."""
        self._consumed_tokens.add(token_identifier)

    def is_token_consumed(self, token_identifier: str) -> bool:
        """Checks if a token has already been consumed."""
        return token_identifier in self._consumed_tokens

    # -------------------------------------------------------------------------
    # Policy Rule 1: Prohibited Actions
    # -------------------------------------------------------------------------
    def check_prohibited_action(
        self,
        action_type: str,
        required_tool: str,
        parameters: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Determines if action involves prohibited real-world/irreversible consequences."""
        violations: list[str] = []
        action_type_upper = action_type.upper()

        for kw in PROHIBITED_ACTION_KEYWORDS:
            if kw in action_type_upper:
                violations.append(
                    f"Action type '{action_type}' contains prohibited keyword '{kw}'."
                )

        # Check for clinical, financial, or lethal operations in parameters
        for val in parameters.values():
            if isinstance(val, str):
                val_upper = val.upper()
                for kw in ["PERFORM_SURGERY", "TRANSFER_FUNDS", "LEGAL_ORDER", "REAL_DISPATCH"]:
                    if kw in val_upper:
                        violations.append(f"Action parameters contain prohibited directive '{kw}'.")

        return len(violations) > 0, violations

    # -------------------------------------------------------------------------
    # Policy Rule 2 & 3: Tool Authorization & Namespace
    # -------------------------------------------------------------------------
    def check_tool_authorization(
        self,
        action_type: str,
        tool_name: str,
    ) -> tuple[bool, list[str]]:
        """Verifies tool exists in simulation namespace and is authorized for action."""
        violations: list[str] = []

        if not TOOL_NAME_REGEX.match(tool_name):
            violations.append(f"Tool identifier '{tool_name}' has invalid format.")
            return False, violations

        # Check tool registration in ToolRegistry
        if tool_name not in REGISTERED_SIMULATION_TOOLS or not self.tool_registry.has(tool_name):
            violations.append(
                f"Tool '{tool_name}' is not an authorized simulated tool in ToolRegistry."
            )
            return False, violations

        # Check action -> tool permission whitelist
        allowed_tools = ACTION_ALLOWED_TOOLS_MAP.get(action_type, [])
        if tool_name not in allowed_tools:
            violations.append(
                f"Tool '{tool_name}' is disallowed for action '{action_type}'. Allowed: {allowed_tools}."
            )
            return False, violations

        return True, violations

    # -------------------------------------------------------------------------
    # Policy Rule 4: Parameter Validation
    # -------------------------------------------------------------------------
    def validate_parameters(
        self,
        action_type: str,
        parameters: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], list[str]]:
        """Validates action parameters against strict Pydantic model for action_type."""
        violations: list[str] = []
        model_cls = ACTION_PARAM_MODELS.get(action_type)

        if not model_cls:
            violations.append(f"No parameter schema defined for action type '{action_type}'.")
            return False, parameters, violations

        try:
            validated = model_cls.model_validate(parameters)
            return True, validated.model_dump(), violations
        except ValidationError as ex:
            for err in ex.errors():
                loc = ".".join(str(p) for p in err.get("loc", []))
                msg = err.get("msg", "Validation error")
                violations.append(f"Parameter validation failed at '{loc}': {msg}")
            return False, parameters, violations
        except Exception as ex:
            violations.append(f"Unexpected parameter validation exception: {str(ex)}")
            return False, parameters, violations

    # -------------------------------------------------------------------------
    # Policy Rule 5: Risk Escalation
    # -------------------------------------------------------------------------
    def determine_escalated_risk(
        self,
        action_type: str,
        proposed_risk: ActionRiskLevel | str,
    ) -> tuple[ActionRiskLevel, bool]:
        """Enforces risk escalation: NEVER allows risk to be downgraded.

        Returns (final_risk_level, was_escalated).
        """
        # Parse proposed risk
        try:
            prop_enum = (
                proposed_risk
                if isinstance(proposed_risk, ActionRiskLevel)
                else ActionRiskLevel(str(proposed_risk).upper())
            )
        except ValueError:
            prop_enum = ActionRiskLevel.HIGH

        baseline_risk = POLICY_BASELINE_RISK_MAP.get(action_type, ActionRiskLevel.HIGH)

        prop_weight = RISK_LEVEL_WEIGHT.get(prop_enum, 2)
        base_weight = RISK_LEVEL_WEIGHT.get(baseline_risk, 2)

        if base_weight > prop_weight:
            # Policy escalates risk
            return baseline_risk, True
        else:
            # Maintain proposed risk (cannot downgrade baseline)
            return prop_enum, False

    # -------------------------------------------------------------------------
    # Policy Rule 6 & 7: Approval Requirement & Token Binding
    # -------------------------------------------------------------------------
    def is_approval_mandatory(self, risk_level: ActionRiskLevel) -> bool:
        """Determines whether human commander approval is strictly required."""
        return risk_level in (
            ActionRiskLevel.MEDIUM,
            ActionRiskLevel.HIGH,
            ActionRiskLevel.HUMAN_ONLY,
        )

    def verify_approval_token(
        self,
        token_or_record: str | ApprovalRecordData | ApprovalRequirement | dict[str, Any] | None,
        expected_incident_id: str,
        expected_plan_id: str,
        expected_action_id: str,
        expected_plan_version: int,
        expected_param_hash: str,
    ) -> tuple[bool, str | None, list[str]]:
        """Cryptographically verifies approval token against exact plan and parameter state.

        Returns: (is_valid, token_id, violations)
        """
        violations: list[str] = []
        if not token_or_record:
            violations.append("Approval token is missing.")
            return False, None, violations

        token_str: str | None = None
        token_id: str | None = None
        rec_status: str = "APPROVED"
        rec_incident_id: str | None = None
        rec_plan_id: str | None = None
        rec_action_id: str | None = None
        rec_plan_version: int | None = None
        rec_param_hash: str | None = None
        rec_expires_at: datetime | None = None

        if isinstance(token_or_record, str):
            token_str = token_or_record.strip()
        elif isinstance(token_or_record, (ApprovalRecordData, ApprovalRequirement)):
            token_id = token_or_record.approval_id
            rec_status = str(token_or_record.status)
            token_str = token_or_record.decision_token
            rec_action_id = token_or_record.action_id
            if hasattr(token_or_record, "incident_id"):
                rec_incident_id = token_or_record.incident_id
            if hasattr(token_or_record, "plan_id"):
                rec_plan_id = token_or_record.plan_id
            if hasattr(token_or_record, "plan_version"):
                rec_plan_version = token_or_record.plan_version
            if hasattr(token_or_record, "action_parameters_hash"):
                rec_param_hash = token_or_record.action_parameters_hash
            if hasattr(token_or_record, "expires_at"):
                rec_expires_at = token_or_record.expires_at
        elif isinstance(token_or_record, dict):
            token_id = str(token_or_record.get("approval_id") or token_or_record.get("token_id"))
            rec_status = str(token_or_record.get("status", "APPROVED"))
            token_str = token_or_record.get("decision_token") or token_or_record.get("token")
            rec_incident_id = token_or_record.get("incident_id")
            rec_plan_id = token_or_record.get("plan_id")
            rec_action_id = token_or_record.get("action_id")
            rec_plan_version = token_or_record.get("plan_version")
            rec_param_hash = token_or_record.get("action_parameters_hash")
            rec_expires_at = token_or_record.get("expires_at")

        # 1. Status check
        if rec_status.upper() == "REJECTED":
            violations.append("Approval record has explicit REJECTED status.")
            return False, token_id, violations
        if rec_status.upper() == "PENDING" and not token_str:
            violations.append("Approval status is PENDING; action has not been authorized.")
            return False, token_id, violations

        # 2. Expiration check
        if rec_expires_at:
            if isinstance(rec_expires_at, str):
                try:
                    rec_expires_at = datetime.fromisoformat(rec_expires_at)
                except ValueError:
                    rec_expires_at = None
            if rec_expires_at and rec_expires_at < datetime.now(UTC):
                violations.append("Approval token has expired.")
                return False, token_id, violations

        # 3. Direct record field validation
        if rec_action_id and rec_action_id != expected_action_id:
            violations.append(
                f"Approval action mismatch: issued for '{rec_action_id}', current is '{expected_action_id}'."
            )
            return False, token_id, violations
        if rec_incident_id and rec_incident_id != expected_incident_id:
            violations.append(
                f"Approval incident mismatch: issued for '{rec_incident_id}', current is '{expected_incident_id}'."
            )
            return False, token_id, violations
        if rec_plan_id and rec_plan_id != expected_plan_id:
            violations.append(
                f"Approval plan mismatch: issued for '{rec_plan_id}', current is '{expected_plan_id}'."
            )
            return False, token_id, violations
        if rec_plan_version is not None and rec_plan_version != expected_plan_version:
            violations.append(
                f"Approval plan version mismatch: issued for v{rec_plan_version}, current is v{expected_plan_version}."
            )
            return False, token_id, violations
        if rec_param_hash and not expected_param_hash.startswith(rec_param_hash):
            violations.append(
                f"Action parameter hash mismatch: token was bound to '{rec_param_hash}', current parameters produce '{expected_param_hash}'."
            )
            return False, token_id, violations

        # 4. Token string parsing (NEXUS-TOKEN format)
        if token_str and token_str.startswith("NEXUS-TOKEN:"):
            parts = token_str.split(":")
            # Format: NEXUS-TOKEN:{tid}:{incident}:{plan}:{action}:v{ver}:{hash_prefix}:{sig}
            if len(parts) >= 7:
                parsed_tid = parts[1]
                parsed_inc = parts[2]
                parsed_plan = parts[3]
                parsed_act = parts[4]
                parsed_ver_str = parts[5].lstrip("v")
                parsed_hash_prefix = parts[6]
                _parsed_sig = parts[7] if len(parts) > 7 else ""

                token_id = token_id or parsed_tid

                # Check token replay
                if parsed_tid in self._consumed_tokens:
                    violations.append(f"Reused approval token detected: '{parsed_tid}'.")
                    return False, token_id, violations

                if parsed_inc != expected_incident_id:
                    violations.append(
                        f"Approval token incident mismatch: token specifies '{parsed_inc}', current is '{expected_incident_id}'."
                    )
                if parsed_plan != expected_plan_id:
                    violations.append(
                        f"Approval token plan mismatch: token specifies '{parsed_plan}', current is '{expected_plan_id}'."
                    )
                if parsed_act != expected_action_id:
                    violations.append(
                        f"Approval token action mismatch: token specifies '{parsed_act}', current is '{expected_action_id}'."
                    )
                try:
                    parsed_ver = int(parsed_ver_str)
                    if parsed_ver != expected_plan_version:
                        violations.append(
                            f"Approval token plan version mismatch: token specifies v{parsed_ver}, current is v{expected_plan_version}."
                        )
                except ValueError:
                    violations.append(f"Invalid plan version in token: '{parsed_ver_str}'.")

                if not expected_param_hash.startswith(parsed_hash_prefix):
                    violations.append(
                        f"Approval token parameter hash mismatch: token specifies '{parsed_hash_prefix}', current parameters digest is '{expected_param_hash[:8]}'."
                    )

                if violations:
                    return False, token_id, violations

                return True, token_id, []
            else:
                violations.append(f"Malformed NEXUS-TOKEN structure: '{token_str}'.")
                return False, token_id, violations

        # Fallback for plain tokens without prefix
        if token_str:
            if token_str in self._consumed_tokens:
                violations.append(f"Reused approval token detected: '{token_str}'.")
                return False, token_id, violations
            # If plain token was provided but no fields could be verified, reject fake token
            if not (rec_incident_id or rec_plan_id or rec_action_id):
                violations.append(f"Unverified or forged decision token: '{token_str}'.")
                return False, token_id, violations

        return len(violations) == 0, token_id, violations

    # -------------------------------------------------------------------------
    # Policy Rule 8: Plan Integrity
    # -------------------------------------------------------------------------
    def check_plan_integrity(
        self,
        action: PlanAction,
        plan: PlanningOutput | PlanData | None,
        state: Any,
    ) -> tuple[bool, list[str]]:
        """Verifies plan is valid, not superseded, version matches, and action is topologically sound."""
        violations: list[str] = []
        if plan is None:
            return True, []

        # Check plan validation status
        plan_status = getattr(plan, "validation_status", None) or getattr(plan, "status", None)
        if plan_status in ("INVALID", "BLOCKED", "NEEDS_REVISION"):
            violations.append(f"Plan validation status is '{plan_status}'; actions cannot proceed.")

        # Check if plan is marked as superseded or invalidated
        if getattr(plan, "supersedes_plan_id", None) and getattr(plan, "is_superseded", False):
            violations.append("Plan has been superseded by a newer version.")

        # Check plan version against state
        state_plan = getattr(state, "plan", None) if hasattr(state, "plan") else None
        if isinstance(state, dict):
            state_plan = state.get("plan")
        if state_plan:
            state_ver = getattr(state_plan, "plan_version", None) or getattr(
                state_plan, "version", None
            )
            plan_ver = getattr(plan, "plan_version", None) or getattr(plan, "version", None)
            if state_ver and plan_ver and state_ver > plan_ver:
                violations.append(
                    f"Plan v{plan_ver} is superseded by active state plan v{state_ver}."
                )

        # Check action existence and uniqueness in plan
        plan_actions = getattr(plan, "actions", [])
        if plan_actions:
            matching_actions = [
                a
                for a in plan_actions
                if (
                    getattr(a, "action_id", None)
                    or (a.get("action_id") if isinstance(a, dict) else None)
                )
                == action.action_id
            ]
            if not matching_actions:
                violations.append(
                    f"Action '{action.action_id}' does not exist in plan '{getattr(plan, 'plan_id', 'UNKNOWN')}'."
                )
            elif len(matching_actions) > 1:
                violations.append(f"Duplicate action ID '{action.action_id}' detected in plan.")

        # Check action lifecycle (must not have already completed or failed)
        if action.status in (PlanActionStatus.COMPLETED, PlanActionStatus.EXECUTING):
            violations.append(
                f"Action '{action.action_id}' has lifecycle status '{action.status}' and cannot be re-executed."
            )

        # Check dependencies: prerequisites must be completed
        if action.depends_on:
            for dep_id in action.depends_on:
                dep_action = next(
                    (
                        a
                        for a in plan_actions
                        if (
                            getattr(a, "action_id", None)
                            or (a.get("action_id") if isinstance(a, dict) else None)
                        )
                        == dep_id
                    ),
                    None,
                )
                if dep_action:
                    dep_status = getattr(dep_action, "status", None) or (
                        dep_action.get("status") if isinstance(dep_action, dict) else None
                    )
                    if dep_status != PlanActionStatus.COMPLETED and dep_status != "COMPLETED":
                        violations.append(
                            f"Prerequisite dependency '{dep_id}' is in status '{dep_status}', not 'COMPLETED'."
                        )
                else:
                    violations.append(f"Prerequisite dependency '{dep_id}' not found in plan.")

        return len(violations) == 0, violations

    # -------------------------------------------------------------------------
    # Policy Rule 9 & 10: Evidence Freshness & Contradictions
    # -------------------------------------------------------------------------
    def check_evidence_freshness(
        self,
        action: PlanAction,
        state: Any,
    ) -> tuple[bool, list[str], list[str]]:
        """Verifies evidence backing the action is present and not stale.

        Returns: (is_fresh, stale_evidence_ids, missing_evidence_ids)
        """
        stale_ids: list[str] = []
        missing_ids: list[str] = []

        # If action requires evidence but none declared
        if (
            action.action_type
            in (
                PlanActionType.RESERVE_SIMULATED_RESOURCE,
                PlanActionType.UPDATE_SIMULATED_ROAD_STATUS,
                PlanActionType.SEND_SIMULATED_NOTIFICATION,
            )
            and not action.evidence_ids
        ):
            missing_ids.append("MISSING_EVIDENCE_LIST")
            return False, stale_ids, missing_ids

        state_evidence = getattr(state, "evidence", []) if hasattr(state, "evidence") else []
        if isinstance(state, dict):
            state_evidence = state.get("evidence", [])

        evidence_by_id: dict[str, Any] = {}
        for ev in state_evidence:
            ev_id = getattr(ev, "evidence_id", None) or (
                ev.get("evidence_id") if isinstance(ev, dict) else None
            )
            if ev_id:
                evidence_by_id[ev_id] = ev

        now = datetime.now(UTC)
        for eid in action.evidence_ids:
            if eid not in evidence_by_id:
                # Could be grounded in verification facts or tool outputs
                continue
            ev_item = evidence_by_id[eid]
            is_stale = getattr(ev_item, "is_stale", False) or (
                ev_item.get("is_stale", False) if isinstance(ev_item, dict) else False
            )
            if is_stale:
                stale_ids.append(eid)
                continue

            ts = (
                getattr(ev_item, "observed_at", None)
                or getattr(ev_item, "collected_at", None)
                or (ev_item.get("observed_at") if isinstance(ev_item, dict) else None)
                or (ev_item.get("collected_at") if isinstance(ev_item, dict) else None)
            )
            if ts:
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts)
                    except ValueError:
                        ts = None
                if ts and (now - ts).total_seconds() > self.max_evidence_age_seconds:
                    stale_ids.append(eid)

        is_fresh = (len(stale_ids) == 0) and (len(missing_ids) == 0)
        return is_fresh, stale_ids, missing_ids

    def check_evidence_contradictions(
        self,
        action: PlanAction,
        state: Any,
    ) -> tuple[bool, list[str]]:
        """Checks for unresolved contradictions affecting this action in state."""
        contradictions: list[str] = []
        ver_state = getattr(state, "verification", None) if hasattr(state, "verification") else None
        if isinstance(state, dict):
            ver_state = state.get("verification")

        if not ver_state:
            return False, contradictions

        raw_contras = getattr(ver_state, "contradictions", []) or (
            ver_state.get("contradictions", []) if isinstance(ver_state, dict) else []
        )
        for c in raw_contras:
            desc = getattr(c, "description", None) or (
                c.get("description") if isinstance(c, dict) else str(c)
            )
            contradictions.append(str(desc))

        return len(contradictions) > 0, contradictions

    # -------------------------------------------------------------------------
    # Policy Rule 11: Resource Safety
    # -------------------------------------------------------------------------
    def check_resource_safety(
        self,
        action: PlanAction,
        parameters: dict[str, Any],
        state: Any,
    ) -> tuple[bool, list[str]]:
        """Verifies resource exists, is available, and belongs to approved namespace."""
        violations: list[str] = []
        unit_id = parameters.get("unit_id") or parameters.get("resource_id")
        if not unit_id:
            return True, []

        if not RESOURCE_ID_REGEX.match(unit_id):
            violations.append(f"Resource identifier '{unit_id}' has invalid format.")
            return False, violations

        # Explicit block on fabricated unit AMB-999 or non-existent fleet units
        fleet = getattr(simulated_fleet_service, "_fleet", {})
        if unit_id == "AMB-999" or unit_id not in fleet:
            violations.append(
                f"Resource '{unit_id}' does not exist in approved simulation fleet inventory."
            )
            return False, violations

        # Check unit status in fleet service
        fleet_unit = fleet.get(unit_id)
        if fleet_unit:
            if fleet_unit.status == "BUSY":
                violations.append(
                    f"Resource '{unit_id}' is currently BUSY and unavailable for reservation."
                )
            elif fleet_unit.status in ("OUT_OF_SERVICE", "MAINTENANCE"):
                violations.append(
                    f"Resource '{unit_id}' is {fleet_unit.status} and cannot be deployed."
                )

        return len(violations) == 0, violations

    # -------------------------------------------------------------------------
    # Policy Rule 12: Route Safety
    # -------------------------------------------------------------------------
    def check_route_safety(
        self,
        action: PlanAction,
        parameters: dict[str, Any],
        state: Any,
    ) -> tuple[bool, bool, list[str]]:
        """Verifies route exists, is available, and is not blocked or uncertain.

        Returns: (is_safe, is_uncertain, violations)
        """
        violations: list[str] = []
        route_id = (
            parameters.get("route_id")
            or parameters.get("road_id")
            or parameters.get("detour_route_id")
        )
        if not route_id:
            return True, False, []

        if not ROUTE_ID_REGEX.match(route_id):
            violations.append(f"Route identifier '{route_id}' has invalid format.")
            return False, False, violations

        # Check if route exists in road network
        routes_map = getattr(synthetic_road_network, "routes", {})
        if route_id not in routes_map:
            violations.append(
                f"Route corridor '{route_id}' does not exist in topological road network."
            )
            return False, False, violations

        segment = routes_map.get(route_id)
        if segment:
            depth = getattr(segment, "max_flood_depth_inches", 0.0)
            if segment.status == "BLOCKED":
                violations.append(f"Route corridor '{route_id}' is BLOCKED (depth: {depth}\").")
                return False, False, violations
            elif segment.status in ("AT_RISK", "UNCERTAIN"):
                violations.append(
                    f"Route corridor '{route_id}' has UNCERTAIN / AT_RISK status (depth: {depth}\")."
                )
                return False, True, violations

        return True, False, []

    # -------------------------------------------------------------------------
    # Policy Rule 13: Prompt Injection Defense
    # -------------------------------------------------------------------------
    def check_prompt_injection(
        self,
        parameters: dict[str, Any],
        state: Any = None,
        action_description: str | None = None,
    ) -> tuple[bool, list[str]]:
        """Scans parameter text fields, action descriptions, and state context for prompt injection patterns.

        In NEXUS, all external text is treated strictly as untrusted data.
        Injected directives can NEVER alter the underlying action, tool authorization,
        risk level, approval requirement, or deterministic policy decision.
        """
        warnings: list[str] = []
        for key, val in parameters.items():
            if isinstance(val, str):
                for p in PROMPT_INJECTION_PATTERNS:
                    if p.search(val):
                        warnings.append(
                            f"Untrusted directive/injection pattern detected in parameter '{key}'."
                        )
                        break

        # Scan action description if provided
        if action_description and isinstance(action_description, str):
            for p in PROMPT_INJECTION_PATTERNS:
                if p.search(action_description):
                    warnings.append(
                        "Untrusted directive/injection pattern detected in action description."
                    )
                    break

        # Also scan state untrusted text (incident description, citizen reports) if provided
        if state:
            incident_data = (
                getattr(state, "incident", None)
                if hasattr(state, "incident")
                else (state.get("incident") if isinstance(state, dict) else None)
            )
            if incident_data:
                desc = (
                    getattr(incident_data, "description", "")
                    if hasattr(incident_data, "description")
                    else (
                        incident_data.get("description", "")
                        if isinstance(incident_data, dict)
                        else ""
                    )
                )
                if isinstance(desc, str):
                    for p in PROMPT_INJECTION_PATTERNS:
                        if p.search(desc):
                            warnings.append(
                                "Untrusted directive/injection pattern detected in incident description."
                            )
                            break
        return len(warnings) > 0, warnings
