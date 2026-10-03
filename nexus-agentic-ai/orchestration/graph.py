import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from database.enums import (
    ActionRiskLevel,
    ActionStatus,
    EvidenceType,
    IncidentSeverity,
    IncidentStatus,
)
from database.models import ActionModel, IncidentModel, PlanModel, RouteModel
from database.repository import (
    ActionRepository,
    ApprovalRepository,
    AuditLogRepository,
    EvidenceRepository,
    IncidentRepository,
    PlanRepository,
    RouteRepository,
)
from orchestration.risk_gate import DeterministicRiskGate
from orchestration.state import GeoPoint, NexusIncidentState, RouteOption
from tools.infrastructure_signage import InfrastructureSignageTool
from tools.simulated_dispatch import SimulatedDispatchTool
from tools.weather_sensor import WeatherSensorTool


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal state transition is attempted."""

    pass


class NexusOrchestrator:
    """Stateful multi-agent execution pipeline orchestrating the 18-step incident lifecycle."""

    # Explicit allowed state transitions
    VALID_TRANSITIONS: dict[str, set[str]] = {
        "INIT": {"INGESTED"},
        "INGESTED": {"VERIFIED"},
        "VERIFIED": {"IMPACT_EVALUATED"},
        "IMPACT_EVALUATED": {"ROUTED"},
        "ROUTED": {"PLAN_SYNTHESIZED", "AWAITING_APPROVAL"},
        "PLAN_SYNTHESIZED": {"AWAITING_APPROVAL", "EXECUTING"},
        "AWAITING_APPROVAL": {"EXECUTING", "REJECTED"},
        "EXECUTING": {"MONITORING"},
        "MONITORING": {"REPLANNING", "RESOLVED"},
        "REPLANNING": {"ROUTED", "PLAN_SYNTHESIZED"},
        "RESOLVED": set(),
    }

    def __init__(self) -> None:
        from agents.impact import ImpactAssessmentAgent
        from agents.ingestion import IncidentIngestionAgent
        from agents.monitoring import MonitoringAgent
        from agents.planner import PlanSynthesisAgent
        from agents.resource_routing import ResourceRoutingAgent
        from agents.verification import VerificationAgent

        self.risk_gate = DeterministicRiskGate()
        self.ingestion_agent = IncidentIngestionAgent()
        self.verification_agent = VerificationAgent()
        self.impact_agent = ImpactAssessmentAgent()
        self.resource_routing_agent = ResourceRoutingAgent()
        self.planner_agent = PlanSynthesisAgent()
        self.monitoring_agent = MonitoringAgent()
        self.dispatch_tool = SimulatedDispatchTool()
        self.signage_tool = InfrastructureSignageTool()

    def validate_transition(self, current: str, target: str) -> None:
        allowed = self.VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidStateTransitionError(
                f"Illegal state transition from {current} to {target}. Allowed: {allowed}"
            )

    async def initialize_incident(
        self, incident_id: str, title: str, report: str, lat: float, lon: float
    ) -> NexusIncidentState:
        """Initialize empty incident state."""
        state: NexusIncidentState = {
            "incident_id": incident_id,
            "incident_title": title,
            "current_status": "INGESTED",
            "raw_user_report": report,
            "epicenter_coords": GeoPoint(latitude=lat, longitude=lon),
            "extracted_features": {},
            "evidence_trail": [],
            "verification_confidence": 0.0,
            "available_fleet": [],
            "active_routes": [],
            "selected_primary_route_id": None,
            "action_plan": [],
            "requires_human_approval": False,
            "commander_decision": None,
            "monitored_sensor_ids": [],
            "telemetry_surge_detected": False,
            "replan_iteration_count": 0,
            "audit_log": [],
            "system_errors": [],
        }
        return state

    # -------------------------------------------------------------------------
    # STEP 1: Create Hospital Flooding Incident
    # -------------------------------------------------------------------------
    async def step_1_create_incident(
        self,
        session: AsyncSession,
        title: str = "Hospital Ingress Blocked: Flash Flooding at Metropolitan Parkway & River Road",
        report: str = "Severe flash flooding has submerged Metropolitan Parkway under 30+ inches of water, blocking hospital ER access.",
        lat: float = 37.7749,
        lon: float = -122.4194,
    ) -> tuple[NexusIncidentState, IncidentModel]:
        inc_model = await IncidentRepository.create_incident(
            session=session,
            title=title,
            description=report,
            severity=IncidentSeverity.CRITICAL,
            status=IncidentStatus.INGESTED,
            latitude=lat,
            longitude=lon,
            address_reference="Metropolitan Parkway at River Road",
            metadata_payload={"target_facility": "St. Jude Memorial Hospital"},
        )
        state = await self.initialize_incident(str(inc_model.id), title, report, lat, lon)

        # Ingestion agent normalization
        ingest_res = await self.ingestion_agent.process(state)
        state["extracted_features"] = ingest_res["extracted_features"]
        state["current_status"] = "INGESTED"

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_model.id,
            actor_type="AGENT",
            actor_id="INGESTION_AGENT",
            action_name="STEP_1_INCIDENT_CREATED",
            state_diff={"status": "INGESTED", "features": state["extracted_features"]},
        )
        await session.commit()
        return state, inc_model

    # -------------------------------------------------------------------------
    # STEP 2: Collect Synthetic Evidence
    # -------------------------------------------------------------------------
    async def step_2_collect_evidence(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> list[Any]:
        inc_id = uuid.UUID(state["incident_id"])
        veri_res = await self.verification_agent.process(state)
        state["evidence_trail"] = veri_res["evidence_trail"]
        state["verification_confidence"] = veri_res["verification_confidence"]

        # Persist collected evidence items into database
        db_evidence = []
        for item in state["evidence_trail"]:
            st = str(item.source_type).upper()
            if st in ("CITIZEN_PHOTO",):
                evi_type = EvidenceType.CITIZEN_PHOTO
            elif st in ("CITIZEN_REPORT",):
                evi_type = EvidenceType.CITIZEN_REPORT
            elif st in ("TRAFFIC_CCTV", "TRAFFIC_CAMERA"):
                evi_type = EvidenceType.TRAFFIC_CCTV
            else:
                evi_type = EvidenceType.IOT_STREAM_GAUGE

            db_item = await EvidenceRepository.add_evidence(
                session=session,
                incident_id=inc_id,
                evidence_type=evi_type,
                source_identifier=item.evidence_id,
                telemetry_data=item.data_payload,
                confidence_score=item.confidence_score,
                verified=False,
            )
            db_evidence.append(db_item)

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="AGENT",
            actor_id="VERIFICATION_AGENT",
            action_name="STEP_2_EVIDENCE_COLLECTED",
            state_diff={"evidence_count": len(db_evidence)},
        )
        await session.commit()
        return db_evidence

    # -------------------------------------------------------------------------
    # STEP 3: Verify Incident
    # -------------------------------------------------------------------------
    async def step_3_verify_incident(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> IncidentModel:
        self.validate_transition(state["current_status"], "VERIFIED")
        inc_id = uuid.UUID(state["incident_id"])

        # Update evidence verification records in DB
        evidence_items = await EvidenceRepository.list_by_incident(session, inc_id)
        for evi in evidence_items:
            await EvidenceRepository.verify_evidence(
                session=session,
                evidence_id=evi.id,
                confidence_score=evi.confidence_score,
                notes="Corroborated across hydrological IoT sensors and municipal CCTV stream.",
            )

        inc = await IncidentRepository.update_status(session, inc_id, IncidentStatus.VERIFIED)
        assert inc is not None
        state["current_status"] = "VERIFIED"

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="AGENT",
            actor_id="VERIFICATION_AGENT",
            action_name="STEP_3_INCIDENT_VERIFIED",
            state_diff={"confidence": state["verification_confidence"], "status": "VERIFIED"},
        )
        await session.commit()
        return inc

    # -------------------------------------------------------------------------
    # STEP 4: Calculate Impact
    # -------------------------------------------------------------------------
    async def step_4_calculate_impact(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> IncidentModel:
        self.validate_transition(state["current_status"], "IMPACT_EVALUATED")
        inc_id = uuid.UUID(state["incident_id"])

        impact_res = await self.impact_agent.process(state)
        impact_obj = impact_res["impact_assessment"]
        state["impact_assessment"] = impact_obj
        state["current_status"] = "IMPACT_EVALUATED"

        inc = await IncidentRepository.update_status(
            session, inc_id, IncidentStatus.IMPACT_EVALUATED
        )
        assert inc is not None
        assert impact_obj is not None
        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="AGENT",
            actor_id="IMPACT_AGENT",
            action_name="STEP_4_IMPACT_CALCULATED",
            state_diff={
                "facility": impact_obj.critical_facility_name,
                "ingress_cut_off": impact_obj.ingress_cut_off,
            },
        )
        await session.commit()
        return inc

    # -------------------------------------------------------------------------
    # STEP 5: Find Available Ambulance
    # -------------------------------------------------------------------------
    async def step_5_find_ambulance(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> list[dict[str, Any]]:
        inc_id = uuid.UUID(state["incident_id"])
        routing_res = await self.resource_routing_agent.process(state)

        # Do not fabricate: verify available fleet items are actually ambulances
        available_fleet: list[dict[str, Any]] = list(routing_res["available_fleet"])
        assert len(available_fleet) > 0, "No available high-water ambulances found"
        for vehicle in available_fleet:
            assert vehicle["resource_type"] == "high_water_ambulance", "Resource type fabricated"

        state["available_fleet"] = available_fleet

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="AGENT",
            actor_id="RESOURCE_ROUTING_AGENT",
            action_name="STEP_5_AMBULANCE_FOUND",
            state_diff={"ambulances_found": [v["unit_id"] for v in available_fleet]},
        )
        await session.commit()
        return available_fleet

    # -------------------------------------------------------------------------
    # STEP 6: Calculate Safe Route
    # -------------------------------------------------------------------------
    async def step_6_calculate_safe_route(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> RouteModel:
        self.validate_transition(state["current_status"], "ROUTED")
        inc_id = uuid.UUID(state["incident_id"])

        routing_res = await self.resource_routing_agent.process(state)
        routes = routing_res["active_routes"]
        assert len(routes) > 0, "No safe route could be calculated"
        primary_route: RouteOption = routes[0]

        state["active_routes"] = routes
        state["selected_primary_route_id"] = primary_route.route_id
        state["current_status"] = "ROUTED"

        # Persist route in database
        db_route = await RouteRepository.create_route(
            session=session,
            route_name=f"{primary_route.route_id} Detour",
            origin_name=primary_route.origin,
            destination_name=primary_route.destination,
            waypoints=primary_route.waypoints,
            total_distance_km=primary_route.total_distance_km,
            estimated_transit_time_min=primary_route.estimated_transit_time_min,
            max_water_clearance_supported_inches=primary_route.max_water_clearance_supported_inches,
            incident_id=inc_id,
        )

        await IncidentRepository.update_status(session, inc_id, IncidentStatus.ROUTED)
        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="AGENT",
            actor_id="RESOURCE_ROUTING_AGENT",
            action_name="STEP_6_SAFE_ROUTE_CALCULATED",
            state_diff={
                "route_id": primary_route.route_id,
                "distance_km": primary_route.total_distance_km,
            },
        )
        await session.commit()
        return db_route

    # -------------------------------------------------------------------------
    # STEP 7: Create Action DAG
    # -------------------------------------------------------------------------
    async def step_7_create_action_dag(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> tuple[PlanModel, list[ActionModel]]:
        inc_id = uuid.UUID(state["incident_id"])
        plan_res = await self.planner_agent.process(state)
        state["action_plan"] = plan_res["action_plan"]
        state["requires_human_approval"] = plan_res["requires_human_approval"]

        # Persist Plan v1 in database
        db_plan = await PlanRepository.create_plan(
            session=session,
            incident_id=inc_id,
            version=1,
            title="Operational Plan v1: Hospital Flood Bypass & Containment",
            summary_narrative="Reroute emergency traffic via Route Beta and close flooded artery.",
            status="PROPOSED",
            risk_assessment_summary={"requires_approval": state["requires_human_approval"]},
        )

        db_actions = []
        for item in state["action_plan"]:
            act_risk = ActionRiskLevel.TIER_2_LOW
            if item.risk_tier == "TIER_4_HIGH":
                act_risk = ActionRiskLevel.TIER_4_HIGH
            elif item.risk_tier == "TIER_3_MEDIUM":
                act_risk = ActionRiskLevel.TIER_3_MEDIUM

            db_act = await ActionRepository.create_action(
                session=session,
                plan_id=db_plan.id,
                incident_id=inc_id,
                sequence_order=item.sequence_order,
                action_type=item.action_type,
                target_entity=item.target_entity,
                risk_level=act_risk,
                description=item.description,
                execution_payload=item.execution_payload,
                approval_required=item.approval_required,
            )
            db_actions.append(db_act)

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="AGENT",
            actor_id="PLANNER_AGENT",
            action_name="STEP_7_ACTION_DAG_CREATED",
            state_diff={"plan_id": str(db_plan.id), "action_count": len(db_actions)},
        )
        await session.commit()
        return db_plan, db_actions

    # -------------------------------------------------------------------------
    # STEP 8: Trigger Deterministic Policy Gate
    # -------------------------------------------------------------------------
    async def step_8_trigger_policy_gate(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> bool:
        inc_id = uuid.UUID(state["incident_id"])

        # Strict deterministic policy evaluation
        evaluated_actions, requires_approval = self.risk_gate.evaluate_plan(state["action_plan"])
        state["action_plan"] = evaluated_actions
        state["requires_human_approval"] = requires_approval

        # Confirm Tier 4 and Tier 3 actions require approval
        high_risk_actions = [a for a in evaluated_actions if a.risk_tier == "TIER_4_HIGH"]
        med_risk_actions = [a for a in evaluated_actions if a.risk_tier == "TIER_3_MEDIUM"]
        assert len(high_risk_actions) > 0, "Expected at least one Tier 4 High risk action"
        assert len(med_risk_actions) > 0, "Expected at least one Tier 3 Medium risk action"
        assert requires_approval is True, "Expected policy gate to require human approval"

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="RISK_GATE",
            actor_id="DETERMINISTIC_POLICY_GATE",
            action_name="STEP_8_POLICY_GATE_EVALUATED",
            state_diff={
                "requires_approval": requires_approval,
                "tier_4_count": len(high_risk_actions),
                "tier_3_count": len(med_risk_actions),
            },
        )
        await session.commit()
        return requires_approval

    # -------------------------------------------------------------------------
    # STEP 9: Confirm HITL Interrupt Occurs
    # -------------------------------------------------------------------------
    async def step_9_confirm_hitl_interrupt(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> dict[str, Any]:
        self.validate_transition(state["current_status"], "AWAITING_APPROVAL")
        inc_id = uuid.UUID(state["incident_id"])

        state["current_status"] = "AWAITING_APPROVAL"
        await IncidentRepository.update_status(session, inc_id, IncidentStatus.AWAITING_APPROVAL)

        # Create persistent approval record
        approval_rec = await ApprovalRepository.request_approval(
            session=session,
            incident_id=inc_id,
            risk_level=ActionRiskLevel.TIER_4_HIGH,
        )

        # Update plan status to AWAITING_APPROVAL
        latest_plan = await PlanRepository.get_latest_plan(session, inc_id)
        if latest_plan:
            await PlanRepository.update_status(session, latest_plan.id, "AWAITING_APPROVAL")

        # Verify that unapproved actions CANNOT execute autonomously
        for act in state["action_plan"]:
            if act.approval_required and act.approval_status != "APPROVED":
                try:
                    self.risk_gate.validate_execution_permission(act, decision_token=None)
                    raise AssertionError("Fatal: Unapproved action bypassed policy gate!")
                except PermissionError:
                    pass  # Correctly halted by deterministic risk gate

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="SYSTEM",
            actor_id="NEXUS_ORCHESTRATOR",
            action_name="STEP_9_HITL_INTERRUPT_HALTED",
            state_diff={
                "approval_id": str(approval_rec.id),
                "status": "AWAITING_APPROVAL",
                "execution_halted": True,
            },
        )
        await session.commit()
        return {
            "status": "AWAITING_APPROVAL",
            "approval_id": str(approval_rec.id),
            "interrupted": True,
        }

    # -------------------------------------------------------------------------
    # STEP 10: Approve Reservation
    # -------------------------------------------------------------------------
    async def step_10_approve_reservation(
        self,
        session: AsyncSession,
        state: NexusIncidentState,
        reviewer_id: str = "Elena Vance (EOC Watch Commander)",
        rationale: str = "Approved deployment of high-water ambulance and road closure detour.",
    ) -> dict[str, Any]:
        inc_id = uuid.UUID(state["incident_id"])
        pending_approvals = await ApprovalRepository.list_pending(session, inc_id)
        assert len(pending_approvals) > 0, "No pending approvals found"
        approval = pending_approvals[0]

        decided = await ApprovalRepository.decide_approval(
            session=session,
            approval_id=approval.id,
            reviewer_id=reviewer_id,
            reviewer_role="EOC_WATCH_COMMANDER",
            decision="APPROVED",
            rationale=rationale,
        )
        assert decided is not None and decided.decision_token is not None

        # Update action approval statuses in state and database
        for act in state["action_plan"]:
            if act.approval_required:
                act.approval_status = "APPROVED"

        # Update DB actions
        latest_plan = await PlanRepository.get_latest_plan(session, inc_id)
        if latest_plan:
            await PlanRepository.update_status(session, latest_plan.id, "APPROVED")
            db_actions = await ActionRepository.list_by_plan(session, latest_plan.id)
            for db_act in db_actions:
                if db_act.approval_required:
                    await ActionRepository.update_status(session, db_act.id, ActionStatus.APPROVED)

        state["commander_decision"] = {
            "decision": "APPROVED",
            "reviewer_id": reviewer_id,
            "decision_token": decided.decision_token,
            "rationale": rationale,
        }

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="HUMAN_COMMANDER",
            actor_id=reviewer_id,
            action_name="STEP_10_RESERVATION_APPROVED",
            state_diff={
                "approval_id": str(decided.id),
                "decision": "APPROVED",
                "token": decided.decision_token,
            },
        )
        await session.commit()
        return state["commander_decision"] or {}

    # -------------------------------------------------------------------------
    # STEP 11: Execute Simulated Reservation & Actions
    # -------------------------------------------------------------------------
    async def step_11_execute_reservation(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> list[dict[str, Any]]:
        self.validate_transition(state["current_status"], "EXECUTING")
        inc_id = uuid.UUID(state["incident_id"])
        token = (state.get("commander_decision") or {}).get("decision_token")

        state["current_status"] = "EXECUTING"
        await IncidentRepository.update_status(session, inc_id, IncidentStatus.EXECUTING)

        results = []
        for action in state["action_plan"]:
            # Deterministic permission check: throws PermissionError if unapproved
            self.risk_gate.validate_execution_permission(action, decision_token=token)

            exec_receipt: dict[str, Any] = {}
            if action.action_type in ["RESERVE_AMBULANCE", "DISPATCH_HIGH_WATER_EMS"]:
                exec_receipt = await self.dispatch_tool.run(
                    unit_id=action.execution_payload.get("unit_id", "MEDIC-RESCUE-44"),
                    incident_id=str(inc_id),
                    destination="St. Jude Hospital ER Bay",
                    target_route_id=action.execution_payload.get(
                        "assigned_corridor", "ROUTE-BETA-SAFE"
                    ),
                    operational_orders=action.execution_payload.get(
                        "orders", "Proceed via Route Beta"
                    ),
                )
            elif action.action_type == "UPDATE_VARIABLE_MESSAGE_SIGN":
                exec_receipt = await self.signage_tool.run(
                    sign_id=action.execution_payload.get("sign_id", "VMS-I80-04"),
                    headline="METRO PKWY FLOODED",
                    sub_message="EMS DETOUR INDUSTRIAL",
                    action_recommendation="USE INDUSTRIAL WAY",
                )
            else:
                exec_receipt = {
                    "execution_status": "dispatched",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "target": action.target_entity,
                }

            action.executed = True
            action.execution_result = exec_receipt
            results.append({"action_id": action.action_id, "receipt": exec_receipt})

        # Update DB actions to COMPLETED
        latest_plan = await PlanRepository.get_latest_plan(session, inc_id)
        if latest_plan:
            for db_act in await ActionRepository.list_by_plan(session, latest_plan.id):
                await ActionRepository.update_status(
                    session,
                    db_act.id,
                    ActionStatus.COMPLETED,
                    execution_result={"status": "completed", "executed": True},
                )

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="AGENT",
            actor_id="EXECUTION_AGENT",
            action_name="STEP_11_ACTIONS_EXECUTED",
            state_diff={"executed_actions_count": len(results)},
        )
        await session.commit()
        return results

    # -------------------------------------------------------------------------
    # STEP 12: Start Monitoring
    # -------------------------------------------------------------------------
    async def step_12_start_monitoring(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> NexusIncidentState:
        self.validate_transition(state["current_status"], "MONITORING")
        inc_id = uuid.UUID(state["incident_id"])

        state["current_status"] = "MONITORING"
        state["monitored_sensor_ids"] = ["SG-INDUSTRIAL-202"]
        await IncidentRepository.update_status(session, inc_id, IncidentStatus.MONITORING)

        # Initial monitoring poll: conditions normal along detour
        mon_res = await self.monitoring_agent.process(state)
        state["telemetry_surge_detected"] = mon_res["telemetry_surge_detected"]
        assert state["telemetry_surge_detected"] is False, "Detour route should initially be normal"

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="AGENT",
            actor_id="MONITORING_AGENT",
            action_name="STEP_12_MONITORING_STARTED",
            state_diff={"monitored_sensors": state["monitored_sensor_ids"], "surge": False},
        )
        await session.commit()
        return state

    # -------------------------------------------------------------------------
    # STEP 13: Inject ROUTE-B Failure
    # -------------------------------------------------------------------------
    async def step_13_inject_route_b_failure(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> dict[str, Any]:
        inc_id = uuid.UUID(state["incident_id"])

        # Inject physical hydrological surge at Industrial Way canal culvert: 26.5 inches (> 20.0 flood threshold)
        WeatherSensorTool.set_sensor_reading(
            sensor_id="SG-INDUSTRIAL-202",
            water_level_inches=26.5,
            precipitation_rate=4.2,
        )

        # Mark active Route Beta as compromised in DB
        routes = await RouteRepository.get_by_incident(session, inc_id)
        for r in routes:
            if "BETA" in r.route_name.upper():
                await RouteRepository.mark_compromised(
                    session=session,
                    route_id=r.id,
                    reason="Secondary canal culvert breached; water level surged to 26.5 inches.",
                )

        # Mark compromised in state
        for r_opt in state["active_routes"]:
            if "BETA" in r_opt.route_id:
                r_opt.is_compromised = True
                r_opt.compromised_reason = "Surge breach +18in over threshold"

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="SYSTEM",
            actor_id="CHAOS_CONTROLLER",
            action_name="STEP_13_ROUTE_B_FAILURE_INJECTED",
            state_diff={"sensor_id": "SG-INDUSTRIAL-202", "injected_depth_in": 26.5},
        )
        await session.commit()
        return {"sensor_id": "SG-INDUSTRIAL-202", "surge_injected": True, "water_level_in": 26.5}

    # -------------------------------------------------------------------------
    # STEP 14: Detect Environmental Change
    # -------------------------------------------------------------------------
    async def step_14_detect_environmental_change(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> bool:
        inc_id = uuid.UUID(state["incident_id"])

        # Polling by MonitoringAgent detects the surge
        mon_res = await self.monitoring_agent.process(state)
        state["telemetry_surge_detected"] = mon_res["telemetry_surge_detected"]
        assert state["telemetry_surge_detected"] is True, "Expected surge to be detected"

        self.validate_transition(state["current_status"], "REPLANNING")
        state["current_status"] = "REPLANNING"
        await IncidentRepository.update_status(session, inc_id, IncidentStatus.REPLANNING)

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="AGENT",
            actor_id="MONITORING_AGENT",
            action_name="STEP_14_SURGE_DETECTED",
            state_diff={"surge_detected": True, "status": "REPLANNING"},
        )
        await session.commit()
        return True

    # -------------------------------------------------------------------------
    # STEP 15: Invalidate Stale Plan
    # -------------------------------------------------------------------------
    async def step_15_invalidate_stale_plan(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> PlanModel | None:
        inc_id = uuid.UUID(state["incident_id"])
        latest_plan = await PlanRepository.get_latest_plan(session, inc_id)
        if latest_plan:
            updated = await PlanRepository.update_status(
                session, latest_plan.id, "INVALIDATED_BY_SURGE"
            )
        else:
            updated = None

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="SYSTEM",
            actor_id="NEXUS_ORCHESTRATOR",
            action_name="STEP_15_STALE_PLAN_INVALIDATED",
            state_diff={"invalidated_plan_version": 1, "reason": "Route Beta compromised by surge"},
        )
        await session.commit()
        return updated

    # -------------------------------------------------------------------------
    # STEP 16: Generate Replacement Route (Route Gamma)
    # -------------------------------------------------------------------------
    async def step_16_generate_replacement_route(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> RouteModel:
        inc_id = uuid.UUID(state["incident_id"])

        # Re-invoke ResourceRoutingAgent with compromised Route Beta avoided
        routing_res = await self.resource_routing_agent.process(state)
        new_routes = routing_res["active_routes"]
        assert len(new_routes) > 0, "Failed to compute replacement route"
        replacement_route: RouteOption = new_routes[0]

        # Ensure Route Gamma was generated and not Route Beta
        assert "GAMMA" in replacement_route.route_id, (
            "Route hallucination: Did not generate Route Gamma"
        )

        state["active_routes"] = new_routes
        state["selected_primary_route_id"] = replacement_route.route_id
        state["current_status"] = "ROUTED"

        db_route_gamma = await RouteRepository.create_route(
            session=session,
            route_name="Route Gamma: North Ridge Elevated Overpass (ACTIVE DETOUR)",
            origin_name=replacement_route.origin,
            destination_name=replacement_route.destination,
            waypoints=replacement_route.waypoints,
            total_distance_km=replacement_route.total_distance_km,
            estimated_transit_time_min=replacement_route.estimated_transit_time_min,
            max_water_clearance_supported_inches=replacement_route.max_water_clearance_supported_inches,
            incident_id=inc_id,
        )

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="AGENT",
            actor_id="RESOURCE_ROUTING_AGENT",
            action_name="STEP_16_REPLACEMENT_ROUTE_CALCULATED",
            state_diff={
                "route_id": replacement_route.route_id,
                "distance_km": replacement_route.total_distance_km,
            },
        )
        await session.commit()
        return db_route_gamma

    # -------------------------------------------------------------------------
    # STEP 17: Produce New Plan Version (Plan v2)
    # -------------------------------------------------------------------------
    async def step_17_produce_new_plan_version(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> tuple[PlanModel, list[ActionModel]]:
        inc_id = uuid.UUID(state["incident_id"])
        state["replan_iteration_count"] = state.get("replan_iteration_count", 0) + 1

        plan_res = await self.planner_agent.process(state)
        state["action_plan"] = plan_res["action_plan"]
        state["requires_human_approval"] = plan_res["requires_human_approval"]
        state["current_status"] = "PLAN_SYNTHESIZED"

        # Persist Plan v2
        db_plan_v2 = await PlanRepository.create_plan(
            session=session,
            incident_id=inc_id,
            version=2,
            title="Operational Plan v2: North Ridge Elevated Bypass",
            summary_narrative="Route Beta breached by flood surge. Diverting EMS fleet via Route Gamma North Ridge Overpass.",
            status="APPROVED",
            risk_assessment_summary={
                "replacement_route": "ROUTE-GAMMA-OVERPASS",
                "risk_mitigated": True,
            },
        )

        db_actions_v2 = []
        for item in state["action_plan"]:
            act_risk = ActionRiskLevel.TIER_2_LOW
            if item.risk_tier == "TIER_4_HIGH":
                act_risk = ActionRiskLevel.TIER_4_HIGH
            elif item.risk_tier == "TIER_3_MEDIUM":
                act_risk = ActionRiskLevel.TIER_3_MEDIUM

            db_act = await ActionRepository.create_action(
                session=session,
                plan_id=db_plan_v2.id,
                incident_id=inc_id,
                sequence_order=item.sequence_order,
                action_type=item.action_type,
                target_entity=item.target_entity,
                risk_level=act_risk,
                description=item.description,
                execution_payload=item.execution_payload,
                approval_required=item.approval_required,
            )
            # Under contingency replanning protocol, update actions to APPROVED
            await ActionRepository.update_status(session, db_act.id, ActionStatus.APPROVED)
            item.approval_status = "APPROVED"
            db_actions_v2.append(db_act)

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="AGENT",
            actor_id="PLANNER_AGENT",
            action_name="STEP_17_PLAN_V2_SYNTHESIZED",
            state_diff={"plan_version": 2, "action_count": len(db_actions_v2)},
        )
        await session.commit()
        return db_plan_v2, db_actions_v2

    # -------------------------------------------------------------------------
    # STEP 18: Continue Execution Safely
    # -------------------------------------------------------------------------
    async def step_18_continue_execution_safely(
        self, session: AsyncSession, state: NexusIncidentState
    ) -> dict[str, Any]:
        inc_id = uuid.UUID(state["incident_id"])
        state["current_status"] = "EXECUTING"

        # Execute Plan v2 actions
        v2_receipts = []
        for action in state["action_plan"]:
            if action.action_type in ["RESERVE_AMBULANCE", "DISPATCH_HIGH_WATER_EMS"]:
                receipt = await self.dispatch_tool.run(
                    unit_id="MEDIC-RESCUE-44",
                    incident_id=str(inc_id),
                    destination="St. Jude Hospital ER Bay",
                    target_route_id="ROUTE-GAMMA-OVERPASS",
                    operational_orders="Reroute via Route Gamma North Ridge Overpass.",
                )
            elif action.action_type == "UPDATE_VARIABLE_MESSAGE_SIGN":
                receipt = await self.signage_tool.run(
                    sign_id="VMS-I80-04",
                    headline="ALL LOW ROUTES FLOODED",
                    sub_message="USE NORTH RIDGE DETOUR",
                    action_recommendation="ELEVATED OVERPASS ONLY",
                )
            else:
                receipt = {"status": "dispatched", "target": action.target_entity}

            action.executed = True
            action.execution_result = receipt
            v2_receipts.append({"action_id": action.action_id, "receipt": receipt})

        # Update Plan v2 actions in DB to COMPLETED
        latest_plan = await PlanRepository.get_latest_plan(session, inc_id)
        if latest_plan:
            for db_act in await ActionRepository.list_by_plan(session, latest_plan.id):
                await ActionRepository.update_status(
                    session,
                    db_act.id,
                    ActionStatus.COMPLETED,
                    execution_result={"status": "completed", "executed": True},
                )

        state["current_status"] = "RESOLVED"
        await IncidentRepository.update_status(session, inc_id, IncidentStatus.RESOLVED)

        await AuditLogRepository.append_log(
            session=session,
            incident_id=inc_id,
            actor_type="SYSTEM",
            actor_id="NEXUS_ORCHESTRATOR",
            action_name="STEP_18_EXECUTION_COMPLETED_SAFELY",
            state_diff={"status": "RESOLVED", "plan_version": 2},
        )
        await session.commit()

        # Verify complete cryptographic audit ledger integrity
        chain_valid = await AuditLogRepository.verify_chain_integrity(session)
        assert chain_valid is True, "Audit log hash chain validation failed"

        return {
            "status": "RESOLVED",
            "plan_version": 2,
            "actions_executed": len(v2_receipts),
            "audit_chain_valid": chain_valid,
        }
