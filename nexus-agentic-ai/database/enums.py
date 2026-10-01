from enum import StrEnum


class IncidentSeverity(StrEnum):
    """Incident severity classification."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(StrEnum):
    """Incident operational lifecycle status."""

    REPORTED = "REPORTED"
    INGESTED = "INGESTED"
    VERIFIED = "VERIFIED"
    IMPACT_EVALUATED = "IMPACT_EVALUATED"
    ROUTED = "ROUTED"
    PLAN_SYNTHESIZED = "PLAN_SYNTHESIZED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    MONITORING = "MONITORING"
    REPLANNING = "REPLANNING"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class EvidenceType(StrEnum):
    """Sensory and observation evidence categories."""

    CITIZEN_PHOTO = "CITIZEN_PHOTO"
    CITIZEN_REPORT = "CITIZEN_REPORT"
    IOT_STREAM_GAUGE = "IOT_STREAM_GAUGE"
    TRAFFIC_CCTV = "TRAFFIC_CCTV"
    WEATHER_STATION = "WEATHER_STATION"
    HISTORICAL_RECORD = "HISTORICAL_RECORD"


class ActionRiskLevel(StrEnum):
    """Deterministic action safety risk tiers."""

    TIER_1_AUTO = "TIER_1_AUTO"
    TIER_2_LOW = "TIER_2_LOW"
    TIER_3_MEDIUM = "TIER_3_MEDIUM"
    TIER_4_HIGH = "TIER_4_HIGH"


class ActionStatus(StrEnum):
    """Lifecycle status of planned intervention actions."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ApprovalStatus(StrEnum):
    """Human-in-the-loop commander approval status."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    AUTO_APPROVED = "AUTO_APPROVED"


class AgentStatus(StrEnum):
    """State status for autonomous agent runs."""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
