import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.enums import (
    ActionRiskLevel,
    ActionStatus,
    AgentStatus,
    ApprovalStatus,
    EvidenceType,
    IncidentSeverity,
    IncidentStatus,
)
from database.session import Base


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(UTC)


class IncidentModel(Base):
    """Primary incident entity representing real-world crisis event."""

    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[IncidentSeverity] = mapped_column(
        Enum(IncidentSeverity, native_enum=False, length=32),
        default=IncidentSeverity.HIGH,
        nullable=False,
    )
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, native_enum=False, length=32),
        default=IncidentStatus.INGESTED,
        nullable=False,
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    address_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    # Relationships
    evidence: Mapped[list["EvidenceModel"]] = relationship(
        "EvidenceModel", back_populates="incident", cascade="all, delete-orphan"
    )
    routes: Mapped[list["RouteModel"]] = relationship("RouteModel", back_populates="incident")
    plans: Mapped[list["PlanModel"]] = relationship(
        "PlanModel", back_populates="incident", cascade="all, delete-orphan"
    )
    actions: Mapped[list["ActionModel"]] = relationship(
        "ActionModel", back_populates="incident", cascade="all, delete-orphan"
    )
    approvals: Mapped[list["ApprovalModel"]] = relationship(
        "ApprovalModel", back_populates="incident", cascade="all, delete-orphan"
    )
    agent_runs: Mapped[list["AgentRunModel"]] = relationship(
        "AgentRunModel", back_populates="incident", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLogModel"]] = relationship(
        "AuditLogModel", back_populates="incident"
    )

    __table_args__ = (
        Index("ix_incidents_status_severity", "status", "severity"),
        Index("ix_incidents_coords", "latitude", "longitude"),
        Index("ix_incidents_created_at", "created_at"),
    )


class EvidenceModel(Base):
    """Corroborating sensory and citizen evidence items."""

    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(
        Enum(EvidenceType, native_enum=False, length=32), nullable=False, index=True
    )
    source_identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    telemetry_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    incident: Mapped["IncidentModel"] = relationship("IncidentModel", back_populates="evidence")


class ResourceModel(Base):
    """Emergency resources including hospitals, ambulances, pumps, and shelters."""

    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="available", index=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    base_station_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    specs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        Index("ix_resources_type_status", "resource_type", "status"),
        Index("ix_resources_coords", "latitude", "longitude"),
    )


class RouteModel(Base):
    """Calculated topological emergency transit routes."""

    __tablename__ = "routes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    route_name: Mapped[str] = mapped_column(String(128), nullable=False)
    origin_name: Mapped[str] = mapped_column(String(128), nullable=False)
    destination_name: Mapped[str] = mapped_column(String(128), nullable=False)
    waypoints: Mapped[list[Any]] = mapped_column(JSON, default=list)
    total_distance_km: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_transit_time_min: Mapped[float] = mapped_column(Float, default=0.0)
    max_water_clearance_supported_inches: Mapped[float] = mapped_column(Float, default=24.0)
    is_compromised: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    compromised_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    incident: Mapped[Optional["IncidentModel"]] = relationship(
        "IncidentModel", back_populates="routes"
    )


class PlanModel(Base):
    """Synthesized operational response plans."""

    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PROPOSED", index=True)
    risk_assessment_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    incident: Mapped["IncidentModel"] = relationship("IncidentModel", back_populates="plans")
    actions: Mapped[list["ActionModel"]] = relationship(
        "ActionModel", back_populates="plan", cascade="all, delete-orphan"
    )
    approvals: Mapped[list["ApprovalModel"]] = relationship("ApprovalModel", back_populates="plan")

    __table_args__ = (Index("ix_plans_incident_version", "incident_id", "version"),)


class ActionModel(Base):
    """Discrete operational action items executing against simulated actuators."""

    __tablename__ = "actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence_order: Mapped[int] = mapped_column(Integer, default=1)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_entity: Mapped[str] = mapped_column(String(128), nullable=False)
    risk_level: Mapped[ActionRiskLevel] = mapped_column(
        Enum(ActionRiskLevel, native_enum=False, length=32),
        default=ActionRiskLevel.TIER_1_AUTO,
        nullable=False,
        index=True,
    )
    status: Mapped[ActionStatus] = mapped_column(
        Enum(ActionStatus, native_enum=False, length=32),
        default=ActionStatus.PENDING,
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    execution_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    execution_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    plan: Mapped["PlanModel"] = relationship("PlanModel", back_populates="actions")
    incident: Mapped["IncidentModel"] = relationship("IncidentModel", back_populates="actions")
    approval: Mapped[Optional["ApprovalModel"]] = relationship(
        "ApprovalModel", back_populates="action", uselist=False
    )


class ApprovalModel(Base):
    """Human-in-the-loop commander sign-off records."""

    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    action_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("actions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    risk_level: Mapped[ActionRiskLevel] = mapped_column(
        Enum(ActionRiskLevel, native_enum=False, length=32),
        default=ActionRiskLevel.TIER_4_HIGH,
        nullable=False,
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, native_enum=False, length=32),
        default=ApprovalStatus.PENDING,
        nullable=False,
        index=True,
    )
    reviewer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewer_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_token: Mapped[str | None] = mapped_column(String(128), nullable=True)

    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    incident: Mapped["IncidentModel"] = relationship("IncidentModel", back_populates="approvals")
    plan: Mapped[Optional["PlanModel"]] = relationship("PlanModel", back_populates="approvals")
    action: Mapped[Optional["ActionModel"]] = relationship("ActionModel", back_populates="approval")


class AgentRunModel(Base):
    """Tracks execution of specific agent tasks in the LangGraph pipeline."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, native_enum=False, length=32),
        default=AgentStatus.IDLE,
        nullable=False,
        index=True,
    )
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    execution_time_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    incident: Mapped["IncidentModel"] = relationship("IncidentModel", back_populates="agent_runs")
    events: Mapped[list["AgentEventModel"]] = relationship(
        "AgentEventModel", back_populates="agent_run", cascade="all, delete-orphan"
    )


class AgentEventModel(Base):
    """Fine-grained thoughts, tool calls, and state diff events during an agent run."""

    __tablename__ = "agent_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    event_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )

    agent_run: Mapped["AgentRunModel"] = relationship("AgentRunModel", back_populates="events")


class AuditLogModel(Base):
    """Immutable, SHA-256 chained audit records for post-incident review."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action_name: Mapped[str] = mapped_column(String(64), nullable=False)
    state_diff: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )

    incident: Mapped[Optional["IncidentModel"]] = relationship(
        "IncidentModel", back_populates="audit_logs"
    )


class MemoryRecordModel(Base):
    """Vector and playbook memory storage for pgvector similarity search."""

    __tablename__ = "memory_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    embedding_vector: Mapped[list[float]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (Index("ix_memory_cat_ref", "category", "reference_id"),)
