from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/incidents", tags=["Incidents & Operations"])


class IncidentReportRequest(BaseModel):
    """Citizen or sensor incident report payload."""

    title: str = Field(
        ..., json_schema_extra={"example": "Flooding near St. Jude Memorial Hospital"}
    )
    description: str = Field(
        ...,
        json_schema_extra={"example": "Metropolitan Parkway submerged under ~30 inches of water."},
    )
    latitude: float = Field(..., ge=-90.0, le=90.0, json_schema_extra={"example": 37.7749})
    longitude: float = Field(..., ge=-180.0, le=180.0, json_schema_extra={"example": -122.4194})
    image_url: str | None = Field(
        default=None, json_schema_extra={"example": "https://example.com/flood-photo.jpg"}
    )
    severity: str = Field(default="HIGH", json_schema_extra={"example": "CRITICAL"})


class IncidentResponse(BaseModel):
    """Incident response model."""

    id: str
    title: str
    status: str
    severity: str
    latitude: float
    longitude: float
    created_at: datetime


# In-memory incident registry for scaffold testing
_MOCK_INCIDENTS: list[IncidentResponse] = [
    IncidentResponse(
        id="inc-hospital-flood-001",
        title="Hospital Access Cutoff - St. Jude Memorial",
        status="INGESTED",
        severity="CRITICAL",
        latitude=37.7749,
        longitude=-122.4194,
        created_at=datetime.now(UTC),
    )
]


@router.get("", response_model=list[IncidentResponse], summary="List Incidents")
async def list_incidents() -> list[IncidentResponse]:
    """Retrieve all tracked incidents."""
    return _MOCK_INCIDENTS


@router.get("/{incident_id}", response_model=IncidentResponse, summary="Get Incident by ID")
async def get_incident(incident_id: str) -> IncidentResponse:
    """Retrieve specific incident details."""
    for inc in _MOCK_INCIDENTS:
        if inc.id == incident_id:
            return inc
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
