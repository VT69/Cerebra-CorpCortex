"""
ChromaDB vector search.
Mohit owns this file.
"""
import chromadb
from openai import AsyncOpenAI
from backend.config import settings

_oai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def _get_collection():
    client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    return client.get_or_create_collection(name=settings.CHROMA_COLLECTION_NAME)


async def vector_search(query: str, top_k: int = None) -> list[dict]:
    """
    Search ChromaDB for the most relevant chunks.
    Returns list of {chunk_id, text, score, metadata}.
    Falls back to both retrieval paths if top score < threshold.
    """
    top_k = top_k or settings.VECTOR_TOP_K

    # Embed the query
    response = await _oai.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=query[:8191],
    )
    query_embedding = response.data[0].embedding

    # Query ChromaDB
    collection = _get_collection()
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    for i, doc in enumerate(results["documents"][0]):
        distance = results["distances"][0][i]
        # ChromaDB cosine distance: score = 1 - distance
        score = 1.0 - distance
        hits.append({
            "chunk_id": results["ids"][0][i],
            "text": doc,
            "score": round(score, 4),
            "metadata": results["metadatas"][0][i],
        })

    # Section 2: Filter injection-flagged chunks from synthesis context.
    # Only exclude flagged chunks if clean alternatives exist — never return
    # empty results when flagged chunks are the only ones available.
    clean_hits = [h for h in hits if not h.get("metadata", {}).get("injection_flagged")]
    return clean_hits if clean_hits else hits


def needs_graph_fallback(vector_hits: list[dict]) -> bool:
    """
    Returns True if the top vector hit is below the confidence threshold,
    meaning we should also run graph traversal.
    """
    if not vector_hits:
        return True
    top_score = vector_hits[0]["score"]
    return top_score < settings.RETRIEVAL_CONFIDENCE_THRESHOLD
