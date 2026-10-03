# NEXUS Tool Layer Contracts & Operational Specifications

This document defines the formal operational contracts, input/output data schemas, safety classifications, approval requirements, and failure modes for all 11 safe tools in the NEXUS Tool Layer.

Every tool executes within a strictly isolated **`simulation/mock environment`** and is accessible via the central `ToolRegistry`:
```python
result = await tool_registry.execute(tool_name, input_data, approval_token=token)
```

---

## 1. Tool Contracts Matrix

| Tool Name | Purpose | Input Schema | Output Schema | Risk Level | Approval Required | Timeout | Provider Interface / Mock | Failure Modes |
|---|---|---|---|---|---|---|---|---|
| `weather` | Queries meteorological stream gauges and doppler rainfall rates. | `WeatherInput`<br>• `latitude` (float: -90 to 90)<br>• `longitude` (float: -180 to 180) | `WeatherOutput`<br>• `temperature_c`<br>• `rainfall_rate_mm_hr`<br>• `flood_level` (LOW/MED/HIGH)<br>• `precipitation_type`<br>• `advisory`<br>• `is_simulation: True` | `LOW` | **No** (Auto) | 5.0s | `WeatherProvider`<br>→ `MockWeatherProvider` | • `VALIDATION_ERROR`: Coordinates out of bounds.<br>• `TIMEOUT_ERROR`: Remote sensor timeout.<br>• `EXECUTION_ERROR`: Sensor telemetry offline. |
| `incident_reports` | Aggregates localized citizen and field responder observations. | `IncidentReportsInput`<br>• `latitude` (float)<br>• `longitude` (float)<br>• `radius_km` (0.1 to 50) | `IncidentReportsOutput`<br>• `reports` (list of items)<br>• `total_reports`<br>• `summary`<br>• `is_simulation: True` | `LOW` | **No** (Auto) | 5.0s | `IncidentReportsProvider`<br>→ `MockIncidentReportsProvider` | • `VALIDATION_ERROR`: Invalid search radius.<br>• `TIMEOUT_ERROR`: Field dispatch database latency. |
| `image_analysis` | Multimodal visual assessment of flood depth and vehicle passability. | `ImageAnalysisInput`<br>• `image_url` (str \| None)<br>• `image_bytes_base64` (str \| None)<br>• `prompt` (str) | `ImageAnalysisOutput`<br>• `water_depth_estimate_inches`<br>• `submerged_landmarks`<br>• `vehicles_impassable`<br>• `confidence` (0.0 to 1.0)<br>• `is_simulation: True` | `LOW` | **No** (Auto) | 5.0s | `ImageAnalysisProvider`<br>→ `MockImageAnalysisProvider` | • `VALIDATION_ERROR`: Malformed image payload.<br>• `TIMEOUT_ERROR`: Vision model inference timeout. |
| `geolocation` | Spatial landmark and healthcare facility coordinate resolver. | `GeolocationInput`<br>• `query_address_or_landmark` (str, min length 2) | `GeolocationOutput`<br>• `resolved_name`<br>• `latitude`<br>• `longitude`<br>• `zone_type`<br>• `is_simulation: True` | `LOW` | **No** (Auto) | 5.0s | `GeolocationProvider`<br>→ `MockGeolocationProvider` | • `VALIDATION_ERROR`: Empty query string.<br>• `EXECUTION_ERROR`: Unresolvable spatial landmark. |
| `routing` | Deterministic topological graph routing bypassing compromised corridors. | `RoutingInput`<br>• `origin` (str)<br>• `destination` (str)<br>• `avoid_routes` (list[str])<br>• `vehicle_clearance_inches` (float) | `RoutingOutput`<br>• `selected_route_id`<br>• `route_name`<br>• `distance_km`<br>• `estimated_travel_time_minutes`<br>• `waypoints` (coords list)<br>• `is_passable`<br>• `is_simulation: True` | `LOW` | **No** (Auto) | 5.0s | `RoutingProvider`<br>→ `MockRoutingProvider`<br>*(NetworkX + Shapely)* | • `VALIDATION_ERROR`: Negative vehicle clearance.<br>• `EXECUTION_ERROR`: Topological disconnection (no safe corridor available). |
| `resource_search` | Discovers available municipal emergency units matching clearance criteria. | `ResourceSearchInput`<br>• `resource_type` (str)<br>• `required_clearance_inches` (float)<br>• `max_distance_km` (float) | `ResourceSearchOutput`<br>• `available_resources` (list)<br>• `selected_recommendation`<br>• `total_available`<br>• `is_simulation: True` | `LOW` | **No** (Auto) | 5.0s | `ResourceSearchProvider`<br>→ `MockResourceSearchProvider`<br>*(SimulatedFleetService)* | • `VALIDATION_ERROR`: Negative distance bounds.<br>• `TIMEOUT_ERROR`: Fleet database connection latency. |
| `hospital_status` | Queries critical care facility bed capacity, barriers, and ingress. | `HospitalStatusInput`<br>• `hospital_id` (str, e.g. CITY-HOSPITAL) | `HospitalStatusOutput`<br>• `hospital_id`<br>• `hospital_name`<br>• `emergency_room_status`<br>• `bed_capacity_available`<br>• `flood_barrier_active`<br>• `ingress_status`<br>• `is_simulation: True` | `LOW` | **No** (Auto) | 5.0s | `HospitalStatusProvider`<br>→ `MockHospitalStatusProvider` | • `VALIDATION_ERROR`: Empty facility ID.<br>• `EXECUTION_ERROR`: Facility record not found. |
| `notifications` | Dispatches simulated operational alerts to trauma bays and EOC consoles. | `NotificationInput`<br>• `channel` (SMS/EMAIL/PAGER/FEED)<br>• `recipient` (str)<br>• `title` (str)<br>• `message` (str)<br>• `priority` (LOW/MED/HIGH/CRIT) | `NotificationOutput`<br>• `delivery_id`<br>• `status` (SENT_SIMULATED)<br>• `channel`<br>• `recipient`<br>• `timestamp`<br>• `is_simulation: True` | `LOW` | **No** (Auto for internal simulated feeds) | 5.0s | `NotificationProvider`<br>→ `MockNotificationProvider` | • `VALIDATION_ERROR`: Unsupported channel or empty message.<br>• **Safety Interception**: Real 911 / EAS triggers strictly intercepted. |
| `ambulance_reservation` | Commits municipal emergency vehicle and issues dispatch receipt. | `AmbulanceReservationInput`<br>• `unit_id` (str)<br>• `incident_id` (str)<br>• `destination` (str)<br>• `approval_token` (str \| None) | `AmbulanceReservationOutput`<br>• `reservation_id`<br>• `unit_id`<br>• `status` (RESERVED)<br>• `tracking_token`<br>• `idempotent_replay`<br>• `is_simulation: True` | `MEDIUM` | **YES**<br>*(Commander Token Required)* | 5.0s | `AmbulanceReservationProvider`<br>→ `MockAmbulanceReservationProvider`<br>*(SimulatedFleetService)* | • `APPROVAL_TOKEN_REQUIRED`: Attempt to execute without valid commander approval token.<br>• `VALIDATION_ERROR`: Empty unit or incident ID.<br>• `EXECUTION_ERROR`: Unit already busy or not found in depot registry. |
| `incident_status_update` | Records operational lifecycle status transitions and audit notes. | `IncidentStatusUpdateInput`<br>• `incident_id` (str)<br>• `new_status` (str)<br>• `commentary` (str) | `IncidentStatusUpdateOutput`<br>• `incident_id`<br>• `previous_status`<br>• `current_status`<br>• `updated_at`<br>• `is_simulation: True` | `LOW` | **No** (Auto) | 5.0s | `IncidentStatusProvider`<br>→ `MockIncidentStatusProvider` | • `VALIDATION_ERROR`: Empty status or incident ID.<br>• `TIMEOUT_ERROR`: State storage latency. |
| `audit_logging` | Appends cryptographically hashed immutable event records. | `AuditLogInput`<br>• `incident_id` (str)<br>• `event_type` (str)<br>• `actor` (str)<br>• `summary` (str)<br>• `payload` (dict) | `AuditLogOutput`<br>• `event_id`<br>• `incident_id`<br>• `recorded_at`<br>• `cryptographic_digest` (sha256)<br>• `is_simulation: True` | `LOW` | **No** (Auto) | 5.0s | `AuditLogProvider`<br>→ `MockAuditLogProvider` | • `VALIDATION_ERROR`: Missing actor or event_type.<br>• `EXECUTION_ERROR`: Audit append serialization failure. |

