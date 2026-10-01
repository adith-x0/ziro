import React from "react";
import { AlertTriangle, Lock, Cpu, Database, Flame } from "lucide-react";

interface StatusRibbonProps {
  safetyGateStrict: boolean;
  activeScenarioName: string;
}

export const StatusRibbon: React.FC<StatusRibbonProps> = ({
  safetyGateStrict,
  activeScenarioName,
}) => {
  return (
    <div className="bg-gray-900 border-b border-gray-800 px-6 py-2.5 flex flex-wrap items-center justify-between text-xs text-gray-300 gap-3">
      <div className="flex items-center space-x-2">
        <span className="flex h-2 w-2 relative">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500"></span>
        </span>
        <span className="font-semibold text-gray-200">ACTIVE SCENARIO:</span>
        <span className="text-red-400 font-medium">{activeScenarioName}</span>
      </div>

      <div className="flex items-center space-x-6 text-gray-400 font-mono">
        <div className="flex items-center space-x-1.5">
          <Lock className="w-3.5 h-3.5 text-amber-400" />
          <span>Safety Gate:</span>
          <span className={safetyGateStrict ? "text-emerald-400 font-bold" : "text-amber-400"}>
            {safetyGateStrict ? "STRICT_DETERMINISTIC" : "ADVISORY"}
          </span>
        </div>

        <div className="flex items-center space-x-1.5">
          <Cpu className="w-3.5 h-3.5 text-blue-400" />
          <span>Model:</span>
          <span className="text-gray-200">Gemini 2.5 Flash / Pro</span>
        </div>

        <div className="flex items-center space-x-1.5">
          <Database className="w-3.5 h-3.5 text-purple-400" />
          <span>Storage:</span>
          <span className="text-gray-200">PostgreSQL + pgvector</span>
        </div>
      </div>
    </div>
  );
};
