"""
Fix 10 (moved into P0) — the committed vector store is re-scanned and
de-duplicated so every chunk carries scan metadata and no file is
ingested more than once.

Audit finding: none of the 626 committed chunks had injection_flagged
metadata (built before the scanner existed), and five files were stored
3-4 times under different doc_ids.
"""
import sqlite3
from collections import defaultdict
from pathlib import Path

import chromadb

from tests import probes

REPO = Path(__file__).resolve().parents[1]
STORE = REPO / "data" / "chroma" / "chroma.sqlite3"


def _committed_metadata():
    con = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
    rows = defaultdict(dict)
    for emb_id, key, s, i, b in con.execute(
            "select id, key, string_value, int_value, bool_value from embedding_metadata"):
        rows[emb_id][key] = s if s is not None else (b if b is not None else i)
    return list(rows.values())


def test_every_committed_chunk_has_scan_metadata():
    metas = _committed_metadata()
    assert metas, "store is empty"
    missing = [m.get("file_name") for m in metas if "injection_flagged" not in m]
    assert missing == [], f"{len(missing)} chunks were never scanned"


def test_no_file_is_ingested_more_than_once():
    doc_ids = defaultdict(set)
    for m in _committed_metadata():
        doc_ids[m["file_name"]].add(m["doc_id"])
    dupes = {f: len(d) for f, d in doc_ids.items() if len(d) > 1}
    assert dupes == {}


def test_rescan_script_dedups_and_flags(tmp_path, monkeypatch):
    from backend.config import settings
    from scripts.rescan_store import rescan

    monkeypatch.setattr(settings, "DOC_FINGERPRINT_CACHE", str(tmp_path / "fp.json"))
    client = chromadb.PersistentClient(path=str(tmp_path / "db"))
    col = client.create_collection(settings.CHROMA_COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    texts = [probes.CLEAN_TEXT, f"Shift note {probes.BASE64}"]
    ids, docs, metas = [], [], []
    for copy in ("a", "b", "c"):  # same file ingested three times
        for n, t in enumerate(texts):
            ids.append(f"{copy}_chunk_{n}"); docs.append(t)
            metas.append({"doc_id": copy, "file_name": "dup.txt", "chunk_index": n})
    col.add(ids=ids, documents=docs, metadatas=metas, embeddings=[[0.1 * (i + 1)] * 4 for i in range(len(ids))])

    summary = rescan(str(tmp_path / "db"), apply=True)
    assert summary["chunks_after"] == 2 and summary["chunks_deleted_as_duplicates"] == 4

    col = client.get_collection(settings.CHROMA_COLLECTION_NAME)  # compaction recreates it
    got = col.get(include=["metadatas", "documents"])
    flags = {d: m["injection_flagged"] for d, m in zip(got["documents"], got["metadatas"])}
    assert flags[probes.CLEAN_TEXT] is False
    assert flags[f"Shift note {probes.BASE64}"] is True  # base64-hidden attack flagged offline
    assert all(m["scan_version"] for m in got["metadatas"])
