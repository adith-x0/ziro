"use client";

import React, { useState, useEffect } from "react";
import { Header } from "@/components/Header";
import { StatusRibbon } from "@/components/StatusRibbon";
import { fetchHealth, fetchReadiness, fetchIncidents } from "@/lib/api";
import { SystemHealth, IncidentSummary } from "@/lib/types";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Compass,
  FileText,
  MapPin,
  RefreshCw,
  ShieldCheck,
  Zap,
} from "lucide-react";

export default function OperationsDashboard() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [lastUpdated, setLastUpdated] = useState<string>("");

  const refreshData = async () => {
    setLoading(true);
    const [hData, incData] = await Promise.all([
      fetchHealth(),
      fetchIncidents(),
    ]);
    setHealth(hData);
    setIncidents(incData);
    setLastUpdated(new Date().toLocaleTimeString());
    setLoading(false);
  };

  useEffect(() => {
    refreshData();
    const interval = setInterval(refreshData, 15000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex flex-col min-h-screen bg-gray-950 text-gray-100">
      <Header
        online={Boolean(health && health.status === "ok")}
        version={health?.version || "0.1.0"}
      />
      <StatusRibbon
        safetyGateStrict={true}
        activeScenarioName="Flooding Disrupts Access to St. Jude Memorial Hospital"
      />

      <main className="flex-1 p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Situational Map & Spatial Assets (5 cols) */}
        <section className="lg:col-span-5 flex flex-col space-y-6">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center space-x-2">
                <MapPin className="w-5 h-5 text-blue-400" />
                <h2 className="text-base font-semibold text-white">Situational Spatial Overview</h2>
              </div>
              <span className="text-xs bg-red-500/10 text-red-400 border border-red-500/20 px-2 py-0.5 rounded font-mono">
                CRITICAL INUNDATION
              </span>
            </div>

            {/* Spatial Vector Mock View */}
            <div className="w-full h-64 bg-gray-950 rounded-lg border border-gray-800 relative overflow-hidden flex flex-col items-center justify-center p-4">
              <div className="absolute inset-0 opacity-15 bg-[radial-gradient(#3b82f6_1px,transparent_1px)] [background-size:16px_16px]"></div>
              
              <div className="relative z-10 text-center space-y-2">
                <div className="inline-flex items-center space-x-2 px-3 py-1 rounded bg-red-950/80 border border-red-800 text-red-300 text-xs">
                  <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse"></span>
                  <span>Epicenter: Metropolitan Pkwy @ River Rd</span>
                </div>
                <p className="text-xs text-gray-400">
                  Target Facility: <span className="text-blue-400 font-semibold">St. Jude Memorial Hospital (ER Bay)</span>
                </p>
                <div className="flex items-center justify-center space-x-2 text-xs font-mono pt-2">
                  <span className="text-red-400 bg-red-950/40 px-2 py-0.5 rounded border border-red-800/40">
                    Primary Route: BLOCKED (32.4 in)
                  </span>
                  <span className="text-emerald-400 bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-800/40">
                    Route Beta: PASSABLE (8.5 in)
                  </span>
                </div>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
              <div className="p-3 bg-gray-950/60 rounded-lg border border-gray-800">
                <div className="text-gray-400">IoT Stream Gauge SG-401</div>
                <div className="text-lg font-bold text-red-400 mt-1">32.4 in <span className="text-xs font-normal text-gray-400">(+8.4 in above flood)</span></div>
              </div>
              <div className="p-3 bg-gray-950/60 rounded-lg border border-gray-800">
                <div className="text-gray-400">Traffic CCTV CAM-08</div>
                <div className="text-lg font-bold text-amber-400 mt-1">Gridlock <span className="text-xs font-normal text-gray-400">(Sedans Impassable)</span></div>
              </div>
            </div>
          </div>

          {/* Incident Feed */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 shadow-sm flex-1">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center space-x-2">
                <FileText className="w-5 h-5 text-purple-400" />
                <h2 className="text-base font-semibold text-white">Tracked Emergency Incidents</h2>
              </div>
              <button
                onClick={refreshData}
                className="text-xs text-gray-400 hover:text-white flex items-center space-x-1"
                title="Refresh incident list"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
                <span>Sync</span>
              </button>
            </div>

            <div className="space-y-3">
              {incidents.length === 0 ? (
                <div className="p-4 text-center text-xs text-gray-500">
                  No active incidents loaded.
                </div>
              ) : (
                incidents.map((inc) => (
                  <div
                    key={inc.id}
                    className="p-3.5 bg-gray-950/80 rounded-lg border border-gray-800 hover:border-gray-700 transition"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold text-gray-100">{inc.title}</span>
                      <span className="text-xs px-2 py-0.5 rounded font-mono bg-red-950 text-red-300 border border-red-800">
                        {inc.severity}
                      </span>
                    </div>
                    <div className="flex items-center space-x-4 mt-2 text-xs text-gray-400 font-mono">
                      <span>ID: {inc.id}</span>
                      <span>Status: {inc.status}</span>
                      <span>Lat: {inc.latitude.toFixed(4)}, Lon: {inc.longitude.toFixed(4)}</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </section>

        {/* Center & Right Column: Multi-Agent Reasoning & HITL Approval Center (7 cols) */}
        <section className="lg:col-span-7 flex flex-col space-y-6">
          {/* Agent Workflow & Reasoning Pipeline */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center space-x-2">
                <Compass className="w-5 h-5 text-cyan-400" />
                <h2 className="text-base font-semibold text-white">Multi-Agent Operational Pipeline</h2>
              </div>
              <span className="text-xs font-mono text-gray-400">
                14-Step Closed Loop Control
              </span>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5 text-xs">
              <div className="p-3 bg-gray-950 rounded-lg border border-blue-900/50">
                <div className="text-blue-400 font-semibold">1. Perception</div>
                <p className="text-gray-400 mt-1 text-[11px]">Citizen report + photo normalized</p>
                <div className="mt-2 text-emerald-400 flex items-center space-x-1">
                  <CheckCircle2 className="w-3 h-3" />
                  <span>COMPLETE</span>
                </div>
              </div>

              <div className="p-3 bg-gray-950 rounded-lg border border-blue-900/50">
                <div className="text-blue-400 font-semibold">2. Verification</div>
                <p className="text-gray-400 mt-1 text-[11px]">IoT gauge & CCTV cross-checked</p>
                <div className="mt-2 text-emerald-400 flex items-center space-x-1">
                  <CheckCircle2 className="w-3 h-3" />
                  <span>94% CONFIDENCE</span>
                </div>
              </div>

              <div className="p-3 bg-gray-950 rounded-lg border border-blue-900/50">
                <div className="text-blue-400 font-semibold">3. Routing</div>
                <p className="text-gray-400 mt-1 text-[11px]">Dijkstra bypass calculated</p>
                <div className="mt-2 text-emerald-400 flex items-center space-x-1">
                  <CheckCircle2 className="w-3 h-3" />
                  <span>ROUTE BETA SAFE</span>
                </div>
              </div>

              <div className="p-3 bg-gray-950 rounded-lg border border-amber-900/50">
                <div className="text-amber-400 font-semibold">4. Safety Gate</div>
                <p className="text-gray-400 mt-1 text-[11px]">Tier 4 high-risk action intercepted</p>
                <div className="mt-2 text-amber-400 flex items-center space-x-1">
                  <Clock className="w-3 h-3" />
                  <span>AWAITING APPROVAL</span>
                </div>
              </div>
            </div>
          </div>

          {/* Human-in-the-Loop Approval Card */}
          <div className="bg-gray-900 border border-amber-900/40 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center space-x-2">
                <ShieldCheck className="w-5 h-5 text-amber-400" />
                <h2 className="text-base font-semibold text-white">Human-in-the-Loop Operational Gate</h2>
              </div>
              <span className="text-xs bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5 rounded font-mono">
                COMMANDER AUTHORIZATION REQUIRED
              </span>
            </div>

            <div className="p-4 bg-gray-950 rounded-lg border border-gray-800 space-y-3">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sm font-semibold text-gray-200">
                    Action: CLOSE_PRIMARY_ARTERY & REROUTE_EMS
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Target: Metropolitan Parkway from Mile 4 to Mile 6
                  </p>
                </div>
                <span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-red-950 text-red-300 border border-red-800">
                  TIER 4 (HIGH RISK)
                </span>
              </div>

              <p className="text-xs text-gray-300 bg-gray-900/60 p-2.5 rounded border border-gray-800">
                <strong className="text-amber-300">Agent Rationale:</strong> Water depth exceeds 32 inches at River Crossing. 
                Standard passenger vehicles and light ambulances risk hydrolocking. Directing traffic to Route Beta (Industrial Way) 
                preserves trauma bay access with +4.2 min transit time.
              </p>

              <div className="flex items-center justify-between pt-2">
                <div className="text-xs text-gray-400 font-mono">
                  State: <span className="text-amber-400">INTERRUPT_HALTED</span>
                </div>
                <div className="flex items-center space-x-3">
                  <button className="px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 text-gray-200 rounded font-medium transition">
                    Modify Parameters
                  </button>
                  <button className="px-4 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded font-medium shadow-sm transition">
                    Authorize Execution
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Hackathon Scenario Control Deck */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center space-x-2">
                <Zap className="w-5 h-5 text-yellow-400" />
                <h2 className="text-base font-semibold text-white">Scenario Telemetry & Chaos Controls</h2>
              </div>
              <span className="text-xs font-mono text-gray-400">Jury Presentation Tools</span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
              <button className="p-3 bg-gray-950 hover:bg-gray-800/80 rounded-lg border border-gray-800 text-left transition">
                <div className="font-semibold text-blue-400">Simulate Cloudburst</div>
                <p className="text-gray-400 mt-0.5 text-[11px]">Injects initial 30in flood at St. Jude Hospital</p>
              </button>

              <button className="p-3 bg-gray-950 hover:bg-gray-800/80 rounded-lg border border-red-900/40 text-left transition">
                <div className="font-semibold text-red-400">Inject +18in Surge</div>
                <p className="text-gray-400 mt-0.5 text-[11px]">Breaches Route Beta to trigger dynamic replan</p>
              </button>

              <button className="p-3 bg-gray-950 hover:bg-gray-800/80 rounded-lg border border-gray-800 text-left transition">
                <div className="font-semibold text-amber-400">Simulate CCTV Dropout</div>
                <p className="text-gray-400 mt-0.5 text-[11px]">Verifies sensor fallback resilience</p>
              </button>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-gray-800 bg-gray-950 px-6 py-3 flex items-center justify-between text-xs text-gray-500">
        <span>NEXUS Mission-Critical Emergency Operations Platform</span>
        <span>Last synced: {lastUpdated || "Initializing..."}</span>
      </footer>
    </div>
  );
}
