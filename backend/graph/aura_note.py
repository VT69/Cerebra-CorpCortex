"""
Neo4j connection fallback config.
If Docker isn't running, use Neo4j AuraDB free tier (cloud).
Add to .env:
  NEO4J_URI=neo4j+s://<aura-id>.databases.neo4j.io
  NEO4J_USERNAME=neo4j
  NEO4J_PASSWORD=<aura-password>
"""
