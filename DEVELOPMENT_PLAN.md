# NEXUS — Engineering & Development Plan

**Project:** Autonomous Real-World Response & Operations Network  
**Target Event:** Ziro.digital National-Level Agentic AI Hackathon 2026  
**Execution Methodology:** Phased, Test-Driven Architecture with Strict Verification Gates

---

## 1. Directory & Codebase Layout

```
ziro/
├── PROJECT_SPEC.md                   # Formal product requirements & domain scope
├── ARCHITECTURE.md                   # Technical system design & state graph specification
├── DEVELOPMENT_PLAN.md               # Phased roadmap & verification checklist
├── README.md                         # Quickstart, scenario guide & presentation docs
├── docker-compose.yml                # Multi-container orchestration (App, DB, Vector, UI)
│
├── backend/                          # Python 3.11+ / FastAPI Core
│   ├── pyproject.toml                # Poetry / Pip dependency declarations
│   ├── Dockerfile                    # Containerization for backend services
│   ├── .env.example                  # Environment variable template
│   │
│   ├── app/
│   │   ├── main.py                   # FastAPI initialization, CORS, middleware, router mount
│   │   ├── config.py                 # Pydantic Settings (DB URLs, Gemini API keys, thresholds)
│   │   │
│   │   ├── models/                   # Relational & Typed Data Schemas
│   │   │   ├── state.py              # LangGraph NexusIncidentState & Pydantic primitives
│   │   │   ├── entities.py           # SQLAlchemy / SQLModel ORM models (Incidents, Actions, Audit)
│   │   │   └── api.py                # Inbound/Outbound REST & SSE schema definitions
│   │   │
│   │   ├── graph/                    # LangGraph Multi-Agent Orchestration
│   │   │   ├── builder.py            # Graph assembly, nodes, conditional edges, checkpointers
│   │   │   ├── nodes/
│   │   │   │   ├── ingest_node.py    # Report ingestion & feature extraction
│   │   │   │   ├── verify_node.py    # Cross-sensor & CCTV evidence verification
│   │   │   │   ├── impact_node.py    # Spatial hazard & facility impact analysis
│   │   │   │   ├── resource_node.py  # Inventory query & Dijkstra safe path router
│   │   │   │   ├── planner_node.py   # Operational action plan synthesis
│   │   │   │   ├── risk_gate_node.py # Deterministic policy & risk classification
│   │   │   │   ├── execution_node.py # Actuator dispatch against simulated municipal systems
│   │   │   │   └── monitor_node.py   # Continuous telemetry polling & surge delta detector
│   │   │   └── edges.py              # Conditional routing logic & replanning branch triggers
│   │   │
│   │   ├── services/                 # Business Logic & Infrastructure
│   │   │   ├── gemini_client.py      # Google GenAI SDK wrapper (Gemini 2.5 Flash / Pro)
│   │   │   ├── router_engine.py      # Dijkstra/A* graph algorithm over road networks
│   │   │   ├── audit_service.py      # Cryptographic SHA-256 chained audit log writer
│   │   │   └── vector_memory.py      # pgvector similarity search for historical incidents
│   │   │
│   │   ├── simulation/               # Safe Simulated Civil Systems & Actuators
│   │   │   ├── sensor_network.py     # Stream gauges & IoT precipitation simulator
│   │   │   ├── traffic_cameras.py    # Mock CCTV frame generator & depth proxies
│   │   │   ├── road_network_data.py  # Spatial road topology surrounding St. Jude Hospital
│   │   │   ├── fleet_depot.py        # High-water vehicles, pumps, and barrier units
│   │   │   ├── signage_actuator.py   # Variable Message Sign (VMS) mock hardware
│   │   │   └── scenario_runner.py    # Hackathon demo chaos controller (surge, tool failure)
│   │   │
│   │   └── api/                      # REST & SSE Endpoints
│   │       ├── incidents.py          # Create, list, stream, inspect incident state
│   │       ├── approvals.py          # Commander HITL approval / rejection endpoint
│   │       ├── simulation.py         # Live demo triggers (Cloudburst, Surge, Chaos)
│   │       └── audit.py              # Cryptographic audit ledger verification
│   │
│   └── tests/                        # Comprehensive Automated Test Suite
│       ├── conftest.py               # Test fixtures, mock Gemini client, in-memory DB
│       ├── test_graph_flow.py        # LangGraph state transitions & interrupt tests
│       ├── test_safety_gates.py      # Strict deterministic risk classification tests
│       ├── test_router_engine.py     # Dijkstra routing with flood edge penalties
│       ├── test_replanning_loop.py   # Simulated surge trigger & replanning assertion
│       └── test_tool_resilience.py   # Chaos fault injection & graceful degradation
│
└── frontend/                         # Next.js 15 (App Router) + TypeScript + Tailwind
    ├── package.json
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── src/
    │   ├── app/
    │   │   ├── layout.tsx            # Global styling, theme provider, header
    │   │   └── page.tsx              # Operations Center command dashboard
    │   ├── components/
    │   │   ├── MapView.tsx           # Interactive situational map (road nodes, flood polygons)
    │   │   ├── AgentTrace.tsx        # Multi-agent reasoning stream with live thoughts
    │   │   ├── ApprovalPanel.tsx     # HITL decision card with risk badges & sign-off controls
    │   │   ├── TelemetryPanel.tsx    # Live IoT stream gauge charts & water surge gauges
    │   │   └── SimulationBar.tsx     # Demo controls: "Inject Surge", "Trigger Replan"
    │   └── lib/
    │       ├── api.ts                # Backend client & SSE stream listener
    │       └── types.ts              # TypeScript interfaces mirroring backend schemas
```

