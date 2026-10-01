import React from "react";
import { ShieldAlert, Activity, Radio } from "lucide-react";

interface HeaderProps {
  online: boolean;
  version: string;
}

export const Header: React.FC<HeaderProps> = ({ online, version }) => {
  return (
    <header className="border-b border-gray-800 bg-gray-950/80 backdrop-blur px-6 py-4 flex items-center justify-between sticky top-0 z-50">
      <div className="flex items-center space-x-3">
        <div className="bg-blue-600/20 text-blue-400 p-2 rounded-lg border border-blue-500/30 flex items-center justify-center">
          <ShieldAlert className="w-6 h-6" />
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="text-xl font-bold tracking-tight text-white">NEXUS</h1>
            <span className="text-xs bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded-full font-mono">
              v{version}
            </span>
            <span className="text-xs bg-yellow-500/10 text-yellow-400 border border-yellow-500/20 px-2 py-0.5 rounded-full font-mono">
              Ziro Hackathon 2026
            </span>
          </div>
          <p className="text-xs text-gray-400">Autonomous Real-World Response & Operations Network</p>
        </div>
      </div>

      <div className="flex items-center space-x-4">
        <div className="flex items-center space-x-2 px-3 py-1.5 rounded-full text-xs font-mono border bg-gray-900 border-gray-800">
          <Radio className="w-3.5 h-3.5 text-blue-400 animate-pulse" />
          <span className="text-gray-400">Orchestrator:</span>
          <span className="text-blue-400 font-semibold">LangGraph Active</span>
        </div>

        <div className="flex items-center space-x-2 px-3 py-1.5 rounded-full text-xs font-mono border bg-gray-900 border-gray-800">
          <Activity
            className={`w-3.5 h-3.5 ${
              online ? "text-emerald-400" : "text-amber-400"
            }`}
          />
          <span className="text-gray-400">Backend API:</span>
          <span
            className={
              online ? "text-emerald-400 font-semibold" : "text-amber-400 font-semibold"
            }
          >
            {online ? "CONNECTED" : "STANDALONE"}
          </span>
        </div>
      </div>
    </header>
  );
};
