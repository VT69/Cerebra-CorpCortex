"""
Hybrid reranker — combines vector similarity + graph path relevance
into a single ranked list before final synthesis.

Mohit owns this file.

Strategy:
  final_score = (VECTOR_WEIGHT * vector_score) + (GRAPH_WEIGHT * graph_score)
  If top combined score < threshold → use union of both, not just top-k.
"""
from backend.config import settings


def rerank(
    vector_hits: list[dict],
    graph_hits: list[dict],
) -> list[dict]:
    """
    Merge and rerank results from both retrieval paths.

    vector_hits: [{chunk_id, text, score, metadata}]
    graph_hits:  [{properties, graph_path, source_docs}]

    Returns unified ranked list of context items for the LLM synthesizer.
    """
    unified = []

    # Add vector results (already scored 0-1)
    for hit in vector_hits:
        unified.append({
            "source": "vector",
            "text": hit["text"],
            "vector_score": hit["score"],
            "graph_score": 0.0,
            "final_score": hit["score"] * settings.RERANKER_VECTOR_WEIGHT,
            "metadata": hit.get("metadata", {}),
            "graph_path": [],
            "doc_id": hit.get("metadata", {}).get("doc_id", ""),
        })

    # Add graph results with estimated relevance score
    # Graph results don't have a natural 0-1 score; use path length as proxy
    # (shorter path = more directly relevant)
    for i, hit in enumerate(graph_hits):
        path_len = len(hit.get("graph_path", []))
        # Inverse path length score: 1-hop=1.0, 2-hop=0.75, 3-hop=0.5
        graph_score = max(0.3, 1.0 - (path_len - 1) * 0.25) if path_len > 0 else 0.5

        # Convert graph hit to text summary for LLM context
        props = hit.get("properties", {})
        text = _graph_hit_to_text(props, hit.get("graph_path", []))

        unified.append({
            "source": "graph",
            "text": text,
            "vector_score": 0.0,
            "graph_score": graph_score,
            "final_score": graph_score * settings.RERANKER_GRAPH_WEIGHT,
            "metadata": {},
            "graph_path": hit.get("graph_path", []),
            "doc_id": hit.get("source_docs", [""])[0] if hit.get("source_docs") else "",
        })

    # Deduplicate by text similarity (simple: exact doc_id match)
    seen_doc_ids = set()
    deduped = []
    for item in unified:
        key = item["doc_id"] or item["text"][:100]
        if key not in seen_doc_ids:
            seen_doc_ids.add(key)
            deduped.append(item)

    # Sort by final_score descending
    deduped.sort(key=lambda x: x["final_score"], reverse=True)

    return deduped[:20]  # Top 20 for synthesis


def _graph_hit_to_text(properties: dict, graph_path: list[dict]) -> str:
    """Convert a graph result to readable text for LLM context."""
    lines = []
    for key, value in properties.items():
        if isinstance(value, dict):
            for k2, v2 in value.items():
                lines.append(f"{k2}: {v2}")
        else:
            lines.append(f"{key}: {value}")

    if graph_path:
        path_str = " → ".join(
            f"{n.get('node_type', '?')}({n.get('label', n.get('node_id', '?'))})"
            for n in graph_path
        )
        lines.append(f"Graph path: {path_str}")

    return "\n".join(lines)
