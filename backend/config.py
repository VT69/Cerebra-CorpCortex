"""
Centralised settings — loaded from .env file.
Import settings from here everywhere in the codebase.
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # LLM
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_VISION_MODEL: str = "gpt-4o"

    # Neo4j
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USERNAME: str = "neo4j"
    NEO4J_PASSWORD: str = "industrialiq123"
    # Least-privilege credentials for query-time graph reads. When unset, the
    # retriever falls back to NEO4J_USERNAME/PASSWORD but still opens a
    # READ_ACCESS session. See README "Neo4j read-only user".
    NEO4J_READ_USERNAME: Optional[str] = None
    NEO4J_READ_PASSWORD: Optional[str] = None
    NEO4J_QUERY_TIMEOUT_S: float = 5.0

    # ChromaDB
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    CHROMA_COLLECTION_NAME: str = "industrialiq_docs"

    # Embedding
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Langfuse
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "http://localhost:3001"

    # Document Processing
    TESSERACT_CMD: Optional[str] = None
    DOC_UPLOAD_DIR: str = "./data/uploads"
    DOC_FINGERPRINT_CACHE: str = "./data/fingerprints.json"

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
    # Write endpoints (/ingest, /webhook/qms/incident, /eval/run) require this
    # key via "Authorization: Bearer <key>" or "X-API-Key: <key>". If unset,
    # writes are refused (fail closed).
    INGEST_API_KEY: Optional[str] = None
    RATE_LIMIT_WRITES_PER_MIN: int = 10
    # /query is unauthenticated; this bounds per-client load and review-queue flooding.
    RATE_LIMIT_QUERIES_PER_MIN: int = 30

    # Human-in-the-loop review of high-stakes answers
    REVIEWER_API_KEY: Optional[str] = None     # required for /review/* (fail closed)
    CHECKPOINT_DB_PATH: str = "./data/checkpoints.sqlite"
    # "all": withhold every high-stakes answer until a reviewer decides.
    # "low_confidence": withhold only high-stakes answers not labelled High.
    HITL_MODE: str = "all"

    # Retrieval tuning
    VECTOR_TOP_K: int = 10
    GRAPH_HOP_LIMIT: int = 3
    GRAPH_MAX_LIMIT: int = 20
    # Near-duplicate chunk threshold (MinHash estimated Jaccard of word 3-shingles).
    # Measured on the corpus: distinct chunks max 0.61; 3-word-edited copies median 0.88.
    NEAR_DUP_JACCARD: float = 0.7
    RETRIEVAL_CONFIDENCE_THRESHOLD: float = 0.70
    # Reciprocal Rank Fusion constant for merging vector + graph rankings.
    RRF_K: int = 60
    # Answer confidence bands on the top raw cosine similarity. These are
    # heuristics, NOT calibrated against labelled data (see EVAL_RESULTS.md).
    CONFIDENCE_HIGH_SIM: float = 0.72
    CONFIDENCE_MEDIUM_SIM: float = 0.52

    # Guardrails
    AUDIT_DIR: str = "./data"
    INJECTION_SCAN_MAX_CHARS: int = 2000
    GROUNDEDNESS_CAP_PARTIAL: float = 0.75
    GROUNDEDNESS_CAP_LOW: float = 0.40
    GROUNDEDNESS_UNSUPPORTED_RATIO: float = 0.5
    PII_MIN_NAME_LENGTH: int = 3

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [o.strip() for o in self.CORS_ORIGINS.split(",")]
        # If wildcard is set, return as-is (Render/Vercel deployment)
        if "*" in origins:
            return ["*"]
        return origins

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
