"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import { queryKnowledgeBase, QueryResponse } from "@/lib/api";
import { GraphPath } from "./GraphPath";
import { Citations } from "./Citations";
import {
  Send, Loader2, User, Bot, AlertCircle, AlertTriangle,
  GitBranch, Layers, FileSearch, Cpu,
  CheckCircle2, Circle, Zap, Database, Network, ShieldAlert
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

// ─────────────────────────────────────────────────────────────────────────────
// Section 6: Suggested query chips
// ─────────────────────────────────────────────────────────────────────────────
const SUGGESTED_QUERIES = [
  "What does OSHA 1910.147 say about lockout/tagout procedures?",
  "What is the maintenance history for Pump P-101?",
  "List calibration requirements for gas detectors.",
  "What are the inspection findings for Vessel V-201?",
];

// ─────────────────────────────────────────────────────────────────────────────
// Section 5: Stage indicator stages
// ─────────────────────────────────────────────────────────────────────────────
const STAGES = [
  { id: "classifying_query", label: "Classifying query", icon: Cpu },
  { id: "searching_graph", label: "Searching knowledge graph", icon: Network },
  { id: "retrieving_documents", label: "Retrieving documents", icon: FileSearch },
  { id: "synthesizing_answer", label: "Synthesizing answer", icon: Layers },
];

function StageIndicator({ currentStage }: { currentStage: number }) {
  return (
    <div className="px-5 py-4 rounded-2xl bg-white/10 border border-white/5 rounded-tl-sm min-w-[280px]">
      <div className="space-y-2.5">
        {STAGES.map((stage, idx) => {
          const Icon = stage.icon;
          const isDone = idx < currentStage;
          const isActive = idx === currentStage;
          return (
            <div key={stage.id} className="flex items-center gap-3">
              <div className={`flex-shrink-0 w-5 h-5 flex items-center justify-center ${
                isDone ? "text-emerald-400" : isActive ? "text-accent" : "text-zinc-600"
              }`}>
                {isDone ? (
                  <CheckCircle2 size={16} />
                ) : isActive ? (
                  <div className="w-3 h-3 rounded-full bg-accent animate-pulse shadow-[0_0_8px_rgba(59,130,246,0.6)]" />
                ) : (
                  <Circle size={14} />
                )}
              </div>
              <span className={`text-sm ${
                isDone ? "text-zinc-400 line-through decoration-zinc-600" : 
                isActive ? "text-white font-medium" : "text-zinc-600"
              }`}>
                {stage.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Section 4: Structured answer bubble
// ─────────────────────────────────────────────────────────────────────────────
function ConfidenceBadge({ label }: { label: "High" | "Medium" | "Low" }) {
  const colors = {
    High: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    Medium: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    Low: "bg-zinc-500/20 text-zinc-400 border-zinc-500/30",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border ${colors[label]}`}>
      <Zap size={11} />
      {label} Confidence
    </span>
  );
}

function RetrievalBadge({ path }: { path: "vector" | "graph" | "hybrid" }) {
  const config = {
    vector: { icon: Database, label: "Vector Search", color: "text-blue-400" },
    graph: { icon: Network, label: "Graph Traversal", color: "text-violet-400" },
    hybrid: { icon: GitBranch, label: "Hybrid", color: "text-cyan-400" },
  };
  const { icon: Icon, label, color } = config[path] ?? config.vector;
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium opacity-70 ${color}`}>
      <Icon size={11} />
      {label}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Section 3: Escalation banner — prominent, must-see, above the answer
// ─────────────────────────────────────────────────────────────────────────────
function EscalationBanner({ notice }: { notice: string }) {
  return (
    <div
      id="escalation-banner"
      className="flex items-start gap-3 px-4 py-3 rounded-xl border border-orange-500/40 bg-orange-500/10 text-orange-300 mb-3"
    >
      <ShieldAlert size={18} className="flex-shrink-0 mt-0.5 text-orange-400" />
      <p className="text-sm font-medium leading-snug">{notice}</p>
    </div>
  );
}

interface AnswerBubbleProps {
  response: QueryResponse;
}

function AnswerBubble({ response }: AnswerBubbleProps) {
  const isSmallTalk = response.query_type === "small_talk";
  const hasEscalation = !!response.escalation_notice;
  const hasGroundednessWarning =
    Array.isArray(response.groundedness_warning) &&
    response.groundedness_warning.length > 0;

  return (
    <div className="flex flex-col gap-0 max-w-2xl">
      {/* Section 3: Escalation banner — rendered ABOVE the answer bubble */}
      {!isSmallTalk && hasEscalation && (
        <EscalationBanner notice={response.escalation_notice!} />
      )}

      <div className="px-5 py-4 rounded-2xl bg-white/10 text-zinc-100 rounded-tl-sm border border-white/5">
        {/* Primary answer */}
        <p className="text-[15px] leading-relaxed font-medium text-white">
          {response.answer}
        </p>

        {/* Supporting detail */}
        {!isSmallTalk && response.supporting_detail && (
          <p className="mt-3 text-sm leading-relaxed text-zinc-400 border-t border-white/5 pt-3">
            {response.supporting_detail}
          </p>
        )}

        {/* Section 1: Groundedness inline notice — below supporting detail */}
        {!isSmallTalk && hasGroundednessWarning && (
          <div
            id="groundedness-notice"
            className="mt-3 flex items-start gap-2 px-3 py-2 rounded-lg border border-amber-500/30 bg-amber-500/8 text-amber-400"
          >
            <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" />
            <span className="text-xs leading-relaxed">
              Some details in this answer could not be fully verified against source documents.
            </span>
          </div>
        )}

        {/* Citation note footnote */}
        {!isSmallTalk && response.citation_note && (
          <div className="mt-3 flex items-start gap-2 text-xs text-zinc-500 border-t border-white/5 pt-3">
            <FileSearch size={13} className="flex-shrink-0 mt-0.5 text-zinc-400" />
            <span className="italic">{response.citation_note}</span>
          </div>
        )}

        {/* Badges row */}
        {!isSmallTalk && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-white/5 pt-3">
            <RetrievalBadge path={response.retrieval_path ?? "vector"} />
            <ConfidenceBadge label={response.confidence_label ?? "Low"} />
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────
interface Message {
  id: string;
  role: "user" | "assistant";
  content?: string;
  metadata?: QueryResponse;
  error?: string;
  stage?: number; // -1 = done, 0-3 = current stage index
}

// ─────────────────────────────────────────────────────────────────────────────
// Main chat component
// ─────────────────────────────────────────────────────────────────────────────
export function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([{
    id: "welcome",
    role: "assistant",
    content: undefined,
    metadata: {
      answer: "Welcome to Cerebra-CorpCortex. I have access to your enterprise data, regulations, and records. What would you like to know?",
      supporting_detail: "",
      citation_note: "",
      citations: [],
      confidence: 1.0,
      confidence_label: "High",
      retrieval_path: "vector",
      graph_path: [],
      query_type: "small_talk",
      agent_used: [],
      retrieval_strategy: "none",
      latency_ms: 0,
    }
  }]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [hasInteracted, setHasInteracted] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const stageTimerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Simulate stage advancement for the loading message
  const advanceStages = useCallback((loadingMsgId: string) => {
    let stage = 0;
    const tick = () => {
      if (stage >= STAGES.length - 1) return;
      stage++;
      setMessages(prev => prev.map(m =>
        m.id === loadingMsgId ? { ...m, stage } : m
      ));
      stageTimerRef.current = setTimeout(tick, 1800 + Math.random() * 1200);
    };
    stageTimerRef.current = setTimeout(tick, 1200);
  }, []);

  const handleSubmit = async (questionText?: string) => {
    const text = (questionText ?? input).trim();
    if (!text || isLoading) return;

    setHasInteracted(true);
    const userMsg: Message = { id: Date.now().toString(), role: "user", content: text };
    const loadingId = `loading-${Date.now()}`;
    const loadingMsg: Message = { id: loadingId, role: "assistant", stage: 0 };

    setMessages(prev => [...prev, userMsg, loadingMsg]);
    setInput("");
    setIsLoading(true);

    advanceStages(loadingId);

    try {
      const response = await queryKnowledgeBase(text);
      if (stageTimerRef.current) clearTimeout(stageTimerRef.current);

      setMessages(prev => prev.map(m =>
        m.id === loadingId
          ? { ...m, stage: -1, metadata: response }
          : m
      ));
    } catch (err: any) {
      if (stageTimerRef.current) clearTimeout(stageTimerRef.current);
      setMessages(prev => prev.map(m =>
        m.id === loadingId
          ? { ...m, stage: -1, error: err.message }
          : m
      ));
    } finally {
      setIsLoading(false);
    }
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleSubmit();
  };

  const handleChipClick = (query: string) => {
    setInput(query);
    handleSubmit(query);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-120px)] w-full max-w-5xl mx-auto rounded-2xl overflow-hidden border border-white/10 shadow-2xl bg-black/40 backdrop-blur-xl">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6">
        <AnimatePresence initial={false}>
          {messages.map((msg) => (
            <motion.div
              key={msg.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className={`flex gap-3 ${msg.role === "user" ? "ml-auto flex-row-reverse max-w-xl" : "mr-auto max-w-4xl"}`}
            >
              {/* Avatar */}
              <div className={`flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center shadow-lg border ${
                msg.role === "user"
                  ? "bg-accent/20 border-accent/50 text-accent"
                  : "bg-emerald-500/20 border-emerald-500/50 text-emerald-400"
              }`}>
                {msg.role === "user" ? <User size={18} /> : <Bot size={18} />}
              </div>

              {/* Content */}
              <div className={`flex flex-col gap-3 min-w-0 ${msg.role === "user" ? "items-end" : "items-start"}`}>
                {/* User message */}
                {msg.role === "user" && (
                  <div className="px-5 py-3.5 rounded-2xl rounded-tr-sm bg-accent text-white text-[15px] leading-relaxed shadow-sm">
                    {msg.content}
                  </div>
                )}

                {/* Loading stage indicator (Section 5) */}
                {msg.role === "assistant" && msg.stage !== undefined && msg.stage >= 0 && !msg.metadata && !msg.error && (
                  <StageIndicator currentStage={msg.stage} />
                )}

                {/* Structured answer bubble (Section 4) */}
                {msg.role === "assistant" && msg.metadata && (
                  <AnswerBubble response={msg.metadata} />
                )}

                {/* Error state */}
                {msg.role === "assistant" && msg.error && (
                  <div className="flex items-center gap-2 px-5 py-3.5 rounded-2xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                    <AlertCircle size={16} />
                    {msg.error}
                  </div>
                )}

                {/* Graph path — below the answer bubble */}
                {msg.metadata?.graph_path && msg.metadata.graph_path.length > 0 && (
                  <GraphPath path={msg.metadata.graph_path} />
                )}

                {/* Citations — only for non-small-talk responses */}
                {msg.metadata && msg.metadata.query_type !== "small_talk" &&
                  msg.metadata.citations && msg.metadata.citations.length > 0 && (
                  <Citations citations={msg.metadata.citations} />
                )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="p-4 bg-white/5 border-t border-white/10 backdrop-blur-md">

        {/* Section 6: Query suggestion chips — visible only on first load */}
        {!hasInteracted && (
          <div className="flex flex-wrap gap-2 mb-3 max-w-4xl mx-auto">
            {SUGGESTED_QUERIES.map((query) => (
              <button
                key={query}
                onClick={() => handleChipClick(query)}
                disabled={isLoading}
                className="text-sm px-3.5 py-1.5 rounded-full border border-white/15 text-zinc-300 hover:border-accent/50 hover:text-white hover:bg-accent/10 transition-all disabled:opacity-40 cursor-pointer"
              >
                {query.length > 45 ? query.slice(0, 42) + "…" : query}
              </button>
            ))}
          </div>
        )}

        <form onSubmit={handleFormSubmit} className="relative max-w-4xl mx-auto flex items-center">
          <input
            id="chat-input"
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={isLoading}
            placeholder="e.g., What does 1910.147 say about lockout procedures?"
            className="w-full bg-black/50 border border-white/20 text-white placeholder-zinc-500 rounded-full pl-6 pr-14 py-4 outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-all shadow-inner"
          />
          <button
            id="chat-submit"
            type="submit"
            disabled={isLoading || !input.trim()}
            className="absolute right-2 p-2.5 rounded-full bg-accent text-white hover:bg-accent/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Send size={18} />
          </button>
        </form>
      </div>
    </div>
  );
}
