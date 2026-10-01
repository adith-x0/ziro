from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestration.state import (
    ActionItem,
    EvidenceItem,
    GeoPoint,
    ImpactAssessment,
)


def test_geopoint_validation():
    """Verify coordinate bounds validation on GeoPoint."""
    valid_point = GeoPoint(latitude=37.7749, longitude=-122.4194)
    assert valid_point.latitude == 37.7749
    assert valid_point.longitude == -122.4194

    with pytest.raises(ValidationError):
        GeoPoint(latitude=95.0, longitude=-122.4194)  # Latitude > 90


def test_evidence_item_schema():
    """Verify evidence schema constraints and confidence bounds."""
    evidence = EvidenceItem(
        evidence_id="ev-001",
        source_type="iot_stream_gauge",
        timestamp=datetime.now(UTC),
        data_payload={"water_level_inches": 32.4},
        confidence_score=0.95,
        corroborated=True,
    )
    assert evidence.confidence_score == 0.95
    assert evidence.corroborated is True

    with pytest.raises(ValidationError):
        EvidenceItem(
            evidence_id="ev-002",
            source_type="iot_stream_gauge",
            timestamp=datetime.now(UTC),
            data_payload={},
            confidence_score=1.5,  # Score > 1.0 invalid
            corroborated=False,
        )


def test_impact_assessment_schema():
    """Verify hospital impact assessment structure."""
    impact = ImpactAssessment(
        critical_facility_name="St. Jude Memorial Hospital",
        facility_type="trauma_hospital",
        ingress_cut_off=True,
        estimated_isolation_risk_minutes=45,
        severely_affected_corridors=["Metropolitan Parkway", "River Road"],
        population_density_index=0.88,
        summary_narrative="Ingress blocked by 30-inch flash flood.",
    )
    assert impact.ingress_cut_off is True
    assert len(impact.severely_affected_corridors) == 2


def test_action_item_schema():
    """Verify operational action item properties."""
    action = ActionItem(
        action_id="act-001",
        sequence_order=1,
        action_type="CLOSE_PRIMARY_ARTERY",
        target_entity="Metropolitan Parkway",
        risk_tier="TIER_4_HIGH",
        description="Close flooded roadway to all traffic.",
        execution_payload={"closure_points": ["Mile 4", "Mile 6"]},
        approval_required=True,
        approval_status="PENDING",
    )
    assert action.approval_required is True
    assert action.approval_status == "PENDING"
