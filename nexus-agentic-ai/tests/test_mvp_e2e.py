"""NEXUS MVP End-to-End Operational Lifecycle Verification Test.

Validates all 18 requirements of the primary vertical slice:
1. Perceive flood incident near City Hospital
2. Collect synthetic IoT evidence (water sensor, radar, citizen reports)
3. Multi-source verification (confidence >= 0.85)
4. Topological impact analysis (Route A blocked, hospital ingress at risk)
5. Deterministic ambulance search (AMB-01 selected: available, shortest dist, lowest workload)
6. Safe route calculation (ROUTE-B selected, 11 min ETA)
7. Plan v1 synthesis (sequenced action DAG)
8. Deterministic policy gate interception
9. HITL interrupt triggered (action blocked prior to human authorization)
10. Human commander approval (EOC Watch Commander authorization token)
11. Execution receipt generation (AMB-01 reserved with idempotency)
12. Corridor monitoring along ROUTE-B
13. Environmental change injection (ROUTE-B flooded/blocked)
14. Environmental anomaly detection
15. Invalidation of Plan v1
16. Replacement route calculation (ROUTE-C selected, 16 min ETA)
17. Plan v2 synthesis with preserved resource reservation
18. Safe completion and comprehensive immutable audit trail
"""

import sys
from pathlib import Path

# Add backend and root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from app.main import app
from fastapi.testclient import TestClient

from orchestration.mvp_runtime import mvp_runtime
from tools.synthetic_environment import simulated_fleet_service, synthetic_road_network


@pytest.fixture(autouse=True)
def reset_environment():
    """Reset simulated state before every test."""
    mvp_runtime.reset_simulation()
    yield
    mvp_runtime.reset_simulation()


def test_mvp_complete_workflow_18_steps():
    """Full 18-step vertical slice execution and assertion."""
    client = TestClient(app)

    # -------------------------------------------------------------------------
    # STEP 1: Incident Creation
    # -------------------------------------------------------------------------
    create_payload = {
        "description": "Heavy flooding is blocking the emergency access road near City Hospital. Ambulances may not be able to reach the emergency entrance.",
        "location": {"latitude": 8.5241, "longitude": 76.9366},
    }
    create_resp = client.post("/api/incidents", json=create_payload)
    assert create_resp.status_code == 201
    created_data = create_resp.json()
    incident_id = created_data["incident_id"]
    assert created_data["status"] == "RECEIVED"
    assert incident_id.startswith("inc-")

    # -------------------------------------------------------------------------
    # STEP 2 - 8: Start Pipeline up to Deterministic Policy Gate
    # -------------------------------------------------------------------------
    start_resp = client.post(f"/api/incidents/{incident_id}/start")
    assert start_resp.status_code == 200
    start_data = start_resp.json()

    # Step 9: Confirm HITL interrupt occurred and status is AWAITING_APPROVAL
    assert start_data["status"] == "AWAITING_APPROVAL"
    assert start_data["pending_approval"] is True

    # Step 3: Verification Check
    veri = start_data["verification"]
    assert veri["verified"] is True
    assert veri["confidence"] >= 0.85
    assert len(veri["evidence_ids"]) >= 3
    assert "WS-CITY-01" in veri["evidence_ids"]
    assert "RADAR-METRO-DOPPLER" in veri["evidence_ids"]

    # Step 4: Impact Analysis Check
    impact = start_data["impact"]
    assert impact["affected_hospital"] == "CITY-HOSPITAL"
    assert "ROUTE-A" in impact["affected_roads"]
    assert impact["emergency_access_risk"] == "HIGH"

    # Step 5: Resource Selection Check
    assert start_data["selected_ambulance"] == "AMB-01"

    # Step 6: Route Selection Check (Initial Route B)
    routing = start_data["routing"]
    assert routing["selected_route"] == "ROUTE-B"
    assert routing["estimated_time_minutes"] == 11.0
    assert "ROUTE-A" in routing["blocked_roads"]

    # Step 7: Plan v1 Action DAG Check
    plan_v1 = start_data["plan_v1"]
    assert plan_v1["version"] == 1
    assert plan_v1["status"] == "AWAITING_APPROVAL"
    reserve_action = next(a for a in plan_v1["actions"] if a["action_type"] == "RESERVE_AMBULANCE")
    assert reserve_action["risk_level"] == "MEDIUM"
    assert reserve_action["requires_approval"] is True

    # Confirm action did NOT execute prior to human approval
    assert simulated_fleet_service._fleet["AMB-01"].status == "AVAILABLE"

    # -------------------------------------------------------------------------
    # STEP 9: Inspect Pending Approvals
    # -------------------------------------------------------------------------
    approvals_resp = client.get("/api/approvals/pending")
    assert approvals_resp.status_code == 200
    pending_list = approvals_resp.json()
    assert len(pending_list) == 1
    approval = pending_list[0]
    approval_id = approval["approval_id"]
    assert approval["target"] == "AMB-01"
    assert approval["risk_level"] == "MEDIUM"

    # -------------------------------------------------------------------------
    # STEP 10: Human Commander Approves Action
    # -------------------------------------------------------------------------
    decision_payload = {"reviewer_id": "Commander Elena Vance (EOC Watch Commander)"}
    approve_resp = client.post(f"/api/approvals/{approval_id}/approve", json=decision_payload)
    assert approve_resp.status_code == 200
    approve_data = approve_resp.json()
    assert approve_data["status"] == "APPROVED_AND_RESUMED"

    # -------------------------------------------------------------------------
    # STEP 11 - 18: Verify Resumed Lifecycle & Replanning
    # -------------------------------------------------------------------------
    # Fetch final incident state
    incident_resp = client.get(f"/api/incidents/{incident_id}")
    assert incident_resp.status_code == 200
    final_state = incident_resp.json()

    # Step 11: Execution check
    assert len(final_state["execution_receipts"]) >= 1
    receipt = final_state["execution_receipts"][0]
    assert receipt["unit_id"] == "AMB-01"
    assert receipt["status"] == "RESERVED"
    assert simulated_fleet_service._fleet["AMB-01"].status == "RESERVED"

    # Step 12 - 14: Environment change check
    assert final_state["environment_changed"] is True
    assert synthetic_road_network.get_route("ROUTE-B").status == "BLOCKED"

    # Step 15: Plan v1 Invalidation check
    assert final_state["plan_v1"]["status"] == "INVALIDATED"
    assert "ROUTE-B" in (final_state["plan_v1"]["invalidation_reason"] or "")

    # Step 16 - 17: Plan v2 & Replacement Route check
    assert final_state["current_plan_version"] == 2
    assert final_state["plan_v2"] is not None
    assert final_state["plan_v2"]["version"] == 2
    assert final_state["plan_v2"]["selected_route"] == "ROUTE-C"
    assert final_state["routing"]["selected_route"] == "ROUTE-C"
    assert final_state["routing"]["estimated_time_minutes"] == 16.0

    # Step 18: Safe completion status
    assert final_state["status"] == "RESOLVED"

    # -------------------------------------------------------------------------
    # Audit Trail Verification
    # -------------------------------------------------------------------------
    audit_resp = client.get(f"/api/incidents/{incident_id}/audit")
    assert audit_resp.status_code == 200
    audit_events = audit_resp.json()
    event_types = [e["event_type"] for e in audit_events]

    expected_types = [
        "incident.created",
        "verification.started",
        "evidence.collected",
        "incident.verified",
        "impact.completed",
        "resource.selected",
        "route.selected",
        "plan.created",
        "approval.requested",
        "approval.approved",
        "action.executed",
        "environment.changed",
        "plan.invalidated",
        "plan.replanned",
    ]
    for exp in expected_types:
        assert exp in event_types, f"Missing audit event type: {exp}"

    # Timeline endpoint check
    timeline_resp = client.get(f"/api/incidents/{incident_id}/timeline")
    assert timeline_resp.status_code == 200
    timeline = timeline_resp.json()
    assert len(timeline) == len(audit_events)


