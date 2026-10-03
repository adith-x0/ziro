"""NEXUS Agent State Model for LangGraph State Machine.

Implements the central, strongly typed, serializable `NexusState` representing
the complete operational lifecycle across all 14 structured domain facets:
1. incident
2. evidence
3. verification
4. impact
5. resources
6. routes
7. plan
8. risk_assessment
9. approval
10. actions
11. monitoring
12. memory
13. errors
14. metadata
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agents.schemas import (
    ActionExecutionReceipt,
    AgentErrorItem,
    ApprovalRecordData,
    EvidenceItem,
    ExecutionMetadata,
    ImpactAssessment,
    IncidentData,
    MemoryState,
    MonitoringData,
    PlanData,
    ResourceState,
    RiskAssessmentData,
    RoutingState,
    VerificationResult,
)


# -----------------------------------------------------------------------------
# LangGraph Canonical TypedDict State
# -----------------------------------------------------------------------------
class NexusState(TypedDict, total=False):
    """Canonical typed dictionary schema for LangGraph StateGraph nodes."""

    incident: IncidentData | dict[str, Any] | None
    evidence: list[EvidenceItem] | list[dict[str, Any]]
    verification: VerificationResult | dict[str, Any] | None
    impact: ImpactAssessment | dict[str, Any] | None
    resources: ResourceState | dict[str, Any] | None
    routes: RoutingState | dict[str, Any] | None
    plan: PlanData | dict[str, Any] | None
    risk_assessment: RiskAssessmentData | dict[str, Any] | None
    approval: ApprovalRecordData | dict[str, Any] | None
    actions: list[ActionExecutionReceipt] | list[dict[str, Any]]
    monitoring: MonitoringData | dict[str, Any] | None
    memory: MemoryState | dict[str, Any] | None
    errors: list[AgentErrorItem] | list[dict[str, Any]]
    metadata: ExecutionMetadata | dict[str, Any] | None


# -----------------------------------------------------------------------------
# Strongly-Typed Pydantic Model for Strict Validation & Persistence
# -----------------------------------------------------------------------------
class NexusStateModel(BaseModel):
    """Pydantic model representing fully-validated state with schema enforcement."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
    )

    incident: IncidentData | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    verification: VerificationResult | None = None
    impact: ImpactAssessment | None = None
    resources: ResourceState = Field(default_factory=ResourceState)
    routes: RoutingState = Field(default_factory=RoutingState)
    plan: PlanData | None = None
    risk_assessment: RiskAssessmentData | None = None
    approval: ApprovalRecordData | None = None
    actions: list[ActionExecutionReceipt] = Field(default_factory=list)
    monitoring: MonitoringData | None = None
    memory: MemoryState = Field(default_factory=MemoryState)
    errors: list[AgentErrorItem] = Field(default_factory=list)
    metadata: ExecutionMetadata = Field(default_factory=ExecutionMetadata)

    def to_langgraph_dict(self) -> NexusState:
        """Converts model to serializable dictionary suitable for LangGraph checkpoints."""
        return self.model_dump(mode="json")  # type: ignore

    @classmethod
    def from_langgraph_dict(cls, data: dict[str, Any]) -> NexusStateModel:
        """Validates raw state dictionary into validated model."""
        return cls.model_validate(data)


# -----------------------------------------------------------------------------
# Helper & State Management Functions
# -----------------------------------------------------------------------------
def create_empty_nexus_state() -> NexusState:
    """Returns an empty state dictionary with baseline metadata."""
    now = datetime.now(UTC)
    meta = ExecutionMetadata(
        current_step="START",
        created_at=now,
        updated_at=now,
    )
    return {
        "incident": None,
        "evidence": [],
        "verification": None,
        "impact": None,
        "resources": ResourceState().model_dump(mode="json"),
        "routes": RoutingState().model_dump(mode="json"),
        "plan": None,
        "risk_assessment": None,
        "approval": None,
        "actions": [],
        "monitoring": None,
        "memory": MemoryState().model_dump(mode="json"),
        "errors": [],
        "metadata": meta.model_dump(mode="json"),
    }


def create_initial_nexus_state(
    incident: IncidentData | dict[str, Any],
    thread_id: str | None = None,
) -> NexusState:
    """Initializes a new state with perceived incident data."""
    empty = create_empty_nexus_state()
    inc_data = incident if isinstance(incident, dict) else incident.model_dump(mode="json")
    empty["incident"] = inc_data
    meta = empty.get("metadata")
    if thread_id and isinstance(meta, dict):
        meta["thread_id"] = thread_id
        empty["metadata"] = meta
    return empty


def validate_nexus_state(state: NexusState | dict[str, Any]) -> NexusStateModel:
    """Strictly validates a state dictionary against the NexusStateModel schema."""
    try:
        return NexusStateModel.model_validate(state)
    except ValidationError as err:
        raise ValueError(f"NexusState validation failure: {err}") from err


def serialize_nexus_state(state: NexusState | NexusStateModel) -> str:
    """Serializes a state object or dictionary to a JSON string."""
    if isinstance(state, NexusStateModel):
        return state.model_dump_json(indent=2)
    validated = NexusStateModel.model_validate(state)
    return validated.model_dump_json(indent=2)


def deserialize_nexus_state(raw_json: str | dict[str, Any]) -> NexusStateModel:
    """Deserializes a JSON string or raw dict into a validated NexusStateModel."""
    if isinstance(raw_json, str):
        return NexusStateModel.model_validate_json(raw_json)
    return NexusStateModel.model_validate(raw_json)


def merge_nexus_state(base: NexusState, updates: dict[str, Any]) -> NexusState:
    """Implements safe state merging for LangGraph nodes with metadata hop increment."""
    merged = dict(base)
    merged.update(updates)

    # Automatically increment hops and update timestamp in metadata
    meta = merged.get("metadata")
    if isinstance(meta, dict):
        meta["updated_at"] = datetime.now(UTC).isoformat()
        meta["agent_hops"] = meta.get("agent_hops", 0) + 1
        merged["metadata"] = meta
    elif isinstance(meta, ExecutionMetadata):
        meta.updated_at = datetime.now(UTC)
        meta.agent_hops += 1
        merged["metadata"] = meta

    return merged  # type: ignore
