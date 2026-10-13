"""
Neo4j graph schema initializer and writer.
Vaibhav owns this file.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver
from backend.shared.ontology import Provenance, CONFIDENCE_THRESHOLDS
from backend.config import settings 


# ─────────────────────────────────────────────────────────────────────────────
# Neo4j Constraints & Indexes (run once on startup)
# ─────────────────────────────────────────────────────────────────────────────

INIT_CYPHER = [
    # Uniqueness constraints
    "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Equipment) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Parameter) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (pe:Person) REQUIRE pe.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Regulation) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (ev:Event) REQUIRE ev.id IS UNIQUE",

    # Full-text search index (for keyword fallback)
    """
    CREATE FULLTEXT INDEX equipment_fulltext IF NOT EXISTS
    FOR (e:Equipment) ON EACH [e.name, e.tag, e.description]
    """,
    """
    CREATE FULLTEXT INDEX document_fulltext IF NOT EXISTS
    FOR (d:Document) ON EACH [d.title, d.content_summary]
    """,
]


class GraphWriter:
    """
    Writes verified facts to Neo4j with full provenance tracking.
    Only writes facts that pass the confidence threshold.
    """

    def __init__(self, driver: AsyncDriver):
        self.driver = driver

    async def initialize_schema(self):
        """Create constraints and indexes. Idempotent."""
        async with self.driver.session() as session:
            for stmt in INIT_CYPHER:
                await session.run(stmt)

    async def upsert_node(
        self,
        node_type: str,
        node_id: str,
        properties: dict,
        provenance: Provenance,
    ) -> str:
        """
        MERGE (upsert) a node. Properties are merged, not replaced.
        Returns the node_id on success, None if skipped or failed.
        """
        if provenance.confidence < CONFIDENCE_THRESHOLDS["write_to_graph"]:
            return None  # Don't write low-confidence facts

        props = {
            "id": node_id,
            "role_tag": provenance.role_tag,
            "last_updated": provenance.extracted_at,
            **properties,
        }

        cypher = f"""
        MERGE (n:{node_type} {{id: $id}})
        SET n += $props
        RETURN n.id
        """
        async with self.driver.session() as session:
            result = await session.run(cypher, id=node_id, props=props)
            record = await result.single()
            returned_id = record["n.id"] if record else None

        # Audit log in its own session to avoid nested-session pool exhaustion
        if returned_id:
            await self._write_audit_log("upsert_node", node_type, node_id, provenance)
        return returned_id

    async def upsert_edge(
        self,
        from_id: str,
        from_type: str,
        edge_type: str,
        to_id: str,
        to_type: str,
        provenance: Provenance,
        edge_properties: dict = None,
    ) -> bool:
        """
        MERGE an edge between two nodes with full provenance payload.
        Uses MERGE for both endpoint nodes so the edge is never silently dropped
        even if a node wasn't committed in a prior step.
        Returns True if the edge was written, False if skipped.
        """
        if provenance.confidence < CONFIDENCE_THRESHOLDS["write_to_graph"]:
            return False

        edge_props = {
            "source_doc_id": provenance.source_doc_id,
            "confidence": provenance.confidence,
            "extraction_pass_id": provenance.extraction_pass_id,
            "extracted_at": provenance.extracted_at,
            "extracted_by": provenance.extracted_by,
            "verified": provenance.verified,
            "role_tag": provenance.role_tag,
            "raw_text_span": provenance.raw_text_span or "",
            **(edge_properties or {}),
        }

        # KEY FIX: use MERGE (not MATCH) on both endpoint nodes so the
        # relationship is never silently dropped when a node is missing.
        # MERGE will create the node stub if it doesn't already exist.
        cypher = f"""
        MERGE (a:{from_type} {{id: $from_id}})
        MERGE (b:{to_type} {{id: $to_id}})
        MERGE (a)-[r:{edge_type}]->(b)
        SET r += $edge_props
        RETURN type(r) AS rel_type
        """
        async with self.driver.session() as session:
            result = await session.run(
                cypher,
                from_id=from_id,
                to_id=to_id,
                edge_props=edge_props,
            )
            record = await result.single()

        # Audit log in its own session to avoid nested-session pool exhaustion
        written = record is not None
        if written:
            await self._write_audit_log("upsert_edge", edge_type, f"{from_id}->{to_id}", provenance)
        return written

    async def _write_audit_log(
        self,
        operation: str,
        entity_type: str,
        entity_id: str,
        provenance: Provenance,
    ):
        """Every graph write gets an immutable audit record."""
        cypher = """
        CREATE (a:AuditLog {
            id: $id,
            operation: $operation,
            entity_type: $entity_type,
            entity_id: $entity_id,
            source_doc_id: $source_doc_id,
            extraction_pass_id: $extraction_pass_id,
            triggered_by: $triggered_by,
            timestamp: $timestamp
        })
        """
        async with self.driver.session() as session:
            await session.run(
                cypher,
                id=str(uuid.uuid4()),
                operation=operation,
                entity_type=entity_type,
                entity_id=entity_id,
                source_doc_id=provenance.source_doc_id,
                extraction_pass_id=provenance.extraction_pass_id,
                triggered_by=provenance.extracted_by,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )


async def get_driver() -> AsyncDriver:
    """Get a connected Neo4j async driver."""
    return AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
    )


async def get_read_driver() -> AsyncDriver:
    """Driver for query-time graph reads, using least-privilege credentials
    when NEO4J_READ_USERNAME/NEO4J_READ_PASSWORD are configured."""
    return AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(
            settings.NEO4J_READ_USERNAME or settings.NEO4J_USERNAME,
            settings.NEO4J_READ_PASSWORD or settings.NEO4J_PASSWORD,
        ),
    )
