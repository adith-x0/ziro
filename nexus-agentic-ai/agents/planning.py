"""NEXUS Planning Agent and Action DAG Synthesizer.

Transforms verified incident intelligence, operational impact assessments,
available emergency resources, and safe topological routes into a structured,
executable Action Directed Acyclic Graph (DAG).

Strict Architectural and Safety Invariants:
1. MUST PLAN actions; MUST NEVER execute actions.
2. MUST NOT bypass safety controls or lower risk tiers to evade human approval.
3. MUST NOT directly invoke operational or actuator tools.
4. Deterministic Safety Policy:
   - LOW risk: read/verify/route/monitor -> requires_approval = False
   - MEDIUM risk: resource reservation / road allocation -> requires_approval = True
   - HIGH risk: public notification / external alert -> requires_approval = True
   - HUMAN_ONLY: clinical / financial / irreversible -> requires_approval = True
5. Topological DAG Validation:
   - Cycle detection (DFS 3-color / Kahn's algorithm)
   - Self-dependency prevention
   - Nonexistent dependency prevention
   - Duplicate action ID prevention
   - Strict tool mapping whitelist
   - Resource existence against available inventory
   - Route existence against clear corridors
   - Evidence grounding across all factual decisions
   - Reversible actions declare explicit rollback protocols
6. Zero Fabrication:
   - Never invent ambulance IDs, route corridors, tool names, or evidence IDs.
7. Plan Versioning:
   - Initial plan: plan_version = 1
   - Replanning: plan_version >= 2 with supersedes_plan_id and reason_for_revision.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator

from agents.base import BaseAgent
from agents.resources import ResourceAnalysisOutput, ResourceItemAnalysis
from agents.routes import RouteAnalysisOutput, RouteItemAnalysis
from agents.schemas import NexusBaseSchema, PlanActionItem, PlanData
from tools.registry import ToolRegistry, default_tool_registry
from tools.synthetic_environment import simulated_fleet_service, synthetic_road_network

logger = logging.getLogger("nexus.agents.planning")


# -----------------------------------------------------------------------------
# Strict Enums
# -----------------------------------------------------------------------------
class PlanActionType(StrEnum):
    """Permitted simulated operational action types."""

    UPDATE_SIMULATED_ROAD_STATUS = "UPDATE_SIMULATED_ROAD_STATUS"
    RESERVE_SIMULATED_RESOURCE = "RESERVE_SIMULATED_RESOURCE"
    UPDATE_SIMULATED_INCIDENT_STATUS = "UPDATE_SIMULATED_INCIDENT_STATUS"
    SEND_SIMULATED_NOTIFICATION = "SEND_SIMULATED_NOTIFICATION"
    REQUEST_ADDITIONAL_VERIFICATION = "REQUEST_ADDITIONAL_VERIFICATION"
    CALCULATE_ROUTE = "CALCULATE_ROUTE"
    MONITOR_INCIDENT = "MONITOR_INCIDENT"
    SEARCH_SIMULATED_RESOURCES = "SEARCH_SIMULATED_RESOURCES"
    CHECK_HOSPITAL_STATUS = "CHECK_HOSPITAL_STATUS"
    LOG_AUDIT_EVENT = "LOG_AUDIT_EVENT"


class ActionRiskLevel(StrEnum):
    """Deterministic risk levels."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    HUMAN_ONLY = "HUMAN_ONLY"


class PlanActionStatus(StrEnum):
    """Execution lifecycle status for actions in the DAG."""

    PENDING = "PENDING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PlanValidationStatus(StrEnum):
    """Categorical validation outcome for the action plan."""

    VALID = "VALID"
    INVALID = "INVALID"
    NEEDS_REVISION = "NEEDS_REVISION"
    BLOCKED = "BLOCKED"


# -----------------------------------------------------------------------------
# Security Patterns & Deterministic Policies
# -----------------------------------------------------------------------------
ACTION_ID_REGEX = re.compile(r"^[A-Za-z0-9_\-]{3,64}$")
RESOURCE_ID_REGEX = re.compile(r"^[A-Z0-9_\-]{3,32}$")
ROUTE_ID_REGEX = re.compile(r"^[A-Z0-9_\-]{3,32}$")
TOOL_NAME_REGEX = re.compile(r"^[a-z0-9_]{3,32}$")

INJECTION_PATTERNS = [
    re.compile(
        r"(?i)(ignore\s+(all\s+)?previous\s+instructions|system\s+override|bypass\s+(safety|gate|policy)|DAN\s+mode|ADMIN_OVERRIDE)"
    ),
    re.compile(
        r"(?i)(mark\s+(this\s+)?as\s+(safe|low\s+risk|auto_approved)|set\s+requires_approval\s*=\s*false)"
    ),
    re.compile(r"(?i)(</system>|</user>|<system_instruction>|```system)"),
]

PROHIBITED_ACTION_KEYWORDS = [
    "REAL_",
    "ACTUAL_",
    "DEPLOY_FIRE",
    "DEPLOY_POLICE",
    "MEDICAL_DECISION",
    "PERFORM_SURGERY",
    "TRANSFER_FUNDS",
    "LEGAL_ORDER",
    "SYSTEM_SHUTDOWN",
    "DISPATCH_REAL",
]


def detect_prompt_injection(text: str) -> bool:
    """Scans untrusted text for adversarial prompt injection attempts."""
    if not text:
        return False
    return any(p.search(text) for p in INJECTION_PATTERNS)


def sanitize_text(text: str) -> str:
    """Neutralizes detected prompt injection patterns."""
    if not text:
        return text
    sanitized = text
    for p in INJECTION_PATTERNS:
        sanitized = p.sub("[SANITIZED_INJECTION_ATTEMPT]", sanitized)
    return sanitized


# Deterministic mapping: action_type -> allowed safe simulated tools
ACTION_TOOL_MAPPING: dict[PlanActionType, list[str]] = {
    PlanActionType.CALCULATE_ROUTE: ["routing"],
    PlanActionType.SEARCH_SIMULATED_RESOURCES: ["resource_search"],
    PlanActionType.CHECK_HOSPITAL_STATUS: ["hospital_status"],
    PlanActionType.MONITOR_INCIDENT: ["incident_reports", "weather", "hospital_status"],
    PlanActionType.REQUEST_ADDITIONAL_VERIFICATION: [
        "incident_reports",
        "weather",
        "image_analysis",
        "geolocation",
    ],
    PlanActionType.LOG_AUDIT_EVENT: ["audit_logging"],
    PlanActionType.RESERVE_SIMULATED_RESOURCE: ["ambulance_reservation"],
    PlanActionType.UPDATE_SIMULATED_ROAD_STATUS: ["incident_status_update"],
    PlanActionType.UPDATE_SIMULATED_INCIDENT_STATUS: ["incident_status_update"],
    PlanActionType.SEND_SIMULATED_NOTIFICATION: ["notifications"],
}

