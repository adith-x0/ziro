import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure monorepo root and backend are on sys.path
base_dir = Path(__file__).resolve().parent.parent
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))
if str(base_dir / "backend") not in sys.path:
    sys.path.insert(0, str(base_dir / "backend"))

from sqlalchemy.ext.asyncio import AsyncSession

from database.enums import (
    ActionRiskLevel,
    EvidenceType,
    IncidentSeverity,
    IncidentStatus,
)
from database.repository import (
    ActionRepository,
    AuditLogRepository,
    EvidenceRepository,
    IncidentRepository,
    MemoryRepository,
    PlanRepository,
    ResourceRepository,
    RouteRepository,
)
from database.session import async_session_factory, init_db


def utc_now() -> datetime:
    return datetime.now(UTC)


async def seed_database(session: AsyncSession) -> dict[str, Any]:
    """Seed database with realistic demo dataset for the Hospital Flooding Scenario."""
    print("Beginning NEXUS demo dataset seeding...")

    # 1. Seed Critical Facilities & Emergency Resources
    hospital = await ResourceRepository.create_resource(
        session=session,
        name="St. Jude Memorial Hospital (Level 1 Trauma Center)",
        resource_type="hospital",
        capacity=450,
        status="operational",
        latitude=37.7760,
        longitude=-122.4210,
        base_station_id="FAC-HOSP-STJUDE",
        specs={
            "facility_type": "Level 1 Regional Trauma Center",
            "active_icu_beds": 42,
            "emergency_bay_access": "BLOCKED_VIA_METROPOLITAN_PKWY",
            "alternate_bay_access": "OPEN_VIA_INDUSTRIAL_WAY",
            "backup_generators": "ONLINE",
            "helo_pad_operational": True,
        },
    )

    ambulance_hw1 = await ResourceRepository.create_resource(
        session=session,
        name="Medic-Rescue 44 (Ford F-550 High-Water 4x4)",
        resource_type="ambulance",
        capacity=2,
        status="available",
        latitude=37.7680,
        longitude=-122.4100,
        base_station_id="DEPOT-CENTRAL",
        specs={
            "vehicle_type": "high_water_ambulance",
            "axle_clearance_inches": 34.0,
            "snorkeled_intake": True,
            "winch_capacity_lbs": 16500,
            "crew_count": 3,
        },
    )

    await ResourceRepository.create_resource(
        session=session,
        name="Medic-Rescue 12 (Freightliner M2 Severe-Duty)",
        resource_type="ambulance",
        capacity=4,
        status="available",
        latitude=37.7690,
        longitude=-122.4110,
        base_station_id="DEPOT-CENTRAL",
        specs={
            "vehicle_type": "high_water_ambulance",
            "axle_clearance_inches": 42.0,
            "crew_count": 4,
        },
    )

    await ResourceRepository.create_resource(
        session=session,
        name="Ambulance Unit 08 (Standard Type III Medic)",
        resource_type="ambulance",
        capacity=1,
        status="staged",
        latitude=37.7675,
        longitude=-122.4095,
        base_station_id="DEPOT-CENTRAL",
        specs={
            "vehicle_type": "standard_ambulance",
            "axle_clearance_inches": 12.0,
            "hydrolock_risk_threshold_inches": 14.0,
        },
    )

    await ResourceRepository.create_resource(
        session=session,
        name="Mobile High-Volume Flood Pump 03",
        resource_type="water_pump",
        capacity=5000,  # GPM
        status="available",
        latitude=37.7685,
        longitude=-122.4105,
        base_station_id="DEPOT-CENTRAL",
        specs={"pump_capacity_gpm": 5000, "fuel_runtime_hours": 18},
    )

    await ResourceRepository.create_resource(
        session=session,
        name="Public Works Barrier Deployment Crew 01",
        resource_type="barrier_crew",
        capacity=1,
        status="available",
        latitude=37.7700,
        longitude=-122.4130,
        base_station_id="DEPOT-CENTRAL",
        specs={"traffic_cones": 150, "water_filled_barriers": 40, "crew_size": 4},
    )

    await ResourceRepository.create_resource(
        session=session,
        name="Civic Center Arena Evacuation Shelter",
        resource_type="shelter",
        capacity=350,
        status="available",
        latitude=37.7715,
        longitude=-122.4120,
        specs={"beds_deployed": 200, "ada_compliant": True, "generator_backup": True},
    )

    await ResourceRepository.create_resource(
        session=session,
        name="North Hill High School Community Shelter",
        resource_type="shelter",
        capacity=200,
        status="available",
        latitude=37.7840,
        longitude=-122.4300,
        specs={"beds_deployed": 100, "pet_friendly": True},
    )

    # 2. Seed Primary Incident: Hospital Flooding
    incident = await IncidentRepository.create_incident(
        session=session,
        title="Hospital Ingress Blocked: Flash Flooding at Metropolitan Parkway & River Road",
        description=(
            "Severe urban cloudburst has overwhelmed municipal storm canals. "
            "Metropolitan Parkway is submerged under 30+ inches of fast-moving water, "
            "severing primary inbound ambulance access to St. Jude Memorial Hospital ER bay."
        ),
        severity=IncidentSeverity.CRITICAL,
        status=IncidentStatus.INGESTED,
        latitude=37.7749,
        longitude=-122.4194,
        address_reference="Metropolitan Parkway at River Road Crossing",
        metadata_payload={
            "scenario_key": "HOSPITAL_FLOODING_PRIMARY",
            "affected_district": "Central Medical Corridor",
            "critical_facilities_threatened": ["St. Jude Memorial Hospital"],
        },
    )

    # 3. Seed Sensory and Citizen Evidence
    await EvidenceRepository.add_evidence(
        session=session,
        incident_id=incident.id,
        evidence_type=EvidenceType.CITIZEN_PHOTO,
        source_identifier="citizen_report_app_user_882",
        telemetry_data={
            "text": "Water is up to car door handles on Metropolitan Pkwy right outside ER gate.",
            "visual_depth_estimate_inches": 30.0,
            "photo_uri": "https://assets.nexus-ops.org/demo/floods/st_jude_inundation_01.jpg",
            "gps_accuracy_meters": 4.5,
        },
        confidence_score=0.89,
        verified=True,
        verification_notes="Cross-verified with CCTV CAM-08 and Stream Gauge SG-RIVER-401.",
    )

    await EvidenceRepository.add_evidence(
        session=session,
        incident_id=incident.id,
        evidence_type=EvidenceType.IOT_STREAM_GAUGE,
        source_identifier="SG-RIVER-401",
        telemetry_data={
            "station_name": "River Road Canal Bridge Gauge",
            "current_water_level_inches": 32.4,
            "flood_stage_threshold_inches": 24.0,
            "rate_of_rise_in_per_hr": 3.8,
            "precipitation_rate_in_per_hr": 2.1,
            "status": "FLOOD_STAGE_ACTIVE",
        },
        confidence_score=0.98,
        verified=True,
        verification_notes="Hardware telemetry validated with checksum signature.",
    )

    await EvidenceRepository.add_evidence(
        session=session,
        incident_id=incident.id,
        evidence_type=EvidenceType.TRAFFIC_CCTV,
        source_identifier="CAM-METRO-08",
        telemetry_data={
            "corridor": "Metropolitan Parkway at Mile 4.8",
            "visual_depth_estimate_inches": 28.5,
            "passable_sedan": False,
            "passable_high_clearance": True,
            "congestion": "gridlock",
            "submerged_vehicles_detected": 2,
        },
        confidence_score=0.95,
        verified=True,
        verification_notes="Visual object detection confirms 2 passenger sedans hydro-locked.",
    )

    await EvidenceRepository.add_evidence(
        session=session,
        incident_id=incident.id,
        evidence_type=EvidenceType.WEATHER_STATION,
        source_identifier="SG-INDUSTRIAL-202",
        telemetry_data={
            "station_name": "Industrial Way Canal Culvert",
            "current_water_level_inches": 8.5,
            "flood_stage_threshold_inches": 20.0,
            "rate_of_rise_in_per_hr": 0.4,
            "status": "NORMAL_FLOW",
        },
        confidence_score=0.96,
        verified=True,
        verification_notes="Confirms detour corridor along Industrial Way remains safe.",
    )

    # 4. Seed Road Routes
    route_primary_blocked = await RouteRepository.create_route(
        session=session,
        incident_id=incident.id,
        route_name="Route Alpha: Direct Metropolitan Pkwy Ingress (COMPROMISED)",
        origin_name="Central Fleet Depot",
        destination_name="St. Jude Hospital ER Bay",
        waypoints=[[37.7680, -122.4100], [37.7749, -122.4194], [37.7760, -122.4210]],
        total_distance_km=2.9,
        estimated_transit_time_min=5.0,
        max_water_clearance_supported_inches=14.0,
    )
    await RouteRepository.mark_compromised(
        session=session,
        route_id=route_primary_blocked.id,
        reason="Submerged under 32.4 inches of water at River Crossing.",
    )

    route_beta_safe = await RouteRepository.create_route(
        session=session,
        incident_id=incident.id,
        route_name="Route Beta: Industrial Way Detour (ACTIVE / SAFE)",
        origin_name="Central Fleet Depot",
        destination_name="St. Jude Hospital Rear Service Access",
        waypoints=[
            [37.7680, -122.4100],
            [37.7710, -122.4150],
            [37.7735, -122.4170],
            [37.7760, -122.4210],
        ],
        total_distance_km=6.4,
        estimated_transit_time_min=11.2,
        max_water_clearance_supported_inches=24.0,
    )

    await RouteRepository.create_route(
        session=session,
        incident_id=incident.id,
        route_name="Route Gamma: North Ridge Elevated Overpass (BACKUP)",
        origin_name="Central Fleet Depot",
        destination_name="St. Jude Hospital North Ridge Ingress",
        waypoints=[
            [37.7680, -122.4100],
            [37.7810, -122.4250],
            [37.7760, -122.4210],
        ],
        total_distance_km=7.8,
        estimated_transit_time_min=14.5,
        max_water_clearance_supported_inches=48.0,
    )

    # 5. Seed Initial Plan & Action Items
    plan = await PlanRepository.create_plan(
        session=session,
        incident_id=incident.id,
        version=1,
        title="Operational Action Plan v1: Hospital Corridor Flood Bypass & Containment",
        summary_narrative=(
            "Metropolitan Parkway submerged; rerouting all emergency medical transport via "
            "Route Beta (Industrial Way). Deploying high-water rescue ambulances, closing "
            "flooded arterial section, updating highway message signs, and alerting trauma bay."
        ),
        status="AWAITING_APPROVAL",
        risk_assessment_summary={
            "highest_risk_tier": "TIER_4_HIGH",
            "approval_required": True,
            "hospital_cutoff_mitigated": True,
            "estimated_delay_minutes": 6.2,
        },
    )

    # Action 1: Tier 2 Low Risk - VMS Sign Update
    await ActionRepository.create_action(
        session=session,
        plan_id=plan.id,
        incident_id=incident.id,
        sequence_order=1,
        action_type="UPDATE_VARIABLE_MESSAGE_SIGN",
        target_entity="Sign VMS-I80-04 (Westbound)",
        risk_level=ActionRiskLevel.TIER_2_LOW,
        description="Update highway digital signs: METRO PKWY FLOODED - EMS DETOUR INDUSTRIAL WAY",
        execution_payload={
            "sign_id": "VMS-I80-04",
            "message": "METRO PKWY FLOODED - DETOUR VIA INDUSTRIAL",
        },
        approval_required=False,
    )

    # Action 2: Tier 4 High Risk - Road Closure
    act_closure = await ActionRepository.create_action(
        session=session,
        plan_id=plan.id,
        incident_id=incident.id,
        sequence_order=2,
        action_type="CLOSE_PRIMARY_ARTERY",
        target_entity="Metropolitan Parkway (Mile 4.0 to 6.2)",
        risk_level=ActionRiskLevel.TIER_4_HIGH,
        description=(
            "Deploy physical barriers to close Metropolitan Parkway and halt civilian traffic."
        ),
        execution_payload={
            "closure_start": "Mile 4.0",
            "closure_end": "Mile 6.2",
            "divert_to": "Industrial Way",
        },
        approval_required=True,
    )

    # Action 3: Tier 3 Medium Risk - High Water EMS Dispatch
    await ActionRepository.create_action(
        session=session,
        plan_id=plan.id,
        incident_id=incident.id,
        sequence_order=3,
        action_type="DISPATCH_HIGH_WATER_EMS",
        target_entity="Medic-Rescue 44",
        risk_level=ActionRiskLevel.TIER_3_MEDIUM,
        description=(
            "Dispatch Medic-Rescue 44 via Route Beta to rendezvous at St. Jude ER trauma bay."
        ),
        execution_payload={
            "unit_id": ambulance_hw1.name,
            "route_id": str(route_beta_safe.id),
        },
        approval_required=True,
    )

    # Action 4: Tier 2 Low Risk - Hospital Bay Notification
    await ActionRepository.create_action(
        session=session,
        plan_id=plan.id,
        incident_id=incident.id,
        sequence_order=4,
        action_type="NOTIFY_HOSPITAL_TRAUMA_BAY",
        target_entity="St. Jude Hospital ER Charge Nurse",
        risk_level=ActionRiskLevel.TIER_2_LOW,
        description=(
            "Notify trauma intake that ambulances are inbound via rear industrial service gate."
        ),
        execution_payload={"facility_id": "FAC-HOSP-STJUDE", "alert": "INBOUND_VIA_REAR_BAY"},
        approval_required=False,
    )

    # 6. Seed Playbook and Historical Memory Records
    await MemoryRepository.store_memory(
        session=session,
        category="playbook",
        reference_id="PLAYBOOK-FLOOD-HOSPITAL-01",
        content=(
            "STANDARD OPERATING PROCEDURE: When flash flooding exceeds 24 inches along "
            "Metropolitan Parkway, ingress to St. Jude Hospital shall immediately divert to "
            "Industrial Way Service Corridor. Standard ambulances (axle clearance < 16in) "
            "must stage at Depot Central until high-clearance escorts are assigned."
        ),
        metadata_payload={"protocol": "SOP-METRO-09", "jurisdiction": "Municipal EOC"},
        embedding_vector=[0.12, -0.45, 0.78, 0.33, -0.11],
    )

    await MemoryRepository.store_memory(
        session=session,
        category="historical_flood",
        reference_id="HIST-EVENT-2023-STORM-ELENA",
        content=(
            "Storm Elena (November 2023): River Road stream gauge crested at 34.2 inches. "
            "Industrial Way remained passable for high-clearance vehicles for 4.5 hours after "
            "Metropolitan Parkway closed, before canal culvert overflow occurred."
        ),
        metadata_payload={"storm_name": "Elena", "year": 2023, "max_depth_inches": 34.2},
        embedding_vector=[0.05, -0.32, 0.65, 0.41, -0.08],
    )

    # 7. Seed Initial Tamper-Evident Audit Record
    await AuditLogRepository.append_log(
        session=session,
        incident_id=incident.id,
        actor_type="SYSTEM",
        actor_id="NEXUS_INGESTION_ORCHESTRATOR",
        action_name="INCIDENT_INGESTION_INITIALIZED",
        state_diff={
            "incident_id": str(incident.id),
            "severity": "CRITICAL",
            "actions_planned": 4,
            "requires_approval": True,
        },
    )

    await session.commit()
    print("Database seeding completed successfully.")

    return {
        "status": "seeded",
        "incident_id": str(incident.id),
        "hospital_id": str(hospital.id),
        "primary_action_id": str(act_closure.id),
    }


async def main():
    await init_db()
    async with async_session_factory() as session:
        result = await seed_database(session)
        print(f"Seed Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