---

## 2. Standardized Tool Execution Result (`ToolResult`)

Every tool execution returns a typed `ToolResult[TOutput]` containing:

```json
{
  "tool_name": "ambulance_reservation",
  "success": true,
  "status": "success",
  "output": {
    "reservation_id": "res-94b2f1aa",
    "unit_id": "AMB-01",
    "incident_id": "inc-8181a5b4",
    "status": "RESERVED",
    "tracking_token": "trk-bd0c0435a2a6",
    "timestamp": "2026-10-01T15:20:00Z",
    "idempotent_replay": false,
    "is_simulation": true,
    "environment": "simulation/mock environment"
  },
  "error": null,
  "error_code": null,
  "simulation_status": "simulation/mock environment",
  "is_simulation": true,
  "execution_metadata": {
    "execution_time_ms": 3.42,
    "started_at": "2026-10-01T15:20:00.100Z",
    "completed_at": "2026-10-01T15:20:00.103Z",
    "risk_level": "MEDIUM",
    "requires_approval": true,
    "timeout_seconds": 5.0
  }
}
```

---

## 3. Human-in-the-Loop Approval Enforcement

Direct calls to `ambulance_reservation` (or any tool with `requires_approval=True`) without a valid authorization token fail deterministically:

```json
{
  "tool_name": "ambulance_reservation",
  "success": false,
  "status": "error",
  "output": null,
  "error_code": "APPROVAL_TOKEN_REQUIRED",
  "error": {
    "error_code": "APPROVAL_TOKEN_REQUIRED",
    "message": "Action 'ambulance_reservation' is classified as MEDIUM risk and strictly requires a validated commander approval token. Direct unauthenticated execution is forbidden.",
    "details": {
      "risk_level": "MEDIUM",
      "requires_approval": true
    },
    "retryable": false
  },
  "simulation_status": "simulation/mock environment",
  "is_simulation": true,
  "execution_metadata": {
    "execution_time_ms": 0.45,
    "risk_level": "MEDIUM",
    "requires_approval": true
  }
}
```

This guarantees that:
1. LLM agents cannot bypass human authorization by hallucinating direct tool invocations.
2. The Policy Gatekeeper is the only authorized issuer of approval tokens.
3. Every mutating operational action remains strictly audited and commander-authorized.