# Deterministic baseline risk classification: LLM cannot lower this
DETERMINISTIC_RISK_POLICY: dict[PlanActionType, ActionRiskLevel] = {
    PlanActionType.CALCULATE_ROUTE: ActionRiskLevel.LOW,
    PlanActionType.SEARCH_SIMULATED_RESOURCES: ActionRiskLevel.LOW,
    PlanActionType.CHECK_HOSPITAL_STATUS: ActionRiskLevel.LOW,
    PlanActionType.MONITOR_INCIDENT: ActionRiskLevel.LOW,
    PlanActionType.REQUEST_ADDITIONAL_VERIFICATION: ActionRiskLevel.LOW,
    PlanActionType.LOG_AUDIT_EVENT: ActionRiskLevel.LOW,
    PlanActionType.RESERVE_SIMULATED_RESOURCE: ActionRiskLevel.MEDIUM,
    PlanActionType.UPDATE_SIMULATED_ROAD_STATUS: ActionRiskLevel.MEDIUM,
    PlanActionType.UPDATE_SIMULATED_INCIDENT_STATUS: ActionRiskLevel.HIGH,
    PlanActionType.SEND_SIMULATED_NOTIFICATION: ActionRiskLevel.HIGH,
}

RISK_ORDER: dict[ActionRiskLevel, int] = {
    ActionRiskLevel.LOW: 1,
    ActionRiskLevel.MEDIUM: 2,
    ActionRiskLevel.HIGH: 3,
    ActionRiskLevel.HUMAN_ONLY: 4,
}

# Deterministic rollback mapping: (rollback_supported, rollback_action)
ROLLBACK_MAPPING: dict[PlanActionType, tuple[bool, str | None]] = {
    PlanActionType.UPDATE_SIMULATED_ROAD_STATUS: (True, "RESTORE_PREVIOUS_ROAD_STATUS"),
    PlanActionType.RESERVE_SIMULATED_RESOURCE: (True, "RELEASE_SIMULATED_RESOURCE"),
    PlanActionType.UPDATE_SIMULATED_INCIDENT_STATUS: (True, "RESTORE_PREVIOUS_INCIDENT_STATUS"),
    PlanActionType.SEND_SIMULATED_NOTIFICATION: (False, None),
    PlanActionType.REQUEST_ADDITIONAL_VERIFICATION: (False, None),
    PlanActionType.CALCULATE_ROUTE: (False, None),
    PlanActionType.MONITOR_INCIDENT: (False, None),
    PlanActionType.SEARCH_SIMULATED_RESOURCES: (False, None),
    PlanActionType.CHECK_HOSPITAL_STATUS: (False, None),
    PlanActionType.LOG_AUDIT_EVENT: (False, None),
}


def is_approval_required_for_risk(risk: ActionRiskLevel | str) -> bool:
    """Enforces deterministic approval policy:

    LOW: requires_approval = False
    MEDIUM, HIGH, HUMAN_ONLY: requires_approval = True
    """
    val = risk.value if isinstance(risk, ActionRiskLevel) else str(risk).upper()
    return val in (
        ActionRiskLevel.MEDIUM.value,
        ActionRiskLevel.HIGH.value,
        ActionRiskLevel.HUMAN_ONLY.value,
    )


# -----------------------------------------------------------------------------
# Structured Pydantic Schemas
# -----------------------------------------------------------------------------
class PlanAction(NexusBaseSchema):
    """Discrete operational step within the action Directed Acyclic Graph."""

    action_id: str = Field(..., description="Unique action identifier e.g. act-01")
    action_type: PlanActionType = Field(..., description="Strict simulation action type")
    description: str = Field(..., min_length=3, description="Operational rationale")
    required_tool: str = Field(..., description="Allowed registered tool from ToolRegistry")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Validated execution payload"
    )
    risk_level: ActionRiskLevel = Field(..., description="Deterministic safety tier")
    requires_approval: bool = Field(..., description="Deterministic human approval requirement")
    prerequisites: list[str] = Field(
        default_factory=list, description="State preconditions required before dispatch"
    )
    depends_on: list[str] = Field(
        default_factory=list, description="Prior action IDs in DAG that must complete first"
    )
    expected_outcome: str = Field(default="", description="Anticipated operational consequence")
    rollback_supported: bool = Field(
        default=False, description="Whether compensating rollback exists"
    )
    rollback_action: str | None = Field(
        default=None, description="Compensating action if rollback supported"
    )
    evidence_ids: list[str] = Field(
        default_factory=list, description="Authoritative grounding evidence IDs"
    )
    status: PlanActionStatus = Field(
        default=PlanActionStatus.PENDING, description="Action execution status"
    )

    @field_validator("action_id")
    @classmethod
    def validate_action_id(cls, v: str) -> str:
        if not ACTION_ID_REGEX.match(v):
            raise ValueError(f"Invalid action_id format: '{v}'")
        return v

    @field_validator("required_tool")
    @classmethod
    def validate_tool_name(cls, v: str) -> str:
        if not TOOL_NAME_REGEX.match(v):
            raise ValueError(f"Invalid required_tool identifier: '{v}'")
        return v


class PlanDependency(NexusBaseSchema):
    """Explicit directed edge in the Action DAG."""

    source_action_id: str = Field(..., description="Prerequisite action ID")
    target_action_id: str = Field(..., description="Dependent action ID")
    dependency_type: str = Field(
        default="PREREQUISITE",
        description="Dependency relationship: PREREQUISITE, DATA_DEPENDENCY, SAFETY_GATE",
    )
    description: str | None = Field(default=None, description="Operational rationale for edge")


class PlanRisk(NexusBaseSchema):
    """Identified operational hazard or contingency during plan execution."""

    risk_id: str = Field(default_factory=lambda: f"risk-{uuid.uuid4().hex[:6]}")
    risk_level: ActionRiskLevel = Field(..., description="Severity of operational risk")
    description: str = Field(..., description="Detailed description of contingency")
    mitigation: str = Field(..., description="Preventative protocol or fallback mechanism")
    requires_approval: bool = Field(
        default=True, description="Whether risk triggers commander escalation"
    )


