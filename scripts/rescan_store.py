"""
Re-scan an existing ChromaDB store in place, without re-embedding.

Why: the committed demo store was built before the injection scanner existed
(no chunk carries scan metadata) and contains the same files ingested 3-4
times under different doc_ids. Retrieval now treats unscanned chunks as
untrusted, so the store must be re-scanned to be usable.

What it does (idempotent):
  1. keeps one ingestion per file (the doc_id with the lowest chunk id) and
     deletes the other copies, and any chunk whose exact text already exists
  2. runs the current injection scanner (normalised regex) on every kept chunk.
     Offline there is no LLM second pass, so ANY regex hit is marked
     injection_flagged=True (conservative: never returned at query time)
  3. stamps scan_version, chunk_sha256, file_sha256 and minhash metadata
  4. rebuilds the fingerprint cache from source files found on disk
  5. compacts the collection (re-creates it from its own embeddings) after
     deletions, because deleted HNSW entries otherwise still consume top-k slots

Usage:
  python -m scripts.rescan_store                # dry run, prints the plan
  python -m scripts.rescan_store --apply
"""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import chromadb

from backend.config import settings
from backend.guardrails.injection_scanner import PATTERN_VERSION, scan_text_for_injection
from backend.ingestion.parsers.document_parsers import (
    fingerprint_file,
    load_fingerprint_cache,
    save_fingerprint_cache,
)

from backend.ingestion import dedup

SOURCE_DIRS = ["./sample_docs", settings.DOC_UPLOAD_DIR]


def _source_files() -> dict[str, Path]:
    found = {}
    for d in SOURCE_DIRS:
        p = Path(d)
        if p.is_dir():
            for f in p.iterdir():
                if f.is_file():
                    found.setdefault(f.name, f)
    return found


def _compact(client, col):
    """Re-create the collection from its own rows (no re-embedding)."""
    rows = col.get(include=["embeddings", "documents", "metadatas"])
    name, meta = col.name, col.metadata
    client.delete_collection(name)
    fresh = client.create_collection(name, metadata=meta)
    for start in range(0, len(rows["ids"]), 200):
        end = start + 200
        fresh.add(ids=rows["ids"][start:end], embeddings=rows["embeddings"][start:end],
                  documents=rows["documents"][start:end], metadatas=rows["metadatas"][start:end])
    return fresh


def rescan(persist_dir: str, apply: bool) -> dict:
    client = chromadb.PersistentClient(path=persist_dir)
    col = client.get_collection(settings.CHROMA_COLLECTION_NAME)
    data = col.get(include=["documents", "metadatas"])

    # Group chunk ids by file, then by doc_id (one doc_id == one ingestion).
    by_file: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for idx, meta in enumerate(data["metadatas"]):
        by_file[meta.get("file_name", "?")][meta.get("doc_id", "?")].append(idx)

    keep: list[int] = []
    delete_ids: list[str] = []
    seen_text: set[str] = set()
    for file_name, ingestions in sorted(by_file.items()):
        canonical = min(ingestions, key=lambda d: min(data["ids"][i] for i in ingestions[d]))
        for doc_id, idxs in ingestions.items():
            for i in idxs:
                text_key = hashlib.sha256(data["documents"][i].encode()).hexdigest()
                if doc_id != canonical or text_key in seen_text:
                    delete_ids.append(data["ids"][i])
                else:
                    seen_text.add(text_key)
                    keep.append(i)

    sources = _source_files()
    file_sha = {name: fingerprint_file(str(p)) for name, p in sources.items()}

    update_ids, update_metas, flagged = [], [], 0
    for i in keep:
        text, meta = data["documents"][i], dict(data["metadatas"][i])
        result = scan_text_for_injection(text)
        meta["injection_flagged"] = bool(result["flagged"])
        meta["scan_version"] = PATTERN_VERSION
        meta["chunk_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        if meta.get("file_name") in file_sha:
            meta["file_sha256"] = file_sha[meta["file_name"]]
        meta["minhash"] = dedup.encode(dedup.minhash(text))
        flagged += meta["injection_flagged"]
        update_ids.append(data["ids"][i])
        update_metas.append(meta)

    summary = {
        "chunks_before": len(data["ids"]),
        "chunks_deleted_as_duplicates": len(delete_ids),
        "chunks_after": len(keep),
        "chunks_flagged": flagged,
        "files": len(by_file),
        "scan_version": PATTERN_VERSION,
    }

    if apply:
        if delete_ids:
            col.delete(ids=delete_ids)
        for start in range(0, len(update_ids), 200):
            col.update(ids=update_ids[start:start + 200], metadatas=update_metas[start:start + 200])
        if delete_ids:
            col = _compact(client, col)
            summary["compacted"] = True

        # Rebuild the fingerprint cache so re-ingesting these files is skipped.
        cache = load_fingerprint_cache(settings.DOC_FINGERPRINT_CACHE)
        for meta in update_metas:
            sha = meta.get("file_sha256")
            if sha and sha not in cache:
                cache[sha] = {
                    "doc_id": meta["doc_id"],
                    "file_path": str(sources[meta["file_name"]]),
                    "ingested_at": "rescan",
                }
        save_fingerprint_cache(cache, settings.DOC_FINGERPRINT_CACHE)
        summary["fingerprints"] = len(cache)

    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--persist-dir", default=settings.CHROMA_PERSIST_DIR)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    print(json.dumps(rescan(args.persist_dir, args.apply), indent=2))


if __name__ == "__main__":
    main()