---

## 2. Phased Development Roadmap

### Phase 1: Environment & Core Data Contracts
- Initialize repository with Docker Compose (PostgreSQL 16 with `pgvector` extension).
- Setup backend Python project with `fastapi`, `pydantic`, `langgraph`, `google-genai`, `sqlalchemy`, `asyncpg`.
- Implement core data contracts: `NexusIncidentState`, `GeoPoint`, `EvidenceItem`, `ImpactAssessment`, `ActionItem`, `AuditRecord`.
- Establish Alembic database migrations for relational tables and pgvector embedding tables.
- **Verification Gate 1:** Database container boots cleanly; Pydantic models validate sample payloads; migrations execute without warnings.

### Phase 2: Simulation Layer & Deterministic Tools
- Implement `road_network_data.py`: Construct spatial road graph around *St. Jude Memorial Hospital* with realistic road coordinates, distances, and water level limits.
- Implement `router_engine.py`: Dijkstra/A* shortest path algorithm with dynamic edge weighting based on flood level vs. vehicle clearance.
- Implement `sensor_network.py` and `traffic_cameras.py`: Synthetic IoT stream gauges and CCTV cameras with programmable flood levels.
- Implement `signage_actuator.py` and `fleet_depot.py`: Mock municipal dispatch systems recording actions in local memory.
- Implement `scenario_runner.py`: Deterministic state transitions for the 14-step hospital flooding scenario.
- **Verification Gate 2:** Router successfully finds alternate routes when primary artery is flooded; returns impassable error if all routes are blocked; unit tests achieve 100% pass on routing logic.

### Phase 3: Gemini Client & Multimodal Ingestion/Verification
- Implement `services/gemini_client.py` wrapping the official modern `google-genai` SDK.
- Configure structured JSON output schemas (`response_schema`) for Gemini 2.5 Flash and Gemini 2.5 Pro.
- Implement `nodes/ingest_node.py`: Extracts structured incident data from unstructured citizen text reports and images.
- Implement `nodes/verify_node.py`: Queries IoT sensors and CCTV analysis tools, cross-references historical incidents via `pgvector`, and outputs verified confidence scores.
- Implement `nodes/impact_node.py`: Computes spatial isolation risk to St. Jude Hospital.
- **Verification Gate 3:** Ingestion and verification nodes process raw flood inputs, validate against mock sensors, and produce valid typed Pydantic outputs with verified confidence scores > 0.85.

### Phase 4: LangGraph Orchestration & Deterministic Safety Gates
- Implement `nodes/resource_node.py` and `nodes/planner_node.py`: Synthesizes discrete action steps (VMS sign updates, high-water EMS dispatch, sandbag staging).
- Implement `nodes/risk_gate_node.py`: Deterministic risk classifier that categorizes actions into Tiers 1–4.
- Implement LangGraph State Graph with interrupt on `AWAITING_APPROVAL` when Tier 3 or 4 actions exist.
- Implement checkpointer persistence with Postgres saver so human commander can resume execution.
- Implement `nodes/execution_node.py`: Dispatches approved actions to simulated actuators.
- **Verification Gate 4:** Safety tests prove that any action labeled `CLOSE_PRIMARY_ARTERY` or `REROUTE_TRAUMA_PATIENTS` is strictly halted for human sign-off; graph cannot proceed to execution without approved commander token.