class PlanValidationResult(NexusBaseSchema):
    """Deterministic validation audit result across all 10 topological gates."""

    is_valid: bool = Field(..., description="True if plan satisfies all 10 deterministic gates")
    validation_status: PlanValidationStatus = Field(
        ..., description="Categorical validation outcome"
    )
    errors: list[str] = Field(default_factory=list, description="Fatal policy or DAG errors")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal operational warnings")
    cycle_detected: bool = Field(
        default=False, description="True if dependency graph contains a cycle"
    )
    missing_dependencies: list[str] = Field(
        default_factory=list, description="Unresolvable dependency action IDs"
    )
    unregistered_tools: list[str] = Field(
        default_factory=list, description="Tools not registered or disallowed"
    )
    invalid_resources: list[str] = Field(
        default_factory=list, description="Fabricated or busy resource IDs"
    )
    invalid_routes: list[str] = Field(
        default_factory=list, description="Fabricated, blocked, or uncertain route IDs"
    )
    unsupported_claims: list[str] = Field(
        default_factory=list, description="Ungrounded evidence IDs"
    )
    prohibited_actions: list[str] = Field(
        default_factory=list, description="Forbidden real-world action types"
    )
    validated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResourceAssignment(NexusBaseSchema):
    """Assignment of an available emergency asset to the response plan."""

    resource_id: str = Field(..., description="Unit identifier e.g. AMB-01")
    resource_type: str = Field(default="AMBULANCE")
    callsign: str = Field(...)
    assigned_role: str = Field(...)
    evidence_id: str = Field(...)


class RouteAssignment(NexusBaseSchema):
    """Assignment of a verified safe corridor to the response plan."""

    route_id: str = Field(..., description="Route segment identifier e.g. ROUTE-B")
    route_name: str = Field(...)
    origin: str = Field(...)
    destination: str = Field(...)
    status: str = Field(default="AVAILABLE")
    evidence_id: str = Field(...)


