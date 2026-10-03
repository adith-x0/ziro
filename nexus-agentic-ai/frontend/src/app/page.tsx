"use client";

import React, { useState, useEffect } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Shield,
  Activity,
  ArrowRight,
  RefreshCw,
  Navigation,
  Truck,
  RotateCcw,
  Radio,
  FileCheck,
  Building2,
  AlertOctagon,
} from "lucide-react";
import {
  createMvpIncident,
  startMvpIncident,
  fetchMvpIncidentState,
  fetchPendingApprovals,
  approveMvpAction,
  rejectMvpAction,
  blockSimulationRoute,
  resetSimulation,
} from "@/lib/api";

type WorkflowStepStatus = "pending" | "active" | "completed" | "interrupted" | "warning";

interface WorkflowStep {
  id: string;
  name: string;
  category: string;
  status: WorkflowStepStatus;
  details?: string;
  badge?: string;
}

export default function NexusMvpDashboard() {
  const [incidentId, setIncidentId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [incidentState, setIncidentState] = useState<any>(null);
  const [pendingApproval, setPendingApproval] = useState<any>(null);
  const [approvalDecision, setApprovalDecision] = useState<string | null>(null);
  const [rejectionHalted, setRejectionHalted] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"workflow" | "audit" | "plan">("workflow");

  // Load pending approvals on mount or when incident changes
  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (incidentId && !incidentState?.status?.includes("RESOLVED")) {
      interval = setInterval(async () => {
        const state = await fetchMvpIncidentState(incidentId);
        if (state) setIncidentState(state);

        const approvals = await fetchPendingApprovals();
        if (approvals && approvals.length > 0) {
          setPendingApproval(approvals[0]);
        } else {
          setPendingApproval(null);
        }
      }, 1500);
    }
    return () => clearInterval(interval);
  }, [incidentId, incidentState?.status]);

  // Launch initial MVP scenario
  const handleLaunchScenario = async () => {
    setIsRunning(true);
    setErrorMsg(null);
    setRejectionHalted(false);
    setApprovalDecision(null);

    try {
      await resetSimulation();
      const inc = await createMvpIncident(
        "Heavy flooding is blocking the emergency access road near City Hospital. Ambulances may not be able to reach the emergency entrance.",
        8.5241,
        76.9366
      );

      if (!inc) {
        // Fallback simulated mode if backend not reachable
        runLocalSimulation();
        return;
      }

      setIncidentId(inc.incident_id);
      const startRes = await startMvpIncident(inc.incident_id);
      if (startRes) {
        setIncidentState(startRes);
      }
      const pending = await fetchPendingApprovals();
      if (pending && pending.length > 0) {
        setPendingApproval(pending[0]);
      }
    } catch (e: any) {
      console.warn("API offline, falling back to simulated mode:", e);
      runLocalSimulation();
    } finally {
      setIsRunning(false);
    }
  };

  // Local fallback simulation if backend is disconnected during offline previews
  const runLocalSimulation = () => {
    const mockIncId = `inc-${Math.random().toString(16).substring(2, 10)}`;
    setIncidentId(mockIncId);
    setIncidentState({
      incident_id: mockIncId,
      status: "AWAITING_APPROVAL",
      description: "Heavy flooding is blocking the emergency access road near City Hospital.",
      current_plan_version: 1,
      selected_ambulance: "AMB-01",
      verification: {
        verified: true,
        confidence: 0.9,
        evidence_ids: ["WS-CITY-01", "RADAR-METRO-DOPPLER", "rep-cit-01", "rep-cit-02"],
      },
      impact: {
        affected_hospital: "CITY-HOSPITAL",
        affected_roads: ["ROUTE-A"],
        emergency_access_risk: "HIGH",
      },
      routing: {
        selected_route: "ROUTE-B",
        estimated_time_minutes: 11.0,
        blocked_roads: ["ROUTE-A"],
      },
      plan_v1: {
        plan_id: "plan-mock-v1",
        version: 1,
        status: "AWAITING_APPROVAL",
        actions: [
          { action_id: "act-1", action_type: "VERIFY_INCIDENT", target_entity: "CITY-HOSPITAL", risk_level: "LOW", status: "COMPLETED" },
          { action_id: "act-2", action_type: "SELECT_AMBULANCE", target_entity: "AMB-01", risk_level: "LOW", status: "COMPLETED" },
          { action_id: "act-3", action_type: "SELECT_SAFE_ROUTE", target_entity: "ROUTE-B", risk_level: "LOW", status: "COMPLETED" },
          { action_id: "act-4", action_type: "RESERVE_AMBULANCE", target_entity: "AMB-01", risk_level: "MEDIUM", status: "AWAITING_APPROVAL" },
        ],
      },
    });
    setPendingApproval({
      approval_id: "appr-mock-1",
      action: "RESERVE_AMBULANCE",
      target: "AMB-01",
      risk_level: "MEDIUM",
      reason: "Resource allocation changes operational state and commits emergency vehicles.",
      supporting_evidence_count: 3,
    });
  };

  const handleApprove = async () => {
    if (!pendingApproval) return;
    setIsRunning(true);
    setApprovalDecision("APPROVED");

    try {
      if (pendingApproval.approval_id && !pendingApproval.approval_id.includes("mock")) {
        await approveMvpAction(pendingApproval.approval_id);
        if (incidentId) {
          const updated = await fetchMvpIncidentState(incidentId);
          setIncidentState(updated);
        }
      } else {
        // Mock progression
        setTimeout(() => {
          setIncidentState((prev: any) => ({
            ...prev,
            status: "RESOLVED",
            current_plan_version: 2,
            environment_changed: true,
            execution_receipts: [{ unit_id: "AMB-01", status: "RESERVED", tracking_token: "trk-mock-88" }],
            routing: { selected_route: "ROUTE-C", estimated_time_minutes: 16.0 },
            plan_v1: { ...prev?.plan_v1, status: "INVALIDATED", invalidation_reason: "Route B flooded" },
            plan_v2: {
              plan_id: "plan-mock-v2",
              version: 2,
              status: "COMPLETED",
              selected_route: "ROUTE-C",
            },
          }));
        }, 800);
      }
    } catch (e: any) {
      setErrorMsg(e.message);
    } finally {
      setPendingApproval(null);
      setIsRunning(false);
    }
  };

  const handleReject = async () => {
    if (!pendingApproval) return;
    setIsRunning(true);
    setApprovalDecision("REJECTED");
    setRejectionHalted(true);

    try {
      if (pendingApproval.approval_id && !pendingApproval.approval_id.includes("mock")) {
        await rejectMvpAction(pendingApproval.approval_id);
        if (incidentId) {
          const updated = await fetchMvpIncidentState(incidentId);
          setIncidentState(updated);
        }
      } else {
        setIncidentState((prev: any) => ({
          ...prev,
          status: "REJECTED",
        }));
      }
    } catch (e: any) {
      setErrorMsg(e.message);
    } finally {
      setPendingApproval(null);
      setIsRunning(false);
    }
  };

  const handleReset = async () => {
    await resetSimulation();
    setIncidentId(null);
    setIncidentState(null);
    setPendingApproval(null);
    setApprovalDecision(null);
    setRejectionHalted(false);
  };

  // Determine vertical workflow statuses based on current state
  const isVerified = Boolean(incidentState?.verification?.verified);
  const isImpactDone = Boolean(incidentState?.impact?.emergency_access_risk);
  const isResourceDone = Boolean(incidentState?.selected_ambulance);
  const isRouteDone = Boolean(incidentState?.routing?.selected_route);
  const isPlanDone = Boolean(incidentState?.plan_v1);
  const isApprovalPending = Boolean(pendingApproval);
  const isApproved = approvalDecision === "APPROVED" || incidentState?.status === "RESOLVED" || Boolean(incidentState?.execution_receipts?.length);
  const isRejected = rejectionHalted || incidentState?.status === "REJECTED";
  const isExecuted = isApproved;
  const isMonitoring = isApproved;
  const isEnvChanged = incidentState?.environment_changed || incidentState?.current_plan_version === 2;
  const isReplanned = incidentState?.current_plan_version === 2;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Navigation Bar */}
      <header className="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-50 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="w-9 h-9 rounded-lg bg-blue-600 flex items-center justify-center font-bold text-white shadow-lg shadow-blue-500/20">
            NX
          </div>
          <div>
            <h1 className="font-bold text-base tracking-wide text-white flex items-center gap-2">
              NEXUS <span className="text-xs px-2 py-0.5 rounded bg-blue-500/20 text-blue-400 font-mono">MVP VERTICAL SLICE</span>
            </h1>
            <p className="text-xs text-slate-400">Autonomous Real-World Operations & Response Network</p>
          </div>
        </div>

        <div className="flex items-center space-x-3">
          {incidentId && (
            <span className="text-xs font-mono px-2.5 py-1 rounded bg-slate-800 border border-slate-700 text-slate-300">
              ID: {incidentId}
            </span>
          )}
          <button
            onClick={handleLaunchScenario}
            disabled={isRunning}
            className="text-xs font-semibold px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition flex items-center space-x-1.5 shadow-md shadow-blue-600/20 disabled:opacity-50"
          >
            <Radio className="w-3.5 h-3.5" />
            <span>Launch Flooding Scenario</span>
          </button>
          <button
            onClick={handleReset}
            className="text-xs font-medium px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition flex items-center space-x-1"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Reset</span>
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
        
        {/* Left Column: Vertical Workflow (7 cols) */}
        <div className="lg:col-span-7 flex flex-col space-y-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-4">
              <div>
                <h2 className="text-sm font-semibold text-white uppercase tracking-wider">
                  Operational Workflow Lifecycle
                </h2>
                <p className="text-xs text-slate-400">Deterministic Multi-Agent State Machine</p>
              </div>
              <span className={`text-xs px-2.5 py-1 rounded-full font-mono font-semibold ${
                incidentState?.status === "RESOLVED"
                  ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                  : incidentState?.status === "AWAITING_APPROVAL"
                  ? "bg-amber-500/10 text-amber-400 border border-amber-500/30 animate-pulse"
                  : "bg-slate-800 text-slate-400"
              }`}>
                {incidentState?.status || "STANDBY"}
              </span>
            </div>

            {/* Vertical Workflow Steps */}
            <div className="space-y-3 font-mono text-sm">
              
              {/* 1. Incident Perception */}
              <div className="flex items-start space-x-3 p-3 rounded-lg bg-slate-950/70 border border-slate-800">
                <span className="mt-0.5">{incidentId ? "✓" : "○"}</span>
                <div className="flex-1">
                  <div className="font-semibold text-white text-xs">Perception & Ingestion</div>
                  <div className="text-xs text-slate-400 font-sans mt-0.5">
                    {incidentState?.description || "Standby for incident telemetry..."}
                  </div>
                </div>
              </div>

              {/* 2. Verification */}
              <div className={`flex items-start space-x-3 p-3 rounded-lg border ${
                isVerified ? "bg-slate-950/70 border-slate-800 text-slate-200" : "bg-slate-950/30 border-slate-900 text-slate-600"
              }`}>
                <span className={`mt-0.5 ${isVerified ? "text-emerald-400" : ""}`}>{isVerified ? "✓" : "○"}</span>
                <div className="flex-1">
                  <div className="font-semibold text-xs">Verification</div>
                  {isVerified && (
                    <div className="text-xs text-slate-400 font-sans mt-1 space-y-0.5">
                      <div>✓ Water sensor: flood_level = HIGH (WS-CITY-01)</div>
                      <div>✓ Radar: heavy_rainfall = TRUE (RADAR-METRO-DOPPLER)</div>
                      <div>✓ Incident reports: 2 independent citizen sources</div>
                      <div className="text-emerald-400 font-mono font-bold pt-1">
                        CONFIDENCE: {Math.round((incidentState?.verification?.confidence || 0.9) * 100)}%
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* 3. Impact Analysis */}
              <div className={`flex items-start space-x-3 p-3 rounded-lg border ${
                isImpactDone ? "bg-slate-950/70 border-slate-800 text-slate-200" : "bg-slate-950/30 border-slate-900 text-slate-600"
              }`}>
                <span className={`mt-0.5 ${isImpactDone ? "text-emerald-400" : ""}`}>{isImpactDone ? "✓" : "○"}</span>
                <div className="flex-1">
                  <div className="font-semibold text-xs">Impact Analysis</div>
                  {isImpactDone && (
                    <div className="text-xs text-slate-400 font-sans mt-1">
                      Target: <span className="text-blue-400 font-medium">{incidentState.impact.affected_hospital}</span> | Access: <span className="text-amber-400 font-medium">{incidentState.impact.hospital_access}</span> | Flooded: <span className="text-red-400 font-mono">{incidentState.impact.affected_roads?.join(", ")}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* 4. Resource Selection */}
              <div className={`flex items-start space-x-3 p-3 rounded-lg border ${
                isResourceDone ? "bg-slate-950/70 border-slate-800 text-slate-200" : "bg-slate-950/30 border-slate-900 text-slate-600"
              }`}>
                <span className={`mt-0.5 ${isResourceDone ? "text-emerald-400" : ""}`}>{isResourceDone ? "✓" : "○"}</span>
                <div className="flex-1">
                  <div className="font-semibold text-xs">Resource Selection</div>
                  {isResourceDone && (
                    <div className="text-xs text-slate-400 font-sans mt-1">
                      Deterministic selection: <span className="text-emerald-400 font-mono font-bold">{incidentState.selected_ambulance}</span> (Ford F-550 High-Water 4x4, 2.1km away, lowest workload)
                    </div>
                  )}
                </div>
              </div>

              {/* 5. Route Selection */}
              <div className={`flex items-start space-x-3 p-3 rounded-lg border ${
                isRouteDone ? "bg-slate-950/70 border-slate-800 text-slate-200" : "bg-slate-950/30 border-slate-900 text-slate-600"
              }`}>
                <span className={`mt-0.5 ${isRouteDone ? "text-emerald-400" : ""}`}>{isRouteDone ? "✓" : "○"}</span>
                <div className="flex-1">
                  <div className="font-semibold text-xs">Route Selection</div>
                  {isRouteDone && (
                    <div className="text-xs text-slate-400 font-sans mt-1">
                      ROUTE-A is blocked. Selected initial corridor: <span className="text-blue-400 font-bold font-mono">ROUTE-B</span> ({incidentState.routing.estimated_time_minutes} min ETA via Industrial Way Detour)
                    </div>
                  )}
                </div>
              </div>

              {/* 6. Plan Generated */}
              <div className={`flex items-start space-x-3 p-3 rounded-lg border ${
                isPlanDone ? "bg-slate-950/70 border-slate-800 text-slate-200" : "bg-slate-950/30 border-slate-900 text-slate-600"
              }`}>
                <span className={`mt-0.5 ${isPlanDone ? "text-emerald-400" : ""}`}>{isPlanDone ? "✓" : "○"}</span>
                <div className="flex-1">
                  <div className="font-semibold text-xs">Plan Generated (Version {incidentState?.current_plan_version || 1})</div>
                  {isPlanDone && (
                    <div className="text-xs text-slate-400 font-sans mt-1">
                      Sequenced DAG with 4 actions. High-risk actions flagged for deterministic safety gate.
                    </div>
                  )}
                </div>
              </div>

              {/* 7. Human Approval Gate */}
              <div className={`flex items-start space-x-3 p-3 rounded-lg border ${
                isApprovalPending
                  ? "bg-amber-950/30 border-amber-600/50 text-amber-300"
                  : isApproved
                  ? "bg-slate-950/70 border-slate-800 text-slate-200"
                  : isRejected
                  ? "bg-red-950/30 border-red-800 text-red-300"
                  : "bg-slate-950/30 border-slate-900 text-slate-600"
              }`}>
                <span className="mt-0.5 font-bold">
                  {isApproved ? "✓" : isApprovalPending ? "⏸" : isRejected ? "✕" : "○"}
                </span>
                <div className="flex-1">
                  <div className="font-semibold text-xs flex items-center justify-between">
                    <span>Human Approval (Safety Gate)</span>
                    {isApprovalPending && (
                      <span className="text-[10px] uppercase font-bold bg-amber-500 text-slate-950 px-2 py-0.5 rounded">
                        Action Required
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-400 font-sans mt-1">
                    {isApprovalPending && "Deterministic policy halted execution: Action RESERVE_AMBULANCE requires authorization."}
                    {isApproved && "Commander Elena Vance (EOC Watch Commander) authorized dispatch."}
                    {isRejected && "Action REJECTED by Commander. Execution halted safely."}
                  </div>
                </div>
              </div>

              {/* 8. Execution */}
              <div className={`flex items-start space-x-3 p-3 rounded-lg border ${
                isExecuted ? "bg-slate-950/70 border-slate-800 text-slate-200" : "bg-slate-950/30 border-slate-900 text-slate-600"
              }`}>
                <span className={`mt-0.5 ${isExecuted ? "text-emerald-400" : ""}`}>{isExecuted ? "✓" : "○"}</span>
                <div className="flex-1">
                  <div className="font-semibold text-xs">Execution</div>
                  {isExecuted && (
                    <div className="text-xs text-slate-400 font-sans mt-1">
                      Ambulance AMB-01 reserved in fleet inventory with idempotency guarantee.
                    </div>
                  )}
                </div>
              </div>

              {/* 9. Corridor Monitoring */}
              <div className={`flex items-start space-x-3 p-3 rounded-lg border ${
                isMonitoring ? "bg-slate-950/70 border-slate-800 text-slate-200" : "bg-slate-950/30 border-slate-900 text-slate-600"
              }`}>
                <span className={`mt-0.5 ${isMonitoring ? "text-emerald-400" : ""}`}>{isMonitoring ? "✓" : "○"}</span>
                <div className="flex-1">
                  <div className="font-semibold text-xs">Monitoring</div>
                  {isMonitoring && (
                    <div className="text-xs text-slate-400 font-sans mt-1">
                      Active hydrological surveillance along ROUTE-B corridor.
                    </div>
                  )}
                </div>
              </div>

              {/* 10. Environmental Change & Replanning */}
              <div className={`flex items-start space-x-3 p-3 rounded-lg border ${
                isEnvChanged ? "bg-slate-950/70 border-slate-800 text-slate-200" : "bg-slate-950/30 border-slate-900 text-slate-600"
              }`}>
                <span className={`mt-0.5 ${isReplanned ? "text-emerald-400" : ""}`}>{isReplanned ? "✓" : "○"}</span>
                <div className="flex-1">
                  <div className="font-semibold text-xs">Replanning & Dynamic Rerouting</div>
                  {isEnvChanged && (
                    <div className="text-xs text-slate-400 font-sans mt-1 space-y-1">
                      <div className="text-amber-400 font-semibold flex items-center gap-1">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        <span>ENVIRONMENT CHANGE: ROUTE-B became blocked.</span>
                      </div>
                      <div className="text-slate-300">Plan v1 invalidated → Plan v2 generated.</div>
                      <div className="text-emerald-400 font-bold font-mono">
                        ✓ ROUTE-C selected (North Ring Elevated Overpass, 16.0 min ETA)
                      </div>
                    </div>
                  )}
                </div>
              </div>

            </div>
          </div>
        </div>

        {/* Right Column: Interactive Approval Card & Telemetry (5 cols) */}
        <div className="lg:col-span-5 flex flex-col space-y-4">
          
          {/* Interactive Human-In-The-Loop Approval Card */}
          {isApprovalPending && pendingApproval && (
            <div className="bg-amber-950/40 border-2 border-amber-500/70 rounded-xl p-5 shadow-xl animate-in fade-in">
              <div className="flex items-center space-x-2 text-amber-400 mb-3 font-mono font-bold text-xs uppercase tracking-wider">
                <Shield className="w-4 h-4" />
                <span>ACTION REQUIRES APPROVAL</span>
              </div>

              <div className="space-y-3 text-sm font-sans">
                <div>
                  <span className="text-xs text-slate-400 block font-mono">Reserve:</span>
                  <span className="text-white font-bold text-base font-mono">{pendingApproval.target || "AMB-01"}</span>
                </div>

                <div>
                  <span className="text-xs text-slate-400 block font-mono">Risk Level:</span>
                  <span className="text-amber-400 font-bold font-mono text-xs px-2 py-0.5 rounded bg-amber-500/20 border border-amber-500/40">
                    {pendingApproval.risk_level || "MEDIUM"}
                  </span>
                </div>

                <div>
                  <span className="text-xs text-slate-400 block font-mono">Reason:</span>
                  <p className="text-slate-300 text-xs mt-0.5 leading-relaxed">
                    {pendingApproval.reason || "Resource allocation changes operational state and commits emergency vehicles."}
                  </p>
                </div>

                <div>
                  <span className="text-xs text-slate-400 block font-mono">Supporting Evidence:</span>
                  <span className="text-emerald-400 text-xs font-mono">
                    {pendingApproval.supporting_evidence_count || 3} supporting sources.
                  </span>
                </div>

                {/* Actions */}
                <div className="pt-3 border-t border-amber-500/30 flex items-center space-x-3 font-mono">
                  <button
                    onClick={handleApprove}
                    disabled={isRunning}
                    className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-2.5 px-4 rounded-lg text-xs uppercase tracking-wider transition shadow-md shadow-emerald-600/30 disabled:opacity-50"
                  >
                    [ APPROVE ]
                  </button>
                  <button
                    onClick={handleReject}
                    disabled={isRunning}
                    className="flex-1 bg-rose-600/80 hover:bg-rose-600 text-white font-bold py-2.5 px-4 rounded-lg text-xs uppercase tracking-wider transition disabled:opacity-50"
                  >
                    [ REJECT ]
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Environmental Simulation Banner (After Approval) */}
          {isEnvChanged && (
            <div className="bg-red-950/40 border border-red-800 rounded-xl p-5 shadow-lg">
              <div className="flex items-center space-x-2 text-red-400 mb-2 font-mono font-bold text-xs uppercase">
                <AlertOctagon className="w-4 h-4" />
                <span>⚠ ENVIRONMENT CHANGE DETECTED</span>
              </div>
              <p className="text-xs text-slate-300 mb-2">
                Hydrological surge detected along canal detour: <span className="font-mono text-red-400 font-bold">ROUTE-B is BLOCKED.</span>
              </p>
              <div className="p-3 bg-slate-950/80 rounded-lg border border-slate-800 space-y-1 text-xs font-mono">
                <div className="text-amber-400">NEXUS REPLANNING...</div>
                <div className="text-slate-400">Plan v1 invalidated. Preserved AMB-01 allocation.</div>
                <div className="text-emerald-400 font-bold">✓ ROUTE-C selected (North Ring Overpass)</div>
              </div>
            </div>
          )}

          {/* System Telemetry & Spatial Overview */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
            <h3 className="text-xs font-semibold text-white uppercase tracking-wider font-mono">
              Synthetic Operational Environment
            </h3>

            <div className="space-y-2 text-xs font-sans">
              <div className="flex items-center justify-between p-2.5 bg-slate-950 rounded border border-slate-800">
                <span className="text-slate-400">Target Hospital:</span>
                <span className="font-semibold text-blue-400 font-mono">CITY-HOSPITAL</span>
              </div>
              <div className="flex items-center justify-between p-2.5 bg-slate-950 rounded border border-slate-800">
                <span className="text-slate-400">Active Corridor:</span>
                <span className="font-bold text-emerald-400 font-mono">
                  {incidentState?.routing?.selected_route || "ROUTE-B"}
                </span>
              </div>
              <div className="flex items-center justify-between p-2.5 bg-slate-950 rounded border border-slate-800">
                <span className="text-slate-400">Reserved Resource:</span>
                <span className="font-semibold text-white font-mono">
                  {incidentState?.selected_ambulance || "AMB-01"}
                </span>
              </div>
              <div className="flex items-center justify-between p-2.5 bg-slate-950 rounded border border-slate-800">
                <span className="text-slate-400">Plan Version:</span>
                <span className="font-semibold text-white font-mono">
                  Version {incidentState?.current_plan_version || 1}
                </span>
              </div>
            </div>

            {/* Quick Route Status Legend */}
            <div className="pt-2 border-t border-slate-800 grid grid-cols-3 gap-2 text-[11px] font-mono text-center">
              <div className="p-2 rounded bg-red-950/40 border border-red-900/60 text-red-300">
                ROUTE-A<br/><span className="text-[10px] text-red-400">BLOCKED</span>
              </div>
              <div className={`p-2 rounded border text-center ${
                isEnvChanged
                  ? "bg-red-950/40 border-red-900/60 text-red-300"
                  : "bg-emerald-950/40 border-emerald-900/60 text-emerald-300"
              }`}>
                ROUTE-B<br/><span className="text-[10px]">{isEnvChanged ? "BLOCKED" : "SAFE (11m)"}</span>
              </div>
              <div className="p-2 rounded bg-emerald-950/40 border border-emerald-900/60 text-emerald-300">
                ROUTE-C<br/><span className="text-[10px] text-emerald-400">SAFE (16m)</span>
              </div>
            </div>
          </div>

        </div>

      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800 bg-slate-900/60 px-6 py-3 text-xs text-slate-500 flex items-center justify-between font-mono">
        <div>NEXUS Agentic Operations Network • Ziro Hackathon 2026</div>
        <div>Deterministic State Machines • LangGraph • Zero-Hallucination Routing</div>
      </footer>
    </div>
  );
}
