# NEXUS — Autonomous Real-World Response & Operations Network

> **A multimodal, multi-agent system that detects a real-world incident, verifies evidence, analyzes impact, plans a response, uses tools/APIs, requests human approval for risky actions, executes approved actions, monitors outcomes, and replans when conditions change.**

Designed for the **Ziro.digital National-Level Agentic AI Hackathon 2026**.

---

## 📁 Monorepo Structure

```
nexus-agentic-ai/
├── backend/              # FastAPI core service, endpoints, and configuration
├── frontend/             # Next.js 14 App Router, TypeScript, Tailwind CSS
├── agents/               # Autonomous agent definitions and protocols
├── tools/                # Operational tools and actuator contracts
├── orchestration/        # LangGraph state machine, typed schemas, and safety gate
├── database/             # SQLAlchemy async models, session management, and Redis
├── tests/                # Automated pytest suite (health, schemas, risk gates, tools)
├── data/                 # Demonstration scenarios, road network topology, mock IoT feeds
├── docs/                 # Product specs, system architecture, and development plans
├── scripts/              # Environment verification and automated quality runners
├── docker-compose.yml    # PostgreSQL (pgvector), Redis, Backend, and Frontend orchestration
└── pyproject.toml        # Root Python workspace configuration
```

---

## ⚙️ Environment Configuration

### Backend (`backend/.env`)
Copy `backend/.env.example` to `backend/.env`:

```bash
cp backend/.env.example backend/.env
```

Key environment variables:
- `ENVIRONMENT`: `development` | `production`
- `LOG_LEVEL`: `INFO` | `DEBUG` | `WARNING`
- `HOST`: `0.0.0.0`
- `PORT`: `8000`
- `CORS_ORIGINS`: `["http://localhost:3000","http://127.0.0.1:3000"]`
- `DATABASE_URL`: `postgresql+asyncpg://nexus_user:nexus_secret_pass@localhost:5432/nexus_db`
- `REDIS_URL`: `redis://localhost:6379/0`
- `GEMINI_API_KEY`: Your Google GenAI API Key
- `SAFETY_GATE_STRICT_MODE`: `true` (enforces deterministic HITL approval for Tier 3/4 actions)

### Frontend (`frontend/.env.local`)
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## 🚀 Step-by-Step Local Setup & Execution Commands

### 1. Prerequisites
- **Python**: 3.11 or 3.12
- **Node.js**: 20+ and npm (or cmd.exe on Windows)
- **Docker** (optional for local standalone, required for full compose)

---

### 2. Backend Setup & Dependency Installation

From the monorepo root (`nexus-agentic-ai`):

#### Create & Activate Virtual Environment
```bash
# Windows (PowerShell or Command Prompt)
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

#### Install Backend & Development Dependencies
```bash
python -m pip install --upgrade pip
pip install -r backend/requirements-dev.txt
```

---

### 3. Database Migrations & Seeding (PostgreSQL & SQLite)

#### Run Alembic Migrations
```bash
# Applies all 11 tables (incidents, evidence, resources, routes, plans, actions, approvals, agent_runs, agent_events, audit_logs, memory_records)
alembic upgrade head
```

#### Seed Realistic Hospital Flooding Scenario Dataset
```bash
# Seeds St. Jude Memorial Hospital, high-water ambulances, road network, shelters, incident report, sensory evidence, and chained audit logs
python database/seed.py
```

---

### 4. Running Backend Tests, Linting & Type Checking

#### Run Pytest Suite
```bash
# Run all tests with verbosity
pytest tests -v

# Or run with coverage
pytest tests --cov=backend/app --cov=agents --cov=tools --cov=orchestration -v
```

#### Run Code Quality & Linting
```bash
# Ruff Lint Check
ruff check .

# Ruff Format Check
ruff format --check .

# Mypy Type Check
mypy backend/app agents tools orchestration
```

#### Run All Automated Checks (Single Command)
```bash
python scripts/run_checks.py
```

---

### 5. Running the Backend Server Locally

```bash
uvicorn app.main:app --app-dir backend --reload --port 8000
```

#### Verify Health Endpoints:
- Root: `http://localhost:8000/`
- General Health: `http://localhost:8000/health`
- Readiness Probe: `http://localhost:8000/health/ready`
- Liveness Probe: `http://localhost:8000/health/live`
- Interactive Swagger UI: `http://localhost:8000/docs`

---

### 6. Frontend Setup & Build

From the frontend directory (`nexus-agentic-ai/frontend`):

#### Install Frontend Dependencies
```bash
cd frontend
npm install
```
*(On Windows PowerShell if scripts are restricted, use: `cmd.exe /c "npm install"`)*

#### Build Next.js Application
```bash
npm run build
```
*(On Windows: `cmd.exe /c "npm run build"`)*

#### Run Next.js in Development Mode
```bash
npm run dev
```
Open `http://localhost:3000` to view the NEXUS Operations Command Center.

---

### 7. Full Stack Docker Compose (Postgres + pgvector + Redis + Backend + Frontend)

From the root (`nexus-agentic-ai`):

```bash
docker compose up --build
```

Services:
- **PostgreSQL 16 + pgvector**: `localhost:5432`
- **Redis 7**: `localhost:6379`
- **FastAPI Core**: `localhost:8000`
- **Next.js Frontend**: `localhost:3000`
