"""
Validation for LLM-generated Cypher before it reaches Neo4j.

This is defence in depth: the primary control is that graph_search runs every
query in a READ_ACCESS session (and, in production, as a read-only Neo4j user).
The guard additionally rejects anything that is not a plain read query and
enforces an upper bound on LIMIT.
"""
import re

from backend.config import settings


class UnsafeCypherError(ValueError):
    """Raised when generated Cypher is not an allowed read-only query."""


# Any of these as a standalone word means the query can write, call procedures,
# reach the network, or administer the database. CALL is rejected outright:
# the retriever never needs procedures, and CALL is how APOC/dbms writes and
# network loads (apoc.load.*) are reached.
_FORBIDDEN = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD|FOREACH|CALL|"
    r"ALTER|GRANT|DENY|REVOKE|RENAME|START|STOP|TERMINATE|SHOW|USE|PERIODIC)\b",
    re.IGNORECASE,
)
_ALLOWED_START = re.compile(r"^\s*(OPTIONAL\s+MATCH|MATCH|WITH|UNWIND|RETURN)\b", re.IGNORECASE)
_LIMIT = re.compile(r"\bLIMIT\s+(\S+)", re.IGNORECASE)
_TRAILING_LIMIT = re.compile(r"\bLIMIT\s+\d+\s*$", re.IGNORECASE)


def _strip_literals_and_comments(cypher: str) -> str:
    """Blank out comments, string literals and backticked names so keywords
    inside them neither trigger nor hide from the keyword check."""
    out = re.sub(r"/\*.*?\*/", " ", cypher, flags=re.DOTALL)
    out = re.sub(r"//[^\n]*", " ", out)
    out = re.sub(r"'(?:\\.|[^'\\])*'", "''", out)
    out = re.sub(r'"(?:\\.|[^"\\])*"', '""', out)
    out = re.sub(r"`[^`]*`", "``", out)
    return out


def validate_cypher(cypher: str, max_limit: int | None = None) -> str:
    """Return a safe, LIMIT-bounded version of ``cypher`` or raise UnsafeCypherError."""
    max_limit = max_limit or settings.GRAPH_MAX_LIMIT
    if not cypher or not cypher.strip():
        raise UnsafeCypherError("empty query")

    query = cypher.strip().rstrip(";").strip()
    skeleton = _strip_literals_and_comments(query)

    if ";" in skeleton:
        raise UnsafeCypherError("multiple statements are not allowed")
    if not _ALLOWED_START.match(skeleton):
        raise UnsafeCypherError("query must start with MATCH, OPTIONAL MATCH, WITH, UNWIND or RETURN")
    bad = _FORBIDDEN.search(skeleton)
    if bad:
        raise UnsafeCypherError(f"forbidden keyword: {bad.group(1).upper()}")

    for m in _LIMIT.finditer(skeleton):
        if not m.group(1).isdigit():
            raise UnsafeCypherError("LIMIT must be an integer literal")

    # Clamp every LIMIT, then guarantee the final clause is bounded.
    query = _LIMIT.sub(lambda m: f"LIMIT {min(int(m.group(1)), max_limit)}", query)
    if not _TRAILING_LIMIT.search(_strip_literals_and_comments(query)):
        query = f"{query} LIMIT {max_limit}"
    return query