### Phase 5: Monitoring, Change Detection & Dynamic Replanning
- Implement `nodes/monitor_node.py`: Continuously evaluates water levels against active route thresholds.
- Implement `edges.py` conditional routing:
  - If water surge breaches detour threshold (`delta > 15%`), route to `replan_node`.
  - Replan node invalidates the active route, updates road graph edge weights, and re-invokes `planner_node` to compute Route Gamma.
- Implement `services/audit_service.py`: Computes SHA-256 chained hashes across every state transition and persists immutable audit trail.
- **Verification Gate 5:** Injecting an 18-inch water surge via API successfully triggers the replanning cycle; new route is computed; audit log contains complete cryptographic proof of all transitions.

### Phase 6: Modern Operations Center Dashboard (Frontend)
- Build Next.js 15 command center dashboard with Tailwind CSS.
- Implement `MapView.tsx`: Interactive SVG/Leaflet map rendering roads, hospital epicenter, flood zones, and real-time vehicle positions.
- Implement `AgentTrace.tsx`: Live SSE stream rendering agent reasoning cards, thought processes, and verification evidence.
- Implement `ApprovalPanel.tsx`: Interactive commander review modal with risk badges, impact diffs, and Approve/Reject triggers.
- Implement `TelemetryPanel.tsx` & `SimulationBar.tsx`: Live stream gauge charts and hackathon demo chaos buttons.
- **Verification Gate 6:** End-to-end user experience works seamlessly in browser; live SSE streams agent thought processes in real-time; human approval unlocks downstream execution.

### Phase 7: Hardening, Automated Test Suite & Hackathon Polish
- Complete full test coverage:
  - Unit tests for all nodes and tools.
  - Integration tests for end-to-end 14-step hospital flooding scenario.
  - Chaos fault-tolerance tests (simulated tool failure, network dropouts).
- Author comprehensive walkthrough documentation in `README.md`.
- Verify clean Docker Compose build with one-command launch (`docker compose up --build`).
- **Verification Gate 7:** All tests pass; system boots cleanly in containerized environment; demonstration scenario completes end-to-end without errors.

---

## 3. Testing Strategy & Quality Assurance

```
   ┌───────────────────────────────────────────────────┐
   │             E2E 14-Step Scenario Replay           │  <-- Automated run of full hospital flood lifecycle
   └─────────────────────────┬─────────────────────────┘
                             │
   ┌─────────────────────────▼─────────────────────────┐
   │         Safety & Boundary Penetration Tests       │  <-- Adversarial tests attempting unapproved high-risk execution
   └─────────────────────────┬─────────────────────────┘
                             │
   ┌─────────────────────────▼─────────────────────────┐
   │          Tool Resilience & Chaos Tests            │  <-- Injected HTTP 500s, CCTV dropouts, sensor timeouts
   └─────────────────────────┬─────────────────────────┘
                             │
   ┌─────────────────────────▼─────────────────────────┐
   │         Unit & Schema Validation Tests            │  <-- Routing graph algorithms, Pydantic contracts, node state diffs
   └───────────────────────────────────────────────────┘
```

1. **Deterministic Safety Assertion Test**:
   ```python
   def test_high_risk_action_never_executes_without_human_approval():
       # Initialize graph with flooded hospital scenario
       # Advance graph to risk gate
       # Assert graph interrupts at 'awaiting_approval'
       # Attempt forced execution without approval token -> Must raise PermissionError
   ```

2. **Dynamic Replanning Test**:
   ```python
   def test_sensor_surge_triggers_replanning_loop():
       # Execute initial approved plan (Route Beta)
       # Advance to monitoring node
       # Inject +18 inch surge at Route Beta node
       # Assert graph transitions state to 'REPLANNING'
       # Assert new Route Gamma is selected and proposed
   ```

3. **Chaos & Resilience Test**:
   ```python
   def test_tool_failure_falls_back_to_secondary_sensors():
       # Mock traffic camera service returning HTTP 503
       # Execute verification node
       # Assert verification succeeds via IoT stream gauge and historical vector database
       # Assert system_errors contains captured warning without crashing the graph
   ```
