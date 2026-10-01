import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.enums import (
    ActionRiskLevel,
    ActionStatus,
    AgentStatus,
    ApprovalStatus,
    EvidenceType,
    IncidentSeverity,
    IncidentStatus,
)
from database.repository import (
    ActionRepository,
    AgentRunRepository,
    ApprovalRepository,
    AuditLogRepository,
    EvidenceRepository,
    IncidentRepository,
    MemoryRepository,
    PlanRepository,
    ResourceRepository,
    RouteRepository,
)
from database.seed import seed_database
from database.session import Base


@pytest_asyncio.fixture
async def db_session():
    """Create an isolated in-memory SQLite async database for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_query_incident(db_session: AsyncSession):
    """Test incident creation, querying, and status updates."""
    inc = await IncidentRepository.create_incident(
        session=db_session,
        title="Flash Flood at St. Jude Hospital Entrance",
        description="Ambulance bay blocked by water.",
        severity=IncidentSeverity.CRITICAL,
        status=IncidentStatus.INGESTED,
        latitude=37.7749,
        longitude=-122.4194,
    )
    assert inc.id is not None
    assert inc.severity == IncidentSeverity.CRITICAL
    assert inc.status == IncidentStatus.INGESTED

    # Test query
    retrieved = await IncidentRepository.get_by_id(db_session, inc.id)
    assert retrieved is not None
    assert retrieved.title == "Flash Flood at St. Jude Hospital Entrance"

    # Test update
    updated = await IncidentRepository.update_status(db_session, inc.id, IncidentStatus.VERIFIED)
    assert updated is not None
    assert updated.status == IncidentStatus.VERIFIED


@pytest.mark.asyncio
async def test_evidence_workflow(db_session: AsyncSession):
    """Test adding evidence and verifying it."""
    inc = await IncidentRepository.create_incident(
        session=db_session,
        title="Hospital Flood Test",
        severity=IncidentSeverity.HIGH,
    )

    ev = await EvidenceRepository.add_evidence(
        session=db_session,
        incident_id=inc.id,
        evidence_type=EvidenceType.IOT_STREAM_GAUGE,
        source_identifier="SG-401",
        telemetry_data={"water_level_inches": 32.4},
        confidence_score=0.75,
        verified=False,
    )
    assert ev.verified is False

    verified_ev = await EvidenceRepository.verify_evidence(
        session=db_session,
        evidence_id=ev.id,
        confidence_score=0.96,
        notes="Verified against CCTV",
    )
    assert verified_ev is not None
    assert verified_ev.verified is True
    assert verified_ev.confidence_score == 0.96


@pytest.mark.asyncio
async def test_resource_management(db_session: AsyncSession):
    """Test resource catalog queries."""
    res1 = await ResourceRepository.create_resource(
        session=db_session,
        name="High-Water Medic 44",
        resource_type="ambulance",
        capacity=2,
        status="available",
        latitude=37.768,
        longitude=-122.410,
        specs={"axle_clearance_inches": 34.0},
    )
    assert res1.name == "High-Water Medic 44"

    ambulances = await ResourceRepository.list_resources(db_session, resource_type="ambulance")
    assert len(ambulances) == 1
    assert ambulances[0].status == "available"

    updated_res = await ResourceRepository.update_status(db_session, res1.id, "dispatched")
    assert updated_res is not None
    assert updated_res.status == "dispatched"


@pytest.mark.asyncio
async def test_route_lifecycle(db_session: AsyncSession):
    """Test creating routes and marking compromise upon water surge."""
    inc = await IncidentRepository.create_incident(
        session=db_session,
        title="Road Inundation",
    )

    route = await RouteRepository.create_route(
        session=db_session,
        incident_id=inc.id,
        route_name="Route Beta: Industrial Way",
        origin_name="Depot",
        destination_name="Hospital ER",
        waypoints=[[37.7, -122.4], [37.8, -122.4]],
        total_distance_km=6.4,
        estimated_transit_time_min=11.2,
    )
    assert route.is_compromised is False

    compromised = await RouteRepository.mark_compromised(
        session=db_session,
        route_id=route.id,
        reason="Surge breached industrial culvert by 18 inches",
    )
    assert compromised is not None
    assert compromised.is_compromised is True
    assert "Surge breached" in compromised.compromised_reason


@pytest.mark.asyncio
async def test_plan_and_action_execution(db_session: AsyncSession):
    """Test synthesizing a plan and updating action status."""
    inc = await IncidentRepository.create_incident(
        session=db_session,
        title="Hospital Bypass",
    )

    plan = await PlanRepository.create_plan(
        session=db_session,
        incident_id=inc.id,
        title="Flood Reroute Plan",
        version=1,
    )

    action = await ActionRepository.create_action(
        session=db_session,
        plan_id=plan.id,
        incident_id=inc.id,
        sequence_order=1,
        action_type="CLOSE_PRIMARY_ARTERY",
        target_entity="Metropolitan Pkwy",
        risk_level=ActionRiskLevel.TIER_4_HIGH,
        description="Close flooded roadway",
        approval_required=True,
    )
    assert action.status == ActionStatus.PENDING
    assert action.risk_level == ActionRiskLevel.TIER_4_HIGH

    updated_action = await ActionRepository.update_status(
        session=db_session,
        action_id=action.id,
        new_status=ActionStatus.COMPLETED,
        execution_result={"receipt_id": "rcpt-99"},
    )
    assert updated_action is not None
    assert updated_action.status == ActionStatus.COMPLETED
    assert updated_action.execution_result["receipt_id"] == "rcpt-99"


@pytest.mark.asyncio
async def test_human_approval_gate(db_session: AsyncSession):
    """Test human commander approval workflow and decision tokens."""
    inc = await IncidentRepository.create_incident(
        session=db_session,
        title="High Risk Action Approval",
    )

    approval = await ApprovalRepository.request_approval(
        session=db_session,
        incident_id=inc.id,
        risk_level=ActionRiskLevel.TIER_4_HIGH,
    )
    assert approval.status == ApprovalStatus.PENDING

    pending_list = await ApprovalRepository.list_pending(db_session, incident_id=inc.id)
    assert len(pending_list) == 1

    decided = await ApprovalRepository.decide_approval(
        session=db_session,
        approval_id=approval.id,
        reviewer_id="commander_elena_vance",
        reviewer_role="Operations Watch Commander",
        decision="APPROVED",
        rationale="Cross-verified with SG-401 gauge. Closure authorized.",
    )
    assert decided is not None
    assert decided.status == ApprovalStatus.APPROVED
    assert decided.decision_token.startswith("tok-")


@pytest.mark.asyncio
async def test_agent_run_and_event_telemetry(db_session: AsyncSession):
    """Test recording agent runs and granular execution events."""
    inc = await IncidentRepository.create_incident(
        session=db_session,
        title="Agent Execution",
    )

    run = await AgentRunRepository.start_run(
        session=db_session,
        incident_id=inc.id,
        agent_name="VerificationAgent",
        input_payload={"sensor_ids": ["SG-401"]},
    )
    assert run.status == AgentStatus.RUNNING

    event = await AgentRunRepository.log_event(
        session=db_session,
        run_id=run.id,
        event_type="TOOL_CALL",
        agent_name="VerificationAgent",
        message="Querying hydrological gauge SG-401",
        event_data={"sensor": "SG-401"},
    )
    assert event.event_type == "TOOL_CALL"

    completed = await AgentRunRepository.complete_run(
        session=db_session,
        run_id=run.id,
        status=AgentStatus.COMPLETED,
        output_payload={"confidence": 0.94},
        execution_time_ms=124.5,
    )
    assert completed is not None
    assert completed.status == AgentStatus.COMPLETED
    assert completed.execution_time_ms == 124.5


@pytest.mark.asyncio
async def test_tamper_evident_audit_log_chain(db_session: AsyncSession):
    """Test cryptographic SHA-256 hash chaining on audit logs."""
    log1 = await AuditLogRepository.append_log(
        session=db_session,
        actor_type="AGENT",
        actor_id="IngestionAgent",
        action_name="INGEST_REPORT",
        state_diff={"flood_level": 30.0},
    )
    assert log1.previous_hash == "GENESIS_NEXUS_CHAIN_ROOT_0000"
    assert len(log1.signature_hash) == 64

    log2 = await AuditLogRepository.append_log(
        session=db_session,
        actor_type="HUMAN",
        actor_id="commander_vance",
        action_name="APPROVE_PLAN",
        state_diff={"approval": "GRANTED"},
    )
    assert log2.previous_hash == log1.signature_hash

    # Verify chain integrity returns True
    is_valid = await AuditLogRepository.verify_chain_integrity(db_session)
    assert is_valid is True


@pytest.mark.asyncio
async def test_memory_records_playbooks(db_session: AsyncSession):
    """Test storing and querying playbook and historical memories."""
    mem = await MemoryRepository.store_memory(
        session=db_session,
        category="playbook",
        reference_id="PLAYBOOK-01",
        content="Deploy sandbags along hospital perimeter when flood exceeds 20 inches.",
        metadata_payload={"priority": "HIGH"},
        embedding_vector=[0.1, 0.2, 0.3],
    )
    assert mem.reference_id == "PLAYBOOK-01"

    results = await MemoryRepository.get_by_category(db_session, "playbook")
    assert len(results) == 1
    assert results[0].reference_id == "PLAYBOOK-01"


@pytest.mark.asyncio
async def test_full_seed_scenario(db_session: AsyncSession):
    """Test that seed_database initializes all critical hospital flood records."""
    summary = await seed_database(db_session)
    assert summary["status"] == "seeded"

    # Verify hospital was seeded
    hospitals = await ResourceRepository.list_resources(db_session, resource_type="hospital")
    assert len(hospitals) == 1
    assert "St. Jude" in hospitals[0].name

    # Verify high-water ambulances
    ambulances = await ResourceRepository.list_resources(db_session, resource_type="ambulance")
    assert len(ambulances) >= 3

    # Verify routes
    routes = await RouteRepository.get_by_incident(db_session, uuid.UUID(summary["incident_id"]))
    assert len(routes) >= 2

    # Verify audit chain integrity
    assert await AuditLogRepository.verify_chain_integrity(db_session) is True