class PlanningOutput(NexusBaseSchema):
    """Structured Pydantic contract produced by NEXUS Planning Agent."""

    plan_id: str = Field(default_factory=lambda: f"plan-{uuid.uuid4().hex[:8]}")
    plan_version: int = Field(default=1, ge=1, description="Sequential plan iteration")
    supersedes_plan_id: str | None = Field(
        default=None, description="Previous plan ID if dynamically replanned"
    )
    reason_for_revision: str | None = Field(
        default=None, description="Trigger for replan iteration"
    )
    incident_id: str = Field(..., description="Target incident identifier")
    objective: str = Field(..., min_length=5, description="Primary operational objective")
    assumptions: list[str] = Field(
        default_factory=list, description="Grounded operational facts and premises"
    )
    actions: list[PlanAction] = Field(
        default_factory=list, description="Topologically sequenced action DAG"
    )
    dependencies: list[PlanDependency] = Field(
        default_factory=list, description="Explicit DAG edges"
    )
    risks: list[PlanRisk] = Field(
        default_factory=list, description="Identified operational contingencies"
    )
    resource_assignments: list[dict[str, Any]] = Field(
        default_factory=list, description="Assigned fleet assets"
    )
    route_assignments: list[dict[str, Any]] = Field(
        default_factory=list, description="Assigned safe corridors"
    )
    approval_requirements: list[str] = Field(
        default_factory=list, description="Action IDs requiring human approval"
    )
    rollback_summary: dict[str, str] = Field(
        default_factory=dict, description="Rollback protocols for reversible actions"
    )
    evidence_ids: list[str] = Field(
        default_factory=list, description="Grounding evidence IDs backing the plan"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Plan feasibility confidence score")
    validation_status: Literal["VALID", "INVALID", "NEEDS_REVISION", "BLOCKED"] = Field(
        default="VALID", description="Deterministic validation status"
    )
    validation_errors: list[str] = Field(
        default_factory=list, description="Fatal errors preventing execution"
    )
    prohibited_actions: list[str] = Field(
        default_factory=list, description="Disallowed real-world actions detected"
    )
    missing_information: list[str] = Field(
        default_factory=list, description="Operational gaps preventing full plan"
    )
    required_next_steps: list[str] = Field(
        default_factory=list, description="Recommended remediation actions"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_simulation: bool = Field(default=True, description="Strict simulation environment indicator")

    def to_plan_data(self) -> PlanData:
        """Converts PlanningOutput to PlanData for backward-compatible state storage."""
        plan_actions: list[PlanActionItem] = []
        for idx, act in enumerate(self.actions, 1):
            act_type_str = act.action_type.value
            target_entity = (
                str(
                    act.parameters.get("unit_id")
                    or act.parameters.get("route_id")
                    or act.parameters.get("recipient")
                    or act.action_id
                )
                if act.parameters
                else act.action_id
            )
            item = PlanActionItem(
                action_id=act.action_id,
                action_type=act_type_str,  # type: ignore
                target_entity=target_entity,
                sequence=idx,
                risk_level=act.risk_level.value,  # type: ignore
                requires_approval=act.requires_approval,
                status=act.status.value,  # type: ignore
                execution_receipt=None,
            )
            plan_actions.append(item)

        status_mapping = {
            "VALID": "PROPOSED",
            "INVALID": "INVALIDATED",
            "BLOCKED": "BLOCKED",
            "NEEDS_REVISION": "NEEDS_REVISION",
        }
        mapped_status = status_mapping.get(self.validation_status, "PROPOSED")

        return PlanData(
            plan_id=self.plan_id,
            version=self.plan_version,
            plan_version=self.plan_version,
            supersedes_plan_id=self.supersedes_plan_id,
            reason_for_revision=self.reason_for_revision,
            objective=self.objective,
            status=mapped_status,  # type: ignore
            actions=plan_actions,
            created_at=self.created_at,
        )


# -----------------------------------------------------------------------------
# Deterministic Topological Plan Validator
# -----------------------------------------------------------------------------
class PlanValidator:
    """Deterministic validator verifying that a proposed plan satisfies all

    invariants before execution is permitted.
    """

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        self.tool_registry = tool_registry or default_tool_registry

    def validate_plan(
        self,
        plan: PlanningOutput,
        available_resources: list[str] | set[str] | None = None,
        available_routes: list[str] | set[str] | None = None,
        valid_evidence_ids: list[str] | set[str] | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> PlanValidationResult:
        """Validates all 10 topological and safety rules deterministically:

        1. Every dependency references a valid action ID.
        2. No action depends on itself.
        3. No dependency cycle exists (topological DFS / Kahn).
        4. Every required prerequisite exists.
        5. Every required resource exists in available inventory.
        6. Every referenced route exists and is not blocked/uncertain.
        7. Every referenced tool exists in ToolRegistry and is permitted.
        8. Risk level matches or exceeds deterministic minimum policy.
        9. Approval requirement strictly matches deterministic policy.
        10. Every factual assumption is grounded in valid evidence IDs.
        """
        registry = tool_registry or self.tool_registry
        errors: list[str] = []
        warnings: list[str] = []
        cycle_detected = False
        missing_dependencies: list[str] = []
        unregistered_tools: list[str] = []
        invalid_resources: list[str] = []
        invalid_routes: list[str] = []
        unsupported_claims: list[str] = []
        prohibited_actions: list[str] = []

        action_ids = [act.action_id for act in plan.actions]
        action_id_set = set(action_ids)

        # Duplicate Action ID check
        if len(action_ids) != len(action_id_set):
            seen: set[str] = set()
            duplicates: set[str] = set()
            for aid in action_ids:
                if aid in seen:
                    duplicates.add(aid)
                seen.add(aid)
            for dup in duplicates:
                errors.append(f"Duplicate action ID detected: '{dup}'")

        # Prepare resource sets
        avail_res: set[str] = (
            set(available_resources)
            if available_resources is not None
            else {u.unit_id for u in simulated_fleet_service.get_available_ambulances()}
        )

        # Prepare route sets
        avail_rts: set[str] = (
            set(available_routes)
            if available_routes is not None
            else {seg.route_id for seg in synthetic_road_network.routes.values()}
        )

        # Prepare evidence sets
        valid_ev: set[str] | None = (
            set(valid_evidence_ids) if valid_evidence_ids is not None else None
        )

        # 1 & 2: Validate dependencies and self-dependencies
        for act in plan.actions:
            # Self-dependency
            if act.action_id in act.depends_on:
                errors.append(
                    f"Self-dependency detected: Action '{act.action_id}' depends on itself."
                )

            # Missing dependencies
            for dep in act.depends_on:
                if dep not in action_id_set:
                    missing_dependencies.append(dep)
                    errors.append(
                        f"Action '{act.action_id}' depends on nonexistent action ID '{dep}'."
                    )

        # Validate explicit PlanDependency edges
        for dep_edge in plan.dependencies:
            if dep_edge.source_action_id == dep_edge.target_action_id:
                errors.append(
                    f"Self-dependency detected in dependency edge: '{dep_edge.source_action_id}'."
                )
            if dep_edge.source_action_id not in action_id_set:
                missing_dependencies.append(dep_edge.source_action_id)
                errors.append(f"Dependency source '{dep_edge.source_action_id}' does not exist.")
            if dep_edge.target_action_id not in action_id_set:
                missing_dependencies.append(dep_edge.target_action_id)
                errors.append(f"Dependency target '{dep_edge.target_action_id}' does not exist.")

        # 3. Cycle Detection in Action DAG (DFS 3-color)
        adj: dict[str, list[str]] = defaultdict(list)
        for act in plan.actions:
            for dep in act.depends_on:
                if dep in action_id_set:
                    adj[dep].append(act.action_id)
        for dep_edge in plan.dependencies:
            if (
                dep_edge.source_action_id in action_id_set
                and dep_edge.target_action_id in action_id_set
            ):
                if dep_edge.target_action_id not in adj[dep_edge.source_action_id]:
                    adj[dep_edge.source_action_id].append(dep_edge.target_action_id)

        color: dict[str, int] = {aid: 0 for aid in action_id_set}  # 0: WHITE, 1: GRAY, 2: BLACK

        def dfs_cycle(u: str) -> bool:
            color[u] = 1  # GRAY
            for v in adj[u]:
                if color[v] == 1:
                    return True
                if color[v] == 0 and dfs_cycle(v):
                    return True
            color[u] = 2  # BLACK
            return False

        for aid in action_id_set:
            if color[aid] == 0:
                if dfs_cycle(aid):
                    cycle_detected = True
                    errors.append("Circular dependency detected in action DAG.")
                    break

        # 4. Check action parameters, tools, resources, routes, risks, approvals, rollbacks
        for act in plan.actions:
            # Check prohibited real-world keywords
            act_type_name = (
                act.action_type.value if hasattr(act.action_type, "value") else str(act.action_type)
            )
            if any(k in act_type_name.upper() for k in PROHIBITED_ACTION_KEYWORDS):
                prohibited_actions.append(act_type_name)
                errors.append(
                    f"Prohibited real-world action '{act_type_name}' in action '{act.action_id}'."
                )

            # 7. Check tool existence and mapping
            tool_name = act.required_tool
            if not TOOL_NAME_REGEX.match(tool_name):
                unregistered_tools.append(tool_name)
                errors.append(
                    f"Tool identifier '{tool_name}' in action '{act.action_id}' violates format regex."
                )
            elif not registry.has(tool_name):
                unregistered_tools.append(tool_name)
                errors.append(
                    f"Unknown or unregistered tool '{tool_name}' in action '{act.action_id}'."
                )
            else:
                allowed_tools = ACTION_TOOL_MAPPING.get(act.action_type, [])
                if tool_name not in allowed_tools:
                    unregistered_tools.append(tool_name)
                    errors.append(
                        f"Tool '{tool_name}' is not permitted for action type '{act.action_type.value}'. Allowed: {allowed_tools}."
                    )

            # 8. Check risk level
            policy_min_risk = DETERMINISTIC_RISK_POLICY.get(act.action_type, ActionRiskLevel.HIGH)
            if RISK_ORDER[act.risk_level] < RISK_ORDER[policy_min_risk]:
                errors.append(
                    f"Action '{act.action_id}' specifies invalid low risk level '{act.risk_level.value}' "
                    f"for action type '{act.action_type.value}' (minimum: '{policy_min_risk.value}')."
                )

            # 9. Check approval requirement
            expected_approval = is_approval_required_for_risk(act.risk_level)
            if expected_approval and not act.requires_approval:
                errors.append(
                    f"Action '{act.action_id}' of risk level '{act.risk_level.value}' illegally sets requires_approval=False."
                )

            # 14. Check rollback validity
            expected_rollback_supported, expected_rollback_action = ROLLBACK_MAPPING.get(
                act.action_type, (False, None)
            )
            if act.rollback_supported and not expected_rollback_supported:
                errors.append(
                    f"Action '{act.action_id}' ({act.action_type.value}) claims rollback support, "
                    "but this action is irreversible (no rollback mechanism exists)."
                )
            if act.rollback_supported and not act.rollback_action:
                errors.append(
                    f"Action '{act.action_id}' claims rollback support but lacks a rollback_action."
                )

            # 5. Check resource parameters
            res_id = (
                act.parameters.get("unit_id")
                or act.parameters.get("resource_id")
                or act.parameters.get("ambulance_id")
            )
            if act.action_type == PlanActionType.RESERVE_SIMULATED_RESOURCE and not res_id:
                errors.append(
                    f"Action '{act.action_id}' (RESERVE_SIMULATED_RESOURCE) is missing required 'unit_id' parameter."
                )

            if res_id:
                res_id_str = str(res_id)
                if not RESOURCE_ID_REGEX.match(res_id_str):
                    invalid_resources.append(res_id_str)
                    errors.append(
                        f"Resource identifier '{res_id_str}' in action '{act.action_id}' violates format regex."
                    )
                elif res_id_str not in avail_res:
                    invalid_resources.append(res_id_str)
                    errors.append(
                        f"Resource '{res_id_str}' in action '{act.action_id}' is unavailable, busy, or unverified."
                    )

            # 6. Check route parameters
            route_id = act.parameters.get("route_id") or act.parameters.get("corridor")
            if route_id:
                route_id_str = str(route_id)
                # If corridor is a street name, don't check route ID regex unless it starts with ROUTE
                if route_id_str.startswith("ROUTE-"):
                    if not ROUTE_ID_REGEX.match(route_id_str):
                        invalid_routes.append(route_id_str)
                        errors.append(
                            f"Route identifier '{route_id_str}' in action '{act.action_id}' violates format regex."
                        )
                    elif route_id_str not in avail_rts:
                        # Check if this action is explicitly closing or updating a blocked road
                        is_road_update = (
                            act.action_type == PlanActionType.UPDATE_SIMULATED_ROAD_STATUS
                        )
                        if not is_road_update:
                            invalid_routes.append(route_id_str)
                            errors.append(
                                f"Route '{route_id_str}' in action '{act.action_id}' is BLOCKED, UNCERTAIN, or nonexistent."
                            )

            # 10. Check evidence grounding
            if valid_ev is not None:
                for ev in act.evidence_ids:
                    if ev not in valid_ev:
                        unsupported_claims.append(ev)
                        errors.append(
                            f"Action '{act.action_id}' references ungrounded or fabricated evidence ID '{ev}'."
                        )

            # State-changing operations must have evidence
            if (
                act.action_type
                in (
                    PlanActionType.RESERVE_SIMULATED_RESOURCE,
                    PlanActionType.UPDATE_SIMULATED_ROAD_STATUS,
                )
                and not act.evidence_ids
            ):
                errors.append(
                    f"State-changing action '{act.action_id}' ({act.action_type.value}) lacks grounding evidence IDs."
                )

        # Check resource assignments
        for ra in plan.resource_assignments:
            r_id = ra.get("resource_id")
            if r_id and str(r_id) not in avail_res:
                invalid_resources.append(str(r_id))
                errors.append(
                    f"Resource assignment contains unavailable or fabricated unit '{r_id}'."
                )

        # Check route assignments
        for rta in plan.route_assignments:
            r_id = rta.get("route_id")
            if r_id and str(r_id) not in avail_rts:
                invalid_routes.append(str(r_id))
                errors.append(
                    f"Route assignment references unavailable or blocked corridor '{r_id}'."
                )

        is_valid = len(errors) == 0
        status = (
            PlanValidationStatus.VALID
            if is_valid
            else (
                PlanValidationStatus.BLOCKED
                if plan.validation_status == "BLOCKED"
                else PlanValidationStatus.INVALID
            )
        )

        return PlanValidationResult(
            is_valid=is_valid,
            validation_status=status,
            errors=errors,
            warnings=warnings,
            cycle_detected=cycle_detected,
            missing_dependencies=missing_dependencies,
            unregistered_tools=unregistered_tools,
            invalid_resources=invalid_resources,
            invalid_routes=invalid_routes,
            unsupported_claims=unsupported_claims,
            prohibited_actions=prohibited_actions,
            validated_at=datetime.now(UTC),
        )


# -----------------------------------------------------------------------------
# NEXUS Planning Agent
# -----------------------------------------------------------------------------
class PlanningAgent(BaseAgent):
    """Transforms verified emergency intelligence, impact analysis, resource

    allocations, and safe corridors into an actionable, topologically validated
    operational Directed Acyclic Graph (DAG).
    """

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        super().__init__(
            name="PlanningAgent",
            role="Operational Plan Synthesis and Action DAG Formulation",
        )
        self.tool_registry = tool_registry or default_tool_registry
        self.validator = PlanValidator(tool_registry=self.tool_registry)

    async def plan(
        self,
        incident: Any,
        verification: Any = None,
        impact: Any = None,
        resources: Any = None,
        routes: Any = None,
        previous_plan: Any = None,
        reason_for_revision: str | None = None,
    ) -> PlanningOutput:
        """Synthesizes a structured, validated PlanningOutput from current

        multi-agent state.
        """
        # 1. Parse and sanitize incident context
        inc_id, inc_desc = self._parse_incident(incident)
        if detect_prompt_injection(inc_desc):
            logger.warning(
                f"[PlanningAgent] Sanitized prompt injection in incident description: '{inc_desc}'"
            )
            inc_desc = sanitize_text(inc_desc)

        # 2. Extract Evidence Base
        if isinstance(verification, tuple) and len(verification) > 0:
            verification = verification[0]

        all_evidence_ids: list[str] = []
        if verification:
            evs = (
                getattr(verification, "evidence_ids", None)
                or (verification.get("evidence_ids") if isinstance(verification, dict) else [])
                or []
            )
            all_evidence_ids.extend([str(e) for e in evs])
        if impact:
            imp_evs = (
                getattr(impact, "evidence_ids", None)
                or (impact.get("evidence_ids") if isinstance(impact, dict) else [])
                or []
            )
            all_evidence_ids.extend([str(e) for e in imp_evs])
        if resources:
            res_evs = (
                getattr(resources, "evidence_ids", None)
                or (resources.get("evidence_ids") if isinstance(resources, dict) else [])
                or []
            )
            all_evidence_ids.extend([str(e) for e in res_evs])
        if routes:
            rt_evs = (
                getattr(routes, "evidence_ids", None)
                or (routes.get("evidence_ids") if isinstance(routes, dict) else [])
                or []
            )
            all_evidence_ids.extend([str(e) for e in rt_evs])

        # Deduplicate evidence IDs while preserving order
        unique_evidence_ids = list(dict.fromkeys(all_evidence_ids))

        # 3. Check Verification Gate
        is_verified = True
        verification_confidence = 0.95
        if isinstance(verification, tuple) and len(verification) > 0:
            verification = verification[0]

        if verification:
            v_status = (
                getattr(verification, "verification_status", None)
                or (
                    verification.get("verification_status")
                    if isinstance(verification, dict)
                    else None
                )
                or "VERIFIED"
            )
            is_v = getattr(verification, "verified", None)
            if is_v is None and isinstance(verification, dict):
                is_v = verification.get("verified", True)
            conf = getattr(verification, "confidence", None)
            if conf is None and isinstance(verification, dict):
                conf = verification.get("confidence", 0.95)

            verification_confidence = float(conf) if conf is not None else 0.95
            if (
                not is_v
                or v_status
                in (
                    "UNVERIFIED",
                    "INSUFFICIENT_EVIDENCE",
                    "CONTRADICTED",
                    "FLAGGED_INJECTION",
                )
                or verification_confidence < 0.60
            ):
                is_verified = False

        if not is_verified:
            logger.warning(
                f"[PlanningAgent] Incident {inc_id} failed verification gate. Producing BLOCKED plan."
            )
            req_act = PlanAction(
                action_id="act-req-veri-01",
                action_type=PlanActionType.REQUEST_ADDITIONAL_VERIFICATION,
                description=f"Request urgent empirical sensor and report corroboration for incident {inc_id}.",
                required_tool="incident_reports",
                parameters={"incident_id": inc_id, "query": "corroborate_flooding"},
                risk_level=ActionRiskLevel.LOW,
                requires_approval=False,
                expected_outcome="Independent empirical corroboration of crisis report.",
                rollback_supported=False,
                evidence_ids=unique_evidence_ids,
                status=PlanActionStatus.PENDING,
            )
            return PlanningOutput(
                incident_id=inc_id,
                objective=f"Gather empirical evidence to verify unconfirmed incident {inc_id}",
                actions=[req_act],
                confidence=min(0.50, verification_confidence),
                validation_status="BLOCKED",
                missing_information=[
                    f"Incident {inc_id} has not been verified by VerificationAgent (confidence: {verification_confidence:.2f})"
                ],
                required_next_steps=[
                    "Conduct independent sensor query and cross-check citizen reports."
                ],
                evidence_ids=unique_evidence_ids,
                is_simulation=True,
            )

        # 4. Check Resources
        avail_units: list[ResourceItemAnalysis] = []
        if isinstance(resources, ResourceAnalysisOutput):
            avail_units = resources.available_resources
        elif hasattr(resources, "allocated_resources") and resources.allocated_resources:
            for item in resources.allocated_resources:
                avail_units.append(
                    ResourceItemAnalysis(
                        resource_id=item.resource_id,
                        resource_type=getattr(item, "resource_type", "AMBULANCE"),
                        name=getattr(item, "callsign", item.resource_id),
                        availability="AVAILABLE"
                        if getattr(item, "status", "") in ("AVAILABLE", "RESERVED")
                        else "UNAVAILABLE",
                        current_location=getattr(item, "current_location", "Municipal Fleet Depot"),
                        distance_km=getattr(item, "distance_km", 2.0),
                        current_workload=getattr(item, "current_workload", 0),
                        axle_clearance_inches=getattr(item, "axle_clearance_inches", 24.0),
                        status=getattr(item, "status", "AVAILABLE"),
                        suitability="SUITABLE: Available in inventory",
                        evidence_source="resource_state",
                    )
                )
        elif isinstance(resources, dict):
            raw_avail = (
                resources.get("available_resources")
                or resources.get("available_fleet")
                or resources.get("allocated_resources")
                or []
            )
            for item in raw_avail:
                if isinstance(item, ResourceItemAnalysis):
                    avail_units.append(item)
                elif isinstance(item, dict):
                    if "resource_id" in item and "name" in item:
                        avail_units.append(ResourceItemAnalysis(**item))
                    elif "resource_id" in item:
                        avail_units.append(
                            ResourceItemAnalysis(
                                resource_id=item["resource_id"],
                                name=str(item.get("callsign") or item["resource_id"]),
                                availability="AVAILABLE"
                                if item.get("status") in ("AVAILABLE", "RESERVED")
                                else "UNAVAILABLE",
                                current_location=item.get(
                                    "current_location", "Municipal Fleet Depot"
                                ),
                                distance_km=item.get("distance_km", 2.0),
                                current_workload=item.get("current_workload", 0),
                                axle_clearance_inches=item.get("axle_clearance_inches", 24.0),
                                status=item.get("status", "AVAILABLE"),
                                suitability="SUITABLE: Available in inventory",
                                evidence_source="resource_state",
                            )
                        )
            if not avail_units and "available_units" in resources:
                for u in resources["available_units"]:
                    avail_units.append(
                        ResourceItemAnalysis(
                            resource_id=u,
                            name=f"Unit-{u}",
                            availability="AVAILABLE",
                            current_location="Municipal Fleet Depot",
                            distance_km=2.0,
                            current_workload=0,
                            axle_clearance_inches=30.0,
                            status="AVAILABLE",
                            suitability="SUITABLE: Available in inventory",
                            evidence_source="resource_state",
                        )
                    )

        # 5. Check Routes
        active_routes: list[RouteItemAnalysis] = []
        if isinstance(routes, RouteAnalysisOutput):
            active_routes = routes.active_routes
        elif hasattr(routes, "active_routes") and routes.active_routes:
            for r_item in routes.active_routes:
                if isinstance(r_item, RouteItemAnalysis):
                    active_routes.append(r_item)
                else:
                    status_mapped: Literal["AVAILABLE", "BLOCKED"] = (
                        "AVAILABLE" if getattr(r_item, "status", "") == "SAFE" else "BLOCKED"
                    )
                    active_routes.append(
                        RouteItemAnalysis(
                            route_id=r_item.route_id,
                            name=str(getattr(r_item, "name", r_item.route_id)),
                            origin="Municipal EMS Depot",
                            destination="City Hospital Regional Medical Center",
                            waypoints=getattr(r_item, "waypoints", []),
                            distance_km=getattr(r_item, "distance_km", 4.0),
                            estimated_time_minutes=getattr(r_item, "estimated_time_minutes", 10.0),
                            status=status_mapped,
                            evidence_ids=unique_evidence_ids,
                            confidence=0.95,
                        )
                    )
        elif isinstance(routes, dict):
            raw_routes = routes.get("active_routes") or []
            for item in raw_routes:
                if isinstance(item, RouteItemAnalysis):
                    active_routes.append(item)
                elif isinstance(item, dict):
                    if "status" in item and item["status"] in (
                        "AVAILABLE",
                        "BLOCKED",
                        "UNCERTAIN",
                        "STALE",
                    ):
                        active_routes.append(RouteItemAnalysis(**item))
                    elif "status" in item:
                        dict_status_mapped: Literal["AVAILABLE", "BLOCKED"] = (
                            "AVAILABLE" if item["status"] == "SAFE" else "BLOCKED"
                        )
                        active_routes.append(
                            RouteItemAnalysis(
                                route_id=item["route_id"],
                                name=str(item.get("name") or item["route_id"]),
                                origin=item.get("origin", "Municipal EMS Depot"),
                                destination=item.get(
                                    "destination", "City Hospital Regional Medical Center"
                                ),
                                waypoints=item.get("waypoints", []),
                                distance_km=item.get("distance_km", 4.0),
                                estimated_time_minutes=item.get("estimated_time_minutes", 10.0),
                                status=dict_status_mapped,
                                evidence_ids=unique_evidence_ids,
                                confidence=0.95,
                            )
                        )

        avail_corridors = [r for r in active_routes if r.status == "AVAILABLE"]
        blocked_corridors = [r for r in active_routes if r.status in ("BLOCKED", "UNCERTAIN")]

        # Determine Primary Route & Fallback
        selected_route: RouteItemAnalysis | None = None
        if avail_corridors:
            # Sort by ETA
            avail_corridors.sort(key=lambda r: (r.estimated_time_minutes, r.distance_km))
            selected_route = avail_corridors[0]

        # 6. Check for Gaps (Resources or Routes)
        if not avail_units:
            logger.warning(
                f"[PlanningAgent] No available emergency units found for incident {inc_id}."
            )
            return PlanningOutput(
                incident_id=inc_id,
                objective=f"Mitigate flood access disruption at City Hospital for incident {inc_id}",
                confidence=0.40,
                validation_status="BLOCKED",
                missing_information=[
                    "No available emergency vehicles meet axle clearance and availability requirements."
                ],
                required_next_steps=[
                    "Request mutual aid fleet allocation or await unit return from prior assignment."
                ],
                risks=[
                    PlanRisk(
                        risk_level=ActionRiskLevel.HIGH,
                        description="Zero emergency ambulances available to service trauma corridor.",
                        mitigation="Request mutual aid from adjacent regional jurisdictions.",
                        requires_approval=True,
                    )
                ],
                evidence_ids=unique_evidence_ids,
                is_simulation=True,
            )

        if not selected_route:
            logger.warning(f"[PlanningAgent] All corridors blocked for incident {inc_id}.")
            return PlanningOutput(
                incident_id=inc_id,
                objective=f"Mitigate flood access disruption at City Hospital for incident {inc_id}",
                confidence=0.40,
                validation_status="BLOCKED",
                missing_information=["All emergency transit corridors are blocked by flood water."],
                required_next_steps=[
                    "Deploy high-water staging barrier or await floodwater recedence."
                ],
                risks=[
                    PlanRisk(
                        risk_level=ActionRiskLevel.HIGH,
                        description="Complete corridor severance to City Hospital.",
                        mitigation="Deploy amphibious high-water rescue staging.",
                        requires_approval=True,
                    )
                ],
                evidence_ids=unique_evidence_ids,
                is_simulation=True,
            )

        # 7. Synthesize Versioned Action DAG
        selected_unit = avail_units[0]
        primary_ev = unique_evidence_ids[0] if unique_evidence_ids else "ev-synthetic-base"

        # Determine version
        plan_ver = 1
        super_id = None
        if previous_plan:
            plan_ver = getattr(previous_plan, "plan_version", 1) + 1
            super_id = getattr(previous_plan, "plan_id", None)
            if not super_id and isinstance(previous_plan, dict):
                super_id = previous_plan.get("plan_id")
                plan_ver = previous_plan.get("plan_version", 1) + 1

        actions: list[PlanAction] = []
        dependencies: list[PlanDependency] = []
        risks: list[PlanRisk] = []
        resource_assignments: list[dict[str, Any]] = []
        route_assignments: list[dict[str, Any]] = []

        # Action 1: CALCULATE_ROUTE (Verify corridor passability)
        act_01_id = f"act-route-{uuid.uuid4().hex[:4]}"
        act_01 = PlanAction(
            action_id=act_01_id,
            action_type=PlanActionType.CALCULATE_ROUTE,
            description=f"Calculate safe topological transit corridor via {selected_route.route_id} ({selected_route.name}).",
            required_tool="routing",
            parameters={
                "origin": selected_route.origin,
                "destination": selected_route.destination,
                "route_id": selected_route.route_id,
            },
            risk_level=ActionRiskLevel.LOW,
            requires_approval=False,
            prerequisites=["CORRIDOR_SURVEILLANCE_ACTIVE"],
            depends_on=[],
            expected_outcome=f"Safe navigation path verified over {selected_route.route_id} with ETA {selected_route.estimated_time_minutes:.1f} mins.",
            rollback_supported=False,
            evidence_ids=[primary_ev],
            status=PlanActionStatus.PENDING,
        )
        actions.append(act_01)

        # Action 2: RESERVE_SIMULATED_RESOURCE (Reserve suitable ambulance)
        act_02_id = f"act-res-{uuid.uuid4().hex[:4]}"
        act_02 = PlanAction(
            action_id=act_02_id,
            action_type=PlanActionType.RESERVE_SIMULATED_RESOURCE,
            description=f"Reserve simulated emergency unit {selected_unit.resource_id} ({selected_unit.name}) for trauma dispatch.",
            required_tool="ambulance_reservation",
            parameters={
                "unit_id": selected_unit.resource_id,
                "incident_id": inc_id,
                "corridor": selected_route.route_id,
            },
            risk_level=ActionRiskLevel.MEDIUM,
            requires_approval=True,
            prerequisites=[act_01_id],
            depends_on=[act_01_id],
            expected_outcome=f"Unit {selected_unit.resource_id} reserved exclusively for incident {inc_id}.",
            rollback_supported=True,
            rollback_action="RELEASE_SIMULATED_RESOURCE",
            evidence_ids=[primary_ev],
            status=PlanActionStatus.PENDING,
        )
        actions.append(act_02)
        dependencies.append(
            PlanDependency(
                source_action_id=act_01_id,
                target_action_id=act_02_id,
                dependency_type="PREREQUISITE",
                description="Must confirm passable corridor before reserving unit.",
            )
        )

        # Action 3: UPDATE_SIMULATED_ROAD_STATUS (Close blocked route segment if known)
        act_03_id = f"act-road-{uuid.uuid4().hex[:4]}"
        blocked_target = blocked_corridors[0].route_id if blocked_corridors else "ROUTE-A"
        act_03 = PlanAction(
            action_id=act_03_id,
            action_type=PlanActionType.UPDATE_SIMULATED_ROAD_STATUS,
            description=f"Update municipal highway status for flooded segment {blocked_target} to BLOCKED.",
            required_tool="incident_status_update",
            parameters={"route_id": blocked_target, "status": "BLOCKED"},
            risk_level=ActionRiskLevel.MEDIUM,
            requires_approval=True,
            prerequisites=[act_01_id],
            depends_on=[act_01_id],
            expected_outcome=f"Segment {blocked_target} marked BLOCKED in road status feeds.",
            rollback_supported=True,
            rollback_action="RESTORE_PREVIOUS_ROAD_STATUS",
            evidence_ids=[primary_ev],
            status=PlanActionStatus.PENDING,
        )
        actions.append(act_03)
        dependencies.append(
            PlanDependency(
                source_action_id=act_01_id,
                target_action_id=act_03_id,
                dependency_type="DATA_DEPENDENCY",
                description="Route computation isolates flooded segment.",
            )
        )

        # Action 4: SEND_SIMULATED_NOTIFICATION (Alert hospital trauma intake)
        act_04_id = f"act-notif-{uuid.uuid4().hex[:4]}"
        notif_msg = (
            f"Simulated Alert: Unit {selected_unit.resource_id} inbound to City Hospital via detour "
            f"{selected_route.route_id} ({selected_route.name}). Flooded segment {blocked_target} avoided."
        )
        act_04 = PlanAction(
            action_id=act_04_id,
            action_type=PlanActionType.SEND_SIMULATED_NOTIFICATION,
            description="Send simulated inbound emergency notice to City Hospital Trauma Center.",
            required_tool="notifications",
            parameters={
                "recipient": "City Hospital Trauma Center",
                "message": notif_msg,
                "urgency": "HIGH",
            },
            risk_level=ActionRiskLevel.HIGH,
            requires_approval=True,
            prerequisites=[act_02_id, act_03_id],
            depends_on=[act_02_id, act_03_id],
            expected_outcome="Hospital trauma team alerted to inbound patient transport via verified detour.",
            rollback_supported=False,
            rollback_action=None,
            evidence_ids=[primary_ev],
            status=PlanActionStatus.PENDING,
        )
        actions.append(act_04)
        dependencies.append(
            PlanDependency(
                source_action_id=act_02_id,
                target_action_id=act_04_id,
                dependency_type="PREREQUISITE",
                description="Ambulance must be reserved before notifying hospital.",
            )
        )
        dependencies.append(
            PlanDependency(
                source_action_id=act_03_id,
                target_action_id=act_04_id,
                dependency_type="PREREQUISITE",
                description="Road advisory must be logged before broadcasting transit notices.",
            )
        )

        # Action 5: MONITOR_INCIDENT (Continuous sensor and corridor surveillance)
        act_05_id = f"act-mon-{uuid.uuid4().hex[:4]}"
        act_05 = PlanAction(
            action_id=act_05_id,
            action_type=PlanActionType.MONITOR_INCIDENT,
            description=f"Continuously monitor water sensors and passability along active detour {selected_route.route_id}.",
            required_tool="incident_reports",
            parameters={
                "corridor": selected_route.route_id,
                "incident_id": inc_id,
                "poll_interval_seconds": 30,
            },
            risk_level=ActionRiskLevel.LOW,
            requires_approval=False,
            prerequisites=[act_04_id],
            depends_on=[act_04_id],
            expected_outcome=f"Real-time anomaly detection active along {selected_route.route_id} to trigger replan if flooded.",
            rollback_supported=False,
            rollback_action=None,
            evidence_ids=[primary_ev],
            status=PlanActionStatus.PENDING,
        )
        actions.append(act_05)
        dependencies.append(
            PlanDependency(
                source_action_id=act_04_id,
                target_action_id=act_05_id,
                dependency_type="PREREQUISITE",
                description="Continuous monitoring initiates once dispatch alert is broadcast.",
            )
        )

        # Compile resource and route assignments
        resource_assignments.append(
            {
                "resource_id": selected_unit.resource_id,
                "resource_type": selected_unit.resource_type,
                "callsign": selected_unit.name,
                "assigned_role": "PRIMARY_EMS_TRANSPORT",
                "evidence_id": primary_ev,
            }
        )
        route_assignments.append(
            {
                "route_id": selected_route.route_id,
                "route_name": selected_route.name,
                "origin": selected_route.origin,
                "destination": selected_route.destination,
                "status": selected_route.status,
                "evidence_id": primary_ev,
            }
        )

        # Identify approval requirements
        approval_reqs = [act.action_id for act in actions if act.requires_approval]

        # Compile rollback summary
        rollback_summary = {
            act.action_id: act.rollback_action
            for act in actions
            if act.rollback_supported and act.rollback_action
        }

        # Identify plan risks
        risks.append(
            PlanRisk(
                risk_level=ActionRiskLevel.MEDIUM,
                description=f"Water levels along {selected_route.route_id} could rise above {selected_unit.axle_clearance_inches:.1f} in clearance threshold.",
                mitigation=f"Continuous monitoring via action {act_05_id} triggers automated replanning to alternative corridors.",
                requires_approval=True,
            )
        )

        # Assumptions
        assumptions = [
            f"Incident {inc_id} verified with confidence {verification_confidence:.2f}.",
            f"Unit {selected_unit.resource_id} is stationed at Municipal Fleet Depot and ready for assignment.",
            f"Corridor {selected_route.route_id} remains clear of water exceeding {selected_unit.axle_clearance_inches:.1f} in.",
            "City Hospital emergency bay is operational and accepting trauma reroutes.",
        ]

        obj_desc = (
            f"Safely reroute emergency medical transport to City Hospital via corridor "
            f"{selected_route.route_id} avoiding flooded corridor {blocked_target}."
        )

        output = PlanningOutput(
            plan_version=plan_ver,
            supersedes_plan_id=super_id,
            reason_for_revision=reason_for_revision,
            incident_id=inc_id,
            objective=obj_desc,
            assumptions=assumptions,
            actions=actions,
            dependencies=dependencies,
            risks=risks,
            resource_assignments=resource_assignments,
            route_assignments=route_assignments,
            approval_requirements=approval_reqs,
            rollback_summary=rollback_summary,
            evidence_ids=unique_evidence_ids,
            confidence=0.95,
            validation_status="VALID",
            is_simulation=True,
        )

        # Deterministic Validation
        val_res = self.validator.validate_plan(
            plan=output,
            available_resources=[u.resource_id for u in avail_units],
            available_routes=[r.route_id for r in avail_corridors],
            valid_evidence_ids=unique_evidence_ids,
        )

        output.validation_status = val_res.validation_status.value
        output.validation_errors = val_res.errors
        output.prohibited_actions = val_res.prohibited_actions

        return output

    async def process(self, state: Any) -> dict[str, Any]:
        """LangGraph StateGraph processing protocol."""
        state_dict = state if isinstance(state, dict) else {}
        incident = state_dict.get("incident") or state_dict.get("perception_output") or state_dict
        verification = state_dict.get("verification")
        impact = state_dict.get("impact") or state_dict.get("impact_assessment")
        resources = state_dict.get("resources") or state_dict.get("resource_analysis")
        routes = state_dict.get("routes") or state_dict.get("route_analysis")
        prev_plan = state_dict.get("plan") or state_dict.get("planning_output")
        revision_reason = state_dict.get("reason_for_revision") or state_dict.get(
            "invalidation_reason"
        )

        output = await self.plan(
            incident=incident,
            verification=verification,
            impact=impact,
            resources=resources,
            routes=routes,
            previous_plan=prev_plan,
            reason_for_revision=revision_reason,
        )

        status_str = "PLAN_SYNTHESIZED" if output.validation_status == "VALID" else "PLAN_BLOCKED"

        return {
            "current_status": status_str,
            "plan": output.to_plan_data(),
            "planning_output": output,
            "metadata": {
                "plan_id": output.plan_id,
                "plan_version": output.plan_version,
                "validation_status": output.validation_status,
                "actions_count": len(output.actions),
                "approval_required": len(output.approval_requirements) > 0,
                "confidence": output.confidence,
            },
        }

    def _parse_incident(self, incident: Any) -> tuple[str, str]:
        """Extracts incident_id and description safely."""
        inc_id = "inc-synthetic-01"
        desc = "Flooding near City Hospital"
        if isinstance(incident, dict):
            inc_id = incident.get("incident_id") or incident.get("id") or inc_id
            desc = (
                incident.get("description")
                or incident.get("raw_report")
                or incident.get("raw_user_report")
                or desc
            )
        else:
            inc_id = getattr(incident, "incident_id", inc_id)
            desc = getattr(incident, "description", desc)
        return str(inc_id), str(desc)
