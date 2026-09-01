"use client";

import React from "react";
import { GraphPathNode } from "@/lib/api";
import { Network, ArrowRight } from "lucide-react";
import { motion } from "framer-motion";

interface GraphPathProps {
  path: GraphPathNode[];
}

export function GraphPath({ path }: GraphPathProps) {
  if (!path || path.length === 0) return null;

  return (
    <div className="mt-4 p-4 rounded-xl bg-white/5 border border-white/10 backdrop-blur-md">
      <div className="flex items-center gap-2 mb-3 text-sm font-medium text-zinc-400">
        <Network size={16} className="text-accent" />
        Knowledge Graph Traversal
      </div>
      <div className="flex flex-wrap items-center gap-y-3">
        {path.map((node, idx) => (
          <React.Fragment key={`${node.node_id}-${idx}`}>
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: idx * 0.1 }}
              className="flex items-center px-3 py-1.5 bg-zinc-800/80 rounded-full border border-zinc-700/50 shadow-sm"
            >
              <span className="text-xs font-semibold text-accent mr-2 px-1.5 py-0.5 bg-accent/10 rounded-md">
                {node.node_type}
              </span>
              <span className="text-sm text-zinc-200">{node.label}</span>
            </motion.div>

            {idx < path.length - 1 && node.edge_type && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: (idx + 0.5) * 0.1 }}
                className="flex items-center mx-2 text-zinc-500"
              >
                <div className="h-[2px] w-4 bg-zinc-600/50 rounded-full"></div>
                <span className="mx-1 text-[10px] uppercase tracking-wider font-semibold text-zinc-400">
                  {node.edge_type}
                </span>
                <ArrowRight size={14} className="text-zinc-600/80 ml-1" />
              </motion.div>
            )}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
