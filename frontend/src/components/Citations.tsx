"use client";

import React, { useState } from "react";
import { Citation } from "@/lib/api";
import { FileText, Image as ImageIcon, ChevronDown, ChevronUp } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface CitationsProps {
  citations: Citation[];
}

function CitationCard({ cite, idx }: { cite: Citation; idx: number }) {
  const [expanded, setExpanded] = useState(false);
  const isImage = cite.doc_type === "image" || /\.(jpg|jpeg|png|tiff?|bmp)$/i.test(cite.title);
  const hasExtra = (cite.extra_excerpts?.length ?? 0) > 0 || (cite.extra_count ?? 0) > 0;

  const scorePercent = Math.round((cite.score ?? 0) * 100);
  const scoreColor =
    scorePercent >= 75 ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" :
    scorePercent >= 50 ? "text-amber-400 bg-amber-500/10 border-amber-500/20" :
    "text-zinc-400 bg-zinc-500/10 border-zinc-500/20";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: idx * 0.07 }}
      className="flex flex-col bg-white/5 border border-white/10 hover:bg-white/8 transition-colors rounded-xl shadow-md backdrop-blur-sm overflow-hidden"
    >
      {/* Header row */}
      <div
        className="flex items-start justify-between gap-3 p-3 cursor-pointer"
        onClick={() => hasExtra && setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2 text-sm font-medium text-zinc-300 min-w-0">
          {isImage
            ? <ImageIcon size={15} className="flex-shrink-0 text-indigo-400" />
            : <FileText size={15} className="flex-shrink-0 text-emerald-400" />}
          <span className="truncate" title={cite.title}>{cite.title}</span>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${scoreColor}`}>
            {scorePercent}%
          </span>
          {hasExtra && (
            expanded ? <ChevronUp size={14} className="text-zinc-500" /> : <ChevronDown size={14} className="text-zinc-500" />
          )}
        </div>
      </div>

      {/* Primary excerpt — truncated to 2 lines */}
      <div className="px-3 pb-3">
        <p className={`text-xs text-zinc-400 italic bg-black/20 p-2 rounded-lg border border-white/5 leading-relaxed ${expanded ? "" : "line-clamp-2"}`}>
          "{cite.text_span}"
        </p>

        {/* Extra excerpts on expand */}
        <AnimatePresence>
          {expanded && cite.extra_excerpts?.map((ex, i) => (
            <motion.p
              key={i}
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="text-xs text-zinc-400 italic bg-black/20 p-2 rounded-lg border border-white/5 leading-relaxed mt-2"
            >
              "{ex}"
            </motion.p>
          ))}
          {expanded && (cite.extra_count ?? 0) > 0 && (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-xs text-zinc-500 mt-1.5 pl-1"
            >
              +{cite.extra_count} more matched passages
            </motion.p>
          )}
        </AnimatePresence>

        {!expanded && hasExtra && (
          <button
            onClick={() => setExpanded(true)}
            className="text-xs text-accent/70 hover:text-accent mt-1.5 pl-1"
          >
            +{(cite.extra_excerpts?.length ?? 0) + (cite.extra_count ?? 0)} more →
          </button>
        )}
      </div>
    </motion.div>
  );
}

export function Citations({ citations }: CitationsProps) {
  if (!citations || citations.length === 0) return null;

  // Safety dedup by title — guarantees no duplicate cards even if backend sends them
  const seen = new Set<string>();
  const uniqueCitations = citations.filter((c) => {
    const key = (c.title || c.doc_id || "").trim().toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  return (
    <div className="mt-4 w-full max-w-2xl">
      <div className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2.5 px-1">
        Sources & Citations
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        {uniqueCitations.map((cite, idx) => (
          <CitationCard key={(cite.doc_id || cite.title || idx.toString()) + idx} cite={cite} idx={idx} />
        ))}
      </div>
    </div>
  );
}
