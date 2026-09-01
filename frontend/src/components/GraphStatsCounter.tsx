"use client";

import { useState, useEffect } from "react";
import { getGraphStats } from "@/lib/api";
import { Network } from "lucide-react";

export function GraphStatsCounter({ initialNodes = 0, initialEdges = 0 }) {
  const [nodes, setNodes] = useState(initialNodes);
  const [edges, setEdges] = useState(initialEdges);
  const [prevNodes, setPrevNodes] = useState(initialNodes);
  const [ticked, setTicked] = useState(false);

  useEffect(() => {
    const poll = async () => {
      try {
        const data = await getGraphStats();
        if (!data) return; // backend unreachable, keep current counts
        const totalNodes = data.nodes?.reduce((a: number, c: { count: number }) => a + c.count, 0) || 0;
        if (totalNodes !== nodes || data.total_edges !== edges) {
          setPrevNodes(nodes);
          setNodes(totalNodes);
          setEdges(data.total_edges);
          // Flash animation on change
          setTicked(true);
          setTimeout(() => setTicked(false), 1200);
        }
      } catch {}
    };

    const interval = setInterval(poll, 8000); // Poll every 8s
    return () => clearInterval(interval);
  }, [nodes, edges]);

  return (
    <div className={`hidden sm:flex items-center gap-4 bg-white/5 px-4 py-2 rounded-full border transition-all duration-500 ${ticked ? "border-accent/60 bg-accent/10" : "border-white/10"}`}>
      <div className="flex items-center gap-1.5">
        <Network size={16} className="text-zinc-400" />
        <span className={`text-sm font-bold transition-all duration-300 ${ticked ? "text-accent" : "text-white"}`}>
          {nodes}
        </span>
        <span className="text-xs text-zinc-500 uppercase">Nodes</span>
      </div>
      <div className="w-[1px] h-4 bg-white/10"></div>
      <div className="flex items-center gap-1.5">
        <span className={`text-sm font-bold transition-all duration-300 ${ticked ? "text-accent" : "text-white"}`}>
          {edges}
        </span>
        <span className="text-xs text-zinc-500 uppercase">Edges</span>
      </div>
    </div>
  );
}
