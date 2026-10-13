"""
Shared test setup. Environment must be set BEFORE any backend import because
backend.config.settings is instantiated at import time.
No test makes a real OpenAI or Neo4j call — those are mocked per test.
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="cerebra-tests-")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-real")
os.environ.setdefault("AUDIT_DIR", _TMP)
os.environ.setdefault("CHROMA_PERSIST_DIR", os.path.join(_TMP, "chroma"))
os.environ.setdefault("DOC_UPLOAD_DIR", os.path.join(_TMP, "uploads"))
os.environ.setdefault("DOC_FINGERPRINT_CACHE", os.path.join(_TMP, "fingerprints.json"))
os.environ.setdefault("INGEST_API_KEY", "test-ingest-key")
os.environ.setdefault("REVIEWER_API_KEY", "test-reviewer-key")
os.environ.setdefault("CHECKPOINT_DB_PATH", os.path.join(_TMP, "checkpoints.sqlite"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
