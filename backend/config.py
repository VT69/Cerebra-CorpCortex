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

    # Retrieval tuning
    VECTOR_TOP_K: int = 10
    GRAPH_HOP_LIMIT: int = 3
    RETRIEVAL_CONFIDENCE_THRESHOLD: float = 0.70
    RERANKER_VECTOR_WEIGHT: float = 0.6
    RERANKER_GRAPH_WEIGHT: float = 0.4

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
