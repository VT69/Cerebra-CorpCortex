import { ChatInterface } from "@/components/ChatInterface";
import { GraphStatsCounter } from "@/components/GraphStatsCounter";
import { HeaderActions } from "@/components/HeaderActions";
import { getGraphStats } from "@/lib/api";
import { BrainCircuit } from "lucide-react";

// Server Component — fetches initial stats, then counter polls live on client
export default async function Home() {
  const statsData = await getGraphStats();
  const stats = statsData ?? { nodes: [] as { type: string; count: number }[], total_edges: 0 };
  const isBackendConnected = statsData !== null;

  const totalNodes = stats.nodes?.reduce((acc, curr) => acc + curr.count, 0) || 0;

  return (
    <div className="flex flex-col min-h-screen bg-black/50 text-white selection:bg-accent/30">
      <header className="sticky top-0 z-50 flex items-center justify-between px-6 py-4 border-b border-white/10 bg-black/60 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <div className="bg-accent text-white p-2 rounded-lg shadow-lg shadow-accent/20">
            <BrainCircuit size={24} />
          </div>
          <div>
            <h1 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-zinc-400">
              Cerebra-CorpCortex
            </h1>
            <p className="text-xs text-zinc-400 font-medium tracking-wide">ENTERPRISE AI BRAIN</p>
          </div>
        </div>

        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${isBackendConnected ? "bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.5)] animate-pulse" : "bg-red-500"}`}></div>
            <span className="text-sm font-medium text-zinc-300">
              {isBackendConnected ? "System Online" : "Backend Offline"}
            </span>
          </div>
          
          <HeaderActions />

          {/* Live-polling counter — flashes on new ingestion */}
          <GraphStatsCounter initialNodes={totalNodes} initialEdges={stats.total_edges} />
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center p-4 sm:p-8">
        <ChatInterface />
      </main>
    </div>
  );
}
