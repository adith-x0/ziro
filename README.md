# NEXUS — Autonomous Real-World Response & Operations Network

[![Ziro Hackathon 2026](https://img.shields.io/badge/Ziro.digital-AI_Hackathon_2026-blue.svg)](https://ziro.digital)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-teal.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Stateful_Orchestration-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![Google Gemini](https://img.shields.io/badge/Google_Gemini-2.5_Flash_%2F_Pro-purple.svg)](https://ai.google.dev/)
[![Next.js](https://img.shields.io/badge/Next.js-15_(App_Router)-black.svg)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16_+_pgvector-blue.svg)](https://www.postgresql.org/)

> **A multimodal, multi-agent system that detects a real-world incident, verifies evidence, analyzes impact, plans a response, uses tools/APIs, requests human approval for risky actions, executes approved actions, monitors outcomes, and replans when conditions change.**

---

## 📑 Core Documentation Index
- **[PROJECT_SPEC.md](PROJECT_SPEC.md)**: Product vision, user personas, primary scenario, agent charters, tool schemas, data model, safety matrix, and project scope.
- **[ARCHITECTURE.md](ARCHITECTURE.md)**: Technical architecture, LangGraph state graph, typed state schema, human-in-the-loop interrupts, deterministic safety gates, and simulation engine.
- **[DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)**: Phased implementation roadmap, testing strategy, verification gates, and directory layout.

---

## 🚨 Primary Demonstration Scenario: Flooding Disrupts Access to a Hospital

In our flagship demonstration scenario, a severe urban storm causes flash flooding that submerges **Metropolitan Parkway**, the primary inbound ambulance artery to **St. Jude Memorial Hospital** (a regional Level 1 Trauma Center).

NEXUS executes an end-to-end, 14-step autonomous operations workflow:

```
 1. Perceive Incident  ──▶ 2. Extract Data    ──▶ 3. Verify Evidence ──▶ 4. Assess Impact
         │                                                                    │
         ▼                                                                    ▼
 8. Risk Scoring       ◀── 7. Plan Actions    ◀── 6. Compute Routes  ◀── 5. Find Resources
         │
         ▼
 9. HITL Approval Gate ──▶ 10. Execute Actions ──▶ 11. Monitor Sensors ──▶ 12. Detect Surge
                                                             ▲                    │
                                                             │                    ▼
 14. Immutable Audit   ◀─────────────────────────────────────┴──────────── 13. Replan Route
```

1. **Perceive Incident**: Ingests citizen report, smartphone flood photo, and GPS coordinates near St. Jude Memorial Hospital.
2. **Extract Structured Information**: Multimodal Gemini model parses unstructured data into typed `ExtractedIncident` records.
3. **Verify Evidence**: Cross-references municipal IoT stream gauges, CCTV camera feeds, and historical flood vectors to generate a confidence score.
4. **Analyze Impact**: Evaluates spatial isolation risk to the trauma center, critical utility proximity, and emergency ingress blockage.
5. **Find Resources**: Queries municipal depot database for high-clearance ambulances, mobile water pumps, and barrier units.
6. **Calculate Safe Routes**: Deterministic Dijkstra routing engine computes safe bypass routes avoiding flooded road segments.
7. **Create Action Plan**: Synthesizes a structured DAG of operational actions (VMS signage, dispatch orders, hospital alerts).
8. **Classify Action Risk**: Deterministic safety gate categorizes actions into Tiers 1–4. Major road closures and hospital reroutes are flagged as **Tier 4 (High Risk)**.
9. **Request Human Approval**: State machine safely halts at an interrupt checkpoint (`AWAITING_APPROVAL`). The Operations Commander inspects the diff and signs off.
10. **Execute Approved Actions**: Dispatches approved commands to simulated municipal systems (digital road signs, emergency vehicle dispatch).
11. **Monitor Situation**: Continuous background agent polls stream gauge sensors along active detour routes.
12. **Detect Changes**: Sensor detects sudden +18-inch water surge breaching Secondary Detour Route B.
13. **Replan Dynamically**: Automatically triggers replanning loop, invalidates Route B, computes Route C, and escalates updated advisory.
14. **Maintain Auditable Record**: Appends tamper-evident, SHA-256 chained audit records for post-incident review.

---

## 🏛️ Non-Negotiable Engineering Principles

1. **Not a Chatbot**: NEXUS is not a conversational bot. It is an autonomous operations state machine with deterministic transitions and typed state schemas.
2. **Explicit Agent Responsibilities**: Each agent in the network has a narrow, formally specified charter, discrete inputs, and bounded outputs.
3. **Deterministic Safety Barriers**: High-risk actions (e.g., closing major transit arteries, rerouting emergency ambulances) **never** execute autonomously. They are intercepted by hardcoded deterministic rules requiring human commander sign-off.
4. **Safe Simulation Environment**: All downstream execution targets safe, simulated civil systems (dispatch simulators, dynamic message sign simulators) rather than production emergency infrastructure.
5. **Resilience & Fault Tolerance**: System gracefully degrades if a tool fails (e.g. CCTV camera offline falls back to stream gauges and historical vector memory).
6. **Dynamic Closed-Loop Replanning**: The system does not stop after execution. It continuously monitors real-world telemetry and replans when conditions breach tolerances.
7. **Immutable Audit Ledger**: Every prompt, completion, tool call, verification score, human approval, and actuator payload is permanently recorded with cryptographic hash chaining.

---

## 🛠️ Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Backend Core** | Python 3.11+, FastAPI, Pydantic v2 | High-performance asynchronous API & schema validation |
| **Agent Orchestration** | LangGraph (Python) | Stateful multi-agent graph with interrupts & checkpointers |
| **Foundation Model** | Google Gemini (2.5 Flash & 2.5 Pro) | Multimodal perception, OCR, and operational plan synthesis via modern `google-genai` SDK |
| **Primary Database** | PostgreSQL 16 | Relational incident storage, action logs, audit trail |
| **Vector Memory** | `pgvector` | Historical incident retrieval & semantic playbook matching |
| **Frontend UI** | Next.js 15 (App Router), TypeScript, Tailwind CSS | Real-time Operations Center dashboard |
| **Simulation Services** | Python In-Memory Services | Simulated IoT stream gauges, CCTV cameras, road graph network |
| **Containerization** | Docker Compose | Multi-container reproducible deployment |

---

## 🚀 Quickstart & Setup

### Prerequisites
- Docker & Docker Compose (v2.20+)
- Python 3.11+
- Node.js 20+ and npm / pnpm
- Google Gemini API Key (`GEMINI_API_KEY`)

### 1. Clone & Configure Environment
```bash
# Clone the repository
git clone https://github.com/your-org/nexus-operations-network.git
cd nexus-operations-network

# Backend environment setup
cp backend/.env.example backend/.env
# Edit backend/.env and insert your GEMINI_API_KEY
```

### 2. Launch with Docker Compose
```bash
docker compose up --build
```
This spins up:
- **PostgreSQL 16 + pgvector**: Port `5432`
- **FastAPI Backend Core**: Port `8000` (Swagger UI at `http://localhost:8000/docs`)
- **Next.js Operations Dashboard**: Port `3000` (`http://localhost:3000`)

### 3. Local Development Setup (Alternative)

#### Backend
```bash
cd backend
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

#### Frontend
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:3000` to access the NEXUS Operations Command Center.

---

## 🧪 Running Tests & Quality Verification

NEXUS includes a rigorous automated test suite enforcing safety guarantees:

```bash
cd backend
pytest -v
```

Key test suites:
- `tests/test_safety_gates.py`: Asserts that high-risk actions can **never** execute autonomously without a valid commander sign-off token.
- `tests/test_graph_flow.py`: Verifies complete LangGraph state transitions across all 14 steps.
- `tests/test_router_engine.py`: Tests Dijkstra road network routing with flooded edge weight penalties.
- `tests/test_replanning_loop.py`: Injects an artificial water surge and asserts automatic replanning.
- `tests/test_tool_resilience.py`: Simulates camera service outages (HTTP 500) and asserts graceful sensor fallback.

---

## 🎬 Hackathon Live Demonstration Walkthrough

During the live jury presentation, follow this sequence:

1. **Step 1: Ingest Citizen Report**
   - Click **"Load Hospital Flood Scenario"** on the dashboard.
   - Observe real-time ingestion of citizen description + photo showing water submerging Metropolitan Parkway.
2. **Step 2–7: Watch Multi-Agent Reasoning Stream**
   - The **Verification Agent** queries the IoT Stream Gauge and Traffic Camera (corroboration confidence: 94%).
   - The **Impact Agent** detects St. Jude Memorial Hospital ingress cutoff.
   - The **Resource & Routing Agent** locates high-water rescue trucks and computes Route Beta.
   - The **Planner Agent** synthesizes a 4-step action plan.
3. **Step 8–9: Human-in-the-Loop Approval Gate**
   - The **Deterministic Safety Gate** marks `CLOSE_METROPOLITAN_PARKWAY` as **Tier 4 (High Risk)**.
   - The system pauses. The **Approval Panel** lights up with a full diff and risk justification.
   - As Operations Commander, click **"Approve Action Plan"**.
4. **Step 10–11: Execution & Real-Time Monitoring**
   - Simulated actuators update Variable Message Signs and dispatch high-water units.
   - The system enters active monitoring mode.
5. **Step 12–13: Inject Chaos & Trigger Dynamic Replanning**
   - Click the red **"Inject +18in Water Surge"** button in the Simulation Bar.
   - Watch the **Monitoring Agent** detect the breach on Route Beta and trigger the **Replanning Loop**.
   - NEXUS automatically re-routes traffic through Route Gamma without crashing.
6. **Step 14: Inspect Tamper-Evident Audit Ledger**
   - Open the **Audit Ledger** tab to view the complete SHA-256 chained log verifying every agent decision.