def test_mvp_rejection_halts_safely():
    """Verify that human commander rejection halts execution without reserving resources."""
    client = TestClient(app)

    create_resp = client.post(
        "/api/incidents",
        json={
            "description": "Suspected flooding near secondary gate.",
            "location": {"latitude": 8.5241, "longitude": 76.9366},
        },
    )
    incident_id = create_resp.json()["incident_id"]
    client.post(f"/api/incidents/{incident_id}/start")

    pending_list = client.get("/api/approvals/pending").json()
    assert len(pending_list) == 1
    approval_id = pending_list[0]["approval_id"]

    # Reject the action
    reject_resp = client.post(
        f"/api/approvals/{approval_id}/reject",
        json={"reviewer_id": "Elena Vance (EOC Watch Commander)"},
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "REJECTED_AND_HALTED"

    final_state = client.get(f"/api/incidents/{incident_id}").json()
    assert final_state["status"] == "REJECTED"
    # Ensure ambulance remained AVAILABLE (never booked)
    assert simulated_fleet_service._fleet["AMB-01"].status == "AVAILABLE"
    assert len(final_state["execution_receipts"]) == 0

    # Ensure approval.rejected is in audit trail
    audit_events = client.get(f"/api/incidents/{incident_id}/audit").json()
    event_types = [e["event_type"] for e in audit_events]
    assert "approval.rejected" in event_types


def test_mvp_idempotency_guarantee():
    """Verify that dispatch reservation is strictly idempotent and prevents double-booking."""
    receipt1 = simulated_fleet_service.reserve_ambulance("AMB-01", "inc-test-01")
    assert receipt1.idempotent_replay is False

    receipt2 = simulated_fleet_service.reserve_ambulance("AMB-01", "inc-test-01")
    assert receipt2.idempotent_replay is True
    assert receipt1.tracking_token == receipt2.tracking_token
