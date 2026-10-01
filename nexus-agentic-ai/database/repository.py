import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.enums import (
    ActionRiskLevel,
    ActionStatus,
    AgentStatus,
    ApprovalStatus,
    EvidenceType,
    IncidentSeverity,
    IncidentStatus,
)
from database.models import (
    ActionModel,
    AgentEventModel,
    AgentRunModel,
    ApprovalModel,
    AuditLogModel,
    EvidenceModel,
    IncidentModel,
    MemoryRecordModel,
    PlanModel,
    ResourceModel,
    RouteModel,
    utc_now,
)


class IncidentRepository:
    """CRUD and analytical queries for Incidents."""

    @staticmethod
    async def create_incident(
        session: AsyncSession,
        title: str,
        description: str | None = None,
        severity: IncidentSeverity = IncidentSeverity.HIGH,
        status: IncidentStatus = IncidentStatus.INGESTED,
        latitude: float = 0.0,
        longitude: float = 0.0,
        address_reference: str | None = None,
        metadata_payload: dict[str, Any] | None = None,
    ) -> IncidentModel:
        incident = IncidentModel(
            title=title,
            description=description,
            severity=severity,
            status=status,
            latitude=latitude,
            longitude=longitude,
            address_reference=address_reference,
            metadata_payload=metadata_payload or {},
        )
        session.add(incident)
        await session.flush()
        return incident

    @staticmethod
    async def get_by_id(session: AsyncSession, incident_id: uuid.UUID) -> IncidentModel | None:
        return await session.get(IncidentModel, incident_id)

    @staticmethod
    async def get_with_details(
        session: AsyncSession, incident_id: uuid.UUID
    ) -> IncidentModel | None:
        stmt = (
            select(IncidentModel)
            .where(IncidentModel.id == incident_id)
            .options(
                selectinload(IncidentModel.evidence),
                selectinload(IncidentModel.routes),
                selectinload(IncidentModel.plans).selectinload(PlanModel.actions),
                selectinload(IncidentModel.approvals),
                selectinload(IncidentModel.audit_logs),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_incidents(
        session: AsyncSession,
        status: IncidentStatus | None = None,
        severity: IncidentSeverity | None = None,
        limit: int = 50,
    ) -> list[IncidentModel]:
        stmt = select(IncidentModel)
        if status:
            stmt = stmt.where(IncidentModel.status == status)
        if severity:
            stmt = stmt.where(IncidentModel.severity == severity)
        stmt = stmt.order_by(desc(IncidentModel.created_at)).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def update_status(
        session: AsyncSession, incident_id: uuid.UUID, new_status: IncidentStatus
    ) -> IncidentModel | None:
        incident = await session.get(IncidentModel, incident_id)
        if incident:
            incident.status = new_status
            incident.updated_at = utc_now()
            await session.flush()
        return incident


class EvidenceRepository:
    """Management of incoming sensory and citizen evidence."""

    @staticmethod
    async def add_evidence(
        session: AsyncSession,
        incident_id: uuid.UUID,
        evidence_type: EvidenceType,
        source_identifier: str,
        telemetry_data: dict[str, Any],
        confidence_score: float = 0.0,
        verified: bool = False,
        verification_notes: str | None = None,
    ) -> EvidenceModel:
        evidence = EvidenceModel(
            incident_id=incident_id,
            evidence_type=evidence_type,
            source_identifier=source_identifier,
            telemetry_data=telemetry_data,
            confidence_score=confidence_score,
            verified=verified,
            verification_notes=verification_notes,
        )
        session.add(evidence)
        await session.flush()
        return evidence

    @staticmethod
    async def list_by_incident(
        session: AsyncSession, incident_id: uuid.UUID
    ) -> list[EvidenceModel]:
        stmt = (
            select(EvidenceModel)
            .where(EvidenceModel.incident_id == incident_id)
            .order_by(desc(EvidenceModel.captured_at))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def verify_evidence(
        session: AsyncSession,
        evidence_id: uuid.UUID,
        confidence_score: float,
        notes: str,
    ) -> EvidenceModel | None:
        evidence = await session.get(EvidenceModel, evidence_id)
        if evidence:
            evidence.verified = True
            evidence.confidence_score = confidence_score
            evidence.verification_notes = notes
            await session.flush()
        return evidence


class ResourceRepository:
    """Registry of municipal depots, hospitals, ambulances, and pumps."""

    @staticmethod
    async def create_resource(
        session: AsyncSession,
        name: str,
        resource_type: str,
        capacity: int = 1,
        status: str = "available",
        latitude: float = 0.0,
        longitude: float = 0.0,
        base_station_id: str | None = None,
        specs: dict[str, Any] | None = None,
    ) -> ResourceModel:
        resource = ResourceModel(
            name=name,
            resource_type=resource_type,
            capacity=capacity,
            status=status,
            latitude=latitude,
            longitude=longitude,
            base_station_id=base_station_id,
            specs=specs or {},
        )
        session.add(resource)
        await session.flush()
        return resource

    @staticmethod
    async def list_resources(
        session: AsyncSession,
        resource_type: str | None = None,
        status: str | None = None,
    ) -> list[ResourceModel]:
        stmt = select(ResourceModel)
        if resource_type:
            stmt = stmt.where(ResourceModel.resource_type == resource_type)
        if status:
            stmt = stmt.where(ResourceModel.status == status)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def update_status(
        session: AsyncSession, resource_id: uuid.UUID, new_status: str
    ) -> ResourceModel | None:
        res = await session.get(ResourceModel, resource_id)
        if res:
            res.status = new_status
            res.updated_at = utc_now()
            await session.flush()
        return res


class RouteRepository:
    """Storage and querying of calculated topological routes."""

    @staticmethod
    async def create_route(
        session: AsyncSession,
        route_name: str,
        origin_name: str,
        destination_name: str,
        waypoints: list[Any],
        total_distance_km: float,
        estimated_transit_time_min: float,
        max_water_clearance_supported_inches: float = 24.0,
        incident_id: uuid.UUID | None = None,
    ) -> RouteModel:
        route = RouteModel(
            incident_id=incident_id,
            route_name=route_name,
            origin_name=origin_name,
            destination_name=destination_name,
            waypoints=waypoints,
            total_distance_km=total_distance_km,
            estimated_transit_time_min=estimated_transit_time_min,
            max_water_clearance_supported_inches=max_water_clearance_supported_inches,
        )
        session.add(route)
        await session.flush()
        return route

    @staticmethod
    async def get_by_incident(session: AsyncSession, incident_id: uuid.UUID) -> list[RouteModel]:
        stmt = select(RouteModel).where(RouteModel.incident_id == incident_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def mark_compromised(
        session: AsyncSession, route_id: uuid.UUID, reason: str
    ) -> RouteModel | None:
        route = await session.get(RouteModel, route_id)
        if route:
            route.is_compromised = True
            route.compromised_reason = reason
            route.updated_at = utc_now()
            await session.flush()
        return route


class PlanRepository:
    """Management of synthesized multi-action operational plans."""

    @staticmethod
    async def create_plan(
        session: AsyncSession,
        incident_id: uuid.UUID,
        title: str,
        version: int = 1,
        summary_narrative: str | None = None,
        status: str = "PROPOSED",
        risk_assessment_summary: dict[str, Any] | None = None,
    ) -> PlanModel:
        plan = PlanModel(
            incident_id=incident_id,
            version=version,
            title=title,
            summary_narrative=summary_narrative,
            status=status,
            risk_assessment_summary=risk_assessment_summary or {},
        )
        session.add(plan)
        await session.flush()
        return plan

    @staticmethod
    async def get_latest_plan(session: AsyncSession, incident_id: uuid.UUID) -> PlanModel | None:
        stmt = (
            select(PlanModel)
            .where(PlanModel.incident_id == incident_id)
            .options(selectinload(PlanModel.actions))
            .order_by(desc(PlanModel.version))
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def update_status(
        session: AsyncSession, plan_id: uuid.UUID, new_status: str
    ) -> PlanModel | None:
        plan = await session.get(PlanModel, plan_id)
        if plan:
            plan.status = new_status
            plan.updated_at = utc_now()
            await session.flush()
        return plan


class ActionRepository:
    """Intervention action items linked to plans and incidents."""

    @staticmethod
    async def create_action(
        session: AsyncSession,
        plan_id: uuid.UUID,
        incident_id: uuid.UUID,
        sequence_order: int,
        action_type: str,
        target_entity: str,
        risk_level: ActionRiskLevel,
        description: str,
        execution_payload: dict[str, Any] | None = None,
        approval_required: bool = False,
    ) -> ActionModel:
        action = ActionModel(
            plan_id=plan_id,
            incident_id=incident_id,
            sequence_order=sequence_order,
            action_type=action_type,
            target_entity=target_entity,
            risk_level=risk_level,
            description=description,
            execution_payload=execution_payload or {},
            approval_required=approval_required,
            status=ActionStatus.PENDING,
        )
        session.add(action)
        await session.flush()
        return action

    @staticmethod
    async def list_by_plan(session: AsyncSession, plan_id: uuid.UUID) -> list[ActionModel]:
        stmt = (
            select(ActionModel)
            .where(ActionModel.plan_id == plan_id)
            .order_by(ActionModel.sequence_order)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def update_status(
        session: AsyncSession,
        action_id: uuid.UUID,
        new_status: ActionStatus,
        execution_result: dict[str, Any] | None = None,
    ) -> ActionModel | None:
        action = await session.get(ActionModel, action_id)
        if action:
            action.status = new_status
            if execution_result:
                action.execution_result = execution_result
            action.updated_at = utc_now()
            await session.flush()
        return action


class ApprovalRepository:
    """Human commander decision registry."""

    @staticmethod
    async def request_approval(
        session: AsyncSession,
        incident_id: uuid.UUID,
        risk_level: ActionRiskLevel = ActionRiskLevel.TIER_4_HIGH,
        action_id: uuid.UUID | None = None,
        plan_id: uuid.UUID | None = None,
    ) -> ApprovalModel:
        approval = ApprovalModel(
            incident_id=incident_id,
            action_id=action_id,
            plan_id=plan_id,
            risk_level=risk_level,
            status=ApprovalStatus.PENDING,
        )
        session.add(approval)
        await session.flush()
        return approval

    @staticmethod
    async def decide_approval(
        session: AsyncSession,
        approval_id: uuid.UUID,
        reviewer_id: str,
        reviewer_role: str,
        decision: str,
        rationale: str,
    ) -> ApprovalModel | None:
        approval = await session.get(ApprovalModel, approval_id)
        if approval:
            approval.reviewer_id = reviewer_id
            approval.reviewer_role = reviewer_role
            approval.decision = decision
            approval.rationale = rationale
            approval.status = (
                ApprovalStatus.APPROVED if decision == "APPROVED" else ApprovalStatus.REJECTED
            )
            approval.decided_at = utc_now()
            approval.decision_token = f"tok-{uuid.uuid4().hex[:16]}"
            await session.flush()
        return approval

    @staticmethod
    async def list_pending(
        session: AsyncSession, incident_id: uuid.UUID | None = None
    ) -> list[ApprovalModel]:
        stmt = select(ApprovalModel).where(ApprovalModel.status == ApprovalStatus.PENDING)
        if incident_id:
            stmt = stmt.where(ApprovalModel.incident_id == incident_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())


class AgentRunRepository:
    """Tracking agent execution cycles and micro-events."""

    @staticmethod
    async def start_run(
        session: AsyncSession,
        incident_id: uuid.UUID,
        agent_name: str,
        input_payload: dict[str, Any],
    ) -> AgentRunModel:
        run = AgentRunModel(
            incident_id=incident_id,
            agent_name=agent_name,
            input_payload=input_payload,
            status=AgentStatus.RUNNING,
        )
        session.add(run)
        await session.flush()
        return run

    @staticmethod
    async def complete_run(
        session: AsyncSession,
        run_id: uuid.UUID,
        status: AgentStatus,
        output_payload: dict[str, Any],
        execution_time_ms: float,
        error_message: str | None = None,
    ) -> AgentRunModel | None:
        run = await session.get(AgentRunModel, run_id)
        if run:
            run.status = status
            run.output_payload = output_payload
            run.execution_time_ms = execution_time_ms
            run.error_message = error_message
            run.completed_at = utc_now()
            await session.flush()
        return run

    @staticmethod
    async def log_event(
        session: AsyncSession,
        run_id: uuid.UUID,
        event_type: str,
        agent_name: str,
        message: str,
        event_data: dict[str, Any] | None = None,
    ) -> AgentEventModel:
        event = AgentEventModel(
            run_id=run_id,
            event_type=event_type,
            agent_name=agent_name,
            message=message,
            event_data=event_data or {},
        )
        session.add(event)
        await session.flush()
        return event

    @staticmethod
    async def list_events_for_run(
        session: AsyncSession, run_id: uuid.UUID
    ) -> list[AgentEventModel]:
        stmt = (
            select(AgentEventModel)
            .where(AgentEventModel.run_id == run_id)
            .order_by(AgentEventModel.timestamp)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


class AuditLogRepository:
    """Tamper-evident chained SHA-256 audit ledger."""

    @staticmethod
    def _format_timestamp(ts: datetime | str) -> str:
        """Format datetime canonically to avoid database serialization differences."""
        if isinstance(ts, datetime):
            clean_ts: datetime = ts
            if clean_ts.tzinfo is not None:
                clean_ts = clean_ts.astimezone(UTC).replace(tzinfo=None)
            return str(clean_ts.strftime("%Y-%m-%d %H:%M:%S.%f"))
        return str(ts)

    @staticmethod
    def _compute_hash(
        previous_hash: str,
        actor_id: str,
        action: str,
        state_diff: dict[str, Any],
        ts_str: str,
    ) -> str:
        payload = (
            f"{previous_hash}|{actor_id}|{action}|{json.dumps(state_diff, sort_keys=True)}|{ts_str}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    async def append_log(
        cls,
        session: AsyncSession,
        actor_type: str,
        actor_id: str,
        action_name: str,
        state_diff: dict[str, Any],
        incident_id: uuid.UUID | None = None,
    ) -> AuditLogModel:
        # Retrieve previous log to chain hash
        stmt = select(AuditLogModel).order_by(desc(AuditLogModel.timestamp)).limit(1)
        result = await session.execute(stmt)
        last_log = result.scalar_one_or_none()
        previous_hash = last_log.signature_hash if last_log else "GENESIS_NEXUS_CHAIN_ROOT_0000"

        now = utc_now()
        ts_str = cls._format_timestamp(now)
        sig = cls._compute_hash(previous_hash, actor_id, action_name, state_diff, ts_str)

        audit_entry = AuditLogModel(
            incident_id=incident_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action_name=action_name,
            state_diff=state_diff,
            previous_hash=previous_hash,
            signature_hash=sig,
            timestamp=now,
        )
        session.add(audit_entry)
        await session.flush()
        return audit_entry

    @classmethod
    async def verify_chain_integrity(cls, session: AsyncSession) -> bool:
        stmt = select(AuditLogModel).order_by(AuditLogModel.timestamp)
        result = await session.execute(stmt)
        logs = list(result.scalars().all())
        if not logs:
            return True

        expected_prev = "GENESIS_NEXUS_CHAIN_ROOT_0000"
        for entry in logs:
            if entry.previous_hash != expected_prev:
                return False
            ts_str = cls._format_timestamp(entry.timestamp)
            recomputed = cls._compute_hash(
                entry.previous_hash,
                entry.actor_id,
                entry.action_name,
                entry.state_diff,
                ts_str,
            )
            if recomputed != entry.signature_hash:
                return False
            expected_prev = entry.signature_hash

        return True


class MemoryRepository:
    """Playbook and vector memory operations."""

    @staticmethod
    async def store_memory(
        session: AsyncSession,
        category: str,
        reference_id: str,
        content: str,
        metadata_payload: dict[str, Any] | None = None,
        embedding_vector: list[float] | None = None,
    ) -> MemoryRecordModel:
        record = MemoryRecordModel(
            category=category,
            reference_id=reference_id,
            content=content,
            metadata_payload=metadata_payload or {},
            embedding_vector=embedding_vector or [],
        )
        session.add(record)
        await session.flush()
        return record

    @staticmethod
    async def get_by_category(session: AsyncSession, category: str) -> list[MemoryRecordModel]:
        stmt = select(MemoryRecordModel).where(MemoryRecordModel.category == category)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_reference(
        session: AsyncSession, reference_id: str
    ) -> MemoryRecordModel | None:
        stmt = select(MemoryRecordModel).where(MemoryRecordModel.reference_id == reference_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
