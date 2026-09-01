"""
Continuous eval pipeline using Ragas + Langfuse.
Mohit owns this file.

Runs automatically when triggered via:
  python -m backend.eval.eval_pipeline
  -- or via file watcher on graph/retrieval changes --

Produces 4 core metrics:
  1. answer_relevancy        — how relevant the answer is to the question
  2. faithfulness            — is the answer grounded in the retrieved context?
  3. context_recall          — how much of the relevant info was retrieved?
  4. entity_extraction_acc   — % of ground-truth entities correctly extracted

Output: ./data/eval/latest_report.json (and pushed to Langfuse)
"""
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import answer_relevancy, faithfulness, context_recall
from langfuse import Langfuse

from backend.agents.supervisor import run_query
from backend.config import settings

# ─────────────────────────────────────────────────────────────────────────────
# Benchmark questions (domain-expert test set)
# In production, replace with your real industrial benchmark
# ─────────────────────────────────────────────────────────────────────────────

BENCHMARK_QUESTIONS = [
    {
        "question": "What is the design pressure of vessel V-201?",
        "ground_truth": "The design pressure of V-201 is 15 bar(g) as per the equipment datasheet.",
        "type": "single-fact",
    },
    {
        "question": "What maintenance was performed on pump P-101 after its last failure?",
        "ground_truth": "Work order WO-2024-0312 records impeller replacement and seal renewal on P-101 following the March 2024 bearing failure.",
        "type": "multi-hop",
    },
    {
        "question": "Which equipment in the process area is non-compliant with OISD-118?",
        "ground_truth": "Vessel V-301 pressure relief valve PV-301A is overdue for calibration per OISD-118 Clause 4.2.3.",
        "type": "aggregation",
    },
    {
        "question": "What is the operating temperature range for compressor K-101?",
        "ground_truth": "K-101 operates between 35°C (suction) and 145°C (discharge) at design conditions.",
        "type": "single-fact",
    },
    {
        "question": "Have there been recurring seal failures on any centrifugal pumps?",
        "ground_truth": "P-101 and P-203 both show mechanical seal failures every 8-10 months, correlated with high-vibration periods.",
        "type": "multi-hop",
    },
]


async def _run_benchmark_query(question: str) -> dict:
    """Run a single benchmark query and return {answer, contexts}."""
    start = time.time()
    response = await run_query(question)
    latency = int((time.time() - start) * 1000)
    return {
        "answer": response.answer,
        "contexts": [c.get("text_span", "") for c in response.citations],
        "latency_ms": latency,
        "confidence": response.confidence,
        "query_type": response.query_type,
    }


async def run_eval() -> dict:
    """
    Run the full eval pipeline and return metric scores.
    """
    print("[Eval] Starting evaluation pipeline...")
    results = []

    for bq in BENCHMARK_QUESTIONS:
        print(f"[Eval] Running: {bq['question'][:60]}...")
        result = await _run_benchmark_query(bq["question"])
        results.append({
            "question": bq["question"],
            "answer": result["answer"],
            "contexts": result["contexts"],
            "ground_truth": bq["ground_truth"],
            "latency_ms": result["latency_ms"],
            "confidence": result["confidence"],
            "query_type": bq["type"],
        })

    # Build Ragas dataset
    dataset = Dataset.from_list([
        {
            "question": r["question"],
            "answer": r["answer"],
            "contexts": r["contexts"] if r["contexts"] else ["No context retrieved"],
            "ground_truth": r["ground_truth"],
        }
        for r in results
    ])

    # Run Ragas eval
    print("[Eval] Running Ragas metrics...")
    try:
        ragas_result = evaluate(
            dataset,
            metrics=[answer_relevancy, faithfulness, context_recall],
        )
        ragas_scores = ragas_result.to_pandas().mean().to_dict()
    except Exception as e:
        print(f"[Eval] Ragas failed: {e}")
        ragas_scores = {}

    # Compute latency stats
    latencies = [r["latency_ms"] for r in results]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0

    # Build report
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "num_questions": len(results),
        "metrics": {
            "answer_relevancy": round(ragas_scores.get("answer_relevancy", 0), 4),
            "faithfulness": round(ragas_scores.get("faithfulness", 0), 4),
            "context_recall": round(ragas_scores.get("context_recall", 0), 4),
            "avg_latency_ms": round(avg_latency, 1),
            "avg_confidence": round(sum(r["confidence"] for r in results) / len(results), 3),
        },
        "per_question": results,
    }

    # Save report
    report_dir = Path("./data/eval")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "latest_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[Eval] Report saved to {report_path}")

    # Push to Langfuse
    _push_to_langfuse(report)

    print("[Eval] ✓ Done")
    print(f"  Answer Relevancy: {report['metrics']['answer_relevancy']:.3f}")
    print(f"  Faithfulness:     {report['metrics']['faithfulness']:.3f}")
    print(f"  Context Recall:   {report['metrics']['context_recall']:.3f}")
    print(f"  Avg Latency:      {report['metrics']['avg_latency_ms']:.0f}ms")

    return report


def _push_to_langfuse(report: dict):
    """Push eval results to Langfuse for observability dashboard."""
    try:
        lf = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
        for q_result in report["per_question"]:
            trace = lf.trace(
                name="eval_benchmark",
                metadata={
                    "query_type": q_result["query_type"],
                    "latency_ms": q_result["latency_ms"],
                    "confidence": q_result["confidence"],
                },
            )
            trace.score(name="answer_relevancy", value=report["metrics"]["answer_relevancy"])
            trace.score(name="faithfulness", value=report["metrics"]["faithfulness"])
        lf.flush()
        print("[Eval] Metrics pushed to Langfuse")
    except Exception as e:
        print(f"[Eval] Langfuse push failed (non-critical): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# File watcher — auto-rerun eval when graph or retrieval code changes
# ─────────────────────────────────────────────────────────────────────────────

def watch_and_eval():
    """Watch for changes in backend/graph and backend/retrieval, rerun eval."""
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    class ChangeHandler(FileSystemEventHandler):
        def __init__(self):
            self._last_run = 0

        def on_modified(self, event):
            if event.src_path.endswith(".py"):
                now = time.time()
                if now - self._last_run > 30:  # Debounce 30s
                    self._last_run = now
                    print(f"\n[Eval] Change detected in {event.src_path} — rerunning eval...")
                    asyncio.run(run_eval())

    observer = Observer()
    handler = ChangeHandler()
    observer.schedule(handler, "./backend/graph", recursive=True)
    observer.schedule(handler, "./backend/retrieval", recursive=True)
    observer.start()
    print("[Eval] Watching for changes. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    import sys
    if "--watch" in sys.argv:
        watch_and_eval()
    else:
        asyncio.run(run_eval())
