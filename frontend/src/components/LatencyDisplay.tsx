import React from "react";
import { Zap, Clock } from "lucide-react";
import { LatencyBreakdown } from "../lib/api";

interface LatencyDisplayProps {
  latencies: LatencyBreakdown;
  cragStatus: string;
}

export default function LatencyDisplay({ latencies, cragStatus }: LatencyDisplayProps) {
  const formatMs = (ms: number) => {
    return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms.toFixed(0)}ms`;
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "CORRECT":
        return "bg-green-500/10 text-green-400 border-green-500/20";
      case "AMBIGUOUS":
        return "bg-amber-500/10 text-amber-400 border-amber-500/20";
      case "NO_DATA_FOUND":
        return "bg-red-500/10 text-red-400 border-red-500/20";
      default:
        return "bg-zinc-800 text-zinc-400 border-zinc-700";
    }
  };

  return (
    <div className="bg-zinc-900/40 border border-zinc-800/80 rounded-xl p-4 backdrop-blur-sm space-y-3">
      <div className="flex items-center justify-between border-b border-zinc-800/60 pb-2">
        <span className="text-xs font-semibold text-zinc-400 uppercase tracking-widest flex items-center gap-1.5">
          <Zap className="h-3.5 w-3.5 text-indigo-400" />
          Rendimiento CRAG
        </span>
        <span className={`text-xs px-2 py-0.5 rounded border font-bold ${getStatusColor(cragStatus)}`}>
          {cragStatus}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 text-xs">
        {/* Recuperación */}
        <div className="bg-zinc-950/40 p-2.5 rounded-lg border border-zinc-900/60">
          <p className="text-zinc-500 font-medium">Búsqueda Híbrida & Rerank</p>
          <p className="text-sm font-semibold text-zinc-200 mt-0.5">{formatMs(latencies.retrieval)}</p>
        </div>

        {/* Reescritura */}
        <div className="bg-zinc-950/40 p-2.5 rounded-lg border border-zinc-900/60">
          <p className="text-zinc-500 font-medium">Reescritura de Query</p>
          <p className="text-sm font-semibold text-zinc-200 mt-0.5">
            {latencies.rewrite > 0 ? formatMs(latencies.rewrite) : "Ignorada (0ms)"}
          </p>
        </div>

        {/* Generación */}
        <div className="bg-zinc-950/40 p-2.5 rounded-lg border border-zinc-900/60">
          <p className="text-zinc-500 font-medium">Generación LLM</p>
          <p className="text-sm font-semibold text-zinc-200 mt-0.5">{formatMs(latencies.generation)}</p>
        </div>

        {/* Total */}
        <div className="bg-indigo-950/10 p-2.5 rounded-lg border border-indigo-900/30">
          <p className="text-indigo-400/70 font-medium flex items-center gap-1">
            <Clock className="h-3 w-3" />
            Latencia Total
          </p>
          <p className="text-sm font-bold text-indigo-400 mt-0.5">{formatMs(latencies.total)}</p>
        </div>
      </div>
    </div>
  );
}
