"""
Fix 1 — LLM-generated Cypher must never be able to write to Neo4j.

Audit finding: graph_search.py ran whatever Cypher the LLM produced in a
default (write-capable) session as the admin user, with no LIMIT or timeout.
"""
import neo4j
import pytest

import backend.retrieval.graph_search as gs


class _Cursor:
    async def data(self):
        return []


class _Session:
    def __init__(self, log, kwargs):
        self.log = log
        self.log["session_kwargs"] = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def run(self, query, *args, **kwargs):
        self.log.setdefault("runs", []).append(query)
        return _Cursor()


class _Driver:
    def __init__(self, log):
        self.log = log

    def session(self, **kwargs):
        return _Session(self.log, kwargs)

    async def close(self):
        pass


@pytest.fixture
def fake_neo4j(monkeypatch):
    log = {}

    async def _get_driver(*a, **k):
        return _Driver(log)

    # Patch every driver factory graph_search might use.
    monkeypatch.setattr(gs, "get_driver", _get_driver, raising=False)
    monkeypatch.setattr(gs, "get_read_driver", _get_driver, raising=False)
    return log


def _llm_returns(monkeypatch, cypher):
    async def _gen(*a, **k):
        return cypher
    monkeypatch.setattr(gs, "_generate_cypher", _gen)


def _query_text(q):
    return q.text if isinstance(q, neo4j.Query) else q


@pytest.mark.parametrize("cypher", [
    "MATCH (n) DETACH DELETE n",
    "MATCH (e:Equipment {id:'pump-P-101'}) SET e.design_pressure = '99 bar' RETURN e",
    "CREATE (x:Equipment {id:'evil'}) RETURN x",
    "MERGE (x:Person {id:'attacker'}) RETURN x",
    "MATCH (a:AuditLog) REMOVE a.operation RETURN a",
    "CALL apoc.load.json('https://evil.example/x') YIELD value RETURN value",
    "CALL dbms.security.createUser('x','y',false)",
    "LOAD CSV FROM 'https://evil.example/x.csv' AS row RETURN row",
    "MATCH (n) RETURN n; MATCH (m) DETACH DELETE m",
    "DROP CONSTRAINT equipment_id",
])
async def test_destructive_cypher_is_never_executed(monkeypatch, fake_neo4j, cypher):
    _llm_returns(monkeypatch, cypher)
    results = await gs.graph_search("delete everything", "multi-hop")
    assert results == []
    assert not fake_neo4j.get("runs"), f"unsafe Cypher reached Neo4j: {cypher}"


async def test_session_is_read_only(monkeypatch, fake_neo4j):
    _llm_returns(monkeypatch, "MATCH (e:Equipment) RETURN e LIMIT 5")
    await gs.graph_search("list equipment", "aggregation")
    assert fake_neo4j["session_kwargs"].get("default_access_mode") == neo4j.READ_ACCESS


async def test_query_has_timeout(monkeypatch, fake_neo4j):
    _llm_returns(monkeypatch, "MATCH (e:Equipment) RETURN e LIMIT 5")
    await gs.graph_search("list equipment", "aggregation")
    q = fake_neo4j["runs"][0]
    assert isinstance(q, neo4j.Query) and q.timeout and q.timeout > 0


@pytest.mark.parametrize("cypher,expected_tail", [
    ("MATCH (e:Equipment) RETURN e", "LIMIT 20"),           # missing LIMIT is appended
    ("MATCH (e:Equipment) RETURN e LIMIT 100000", "LIMIT 20"),  # oversized LIMIT is clamped
    ("MATCH (e:Equipment) RETURN e LIMIT 5", "LIMIT 5"),      # small LIMIT kept
])
async def test_limit_is_enforced(monkeypatch, fake_neo4j, cypher, expected_tail):
    _llm_returns(monkeypatch, cypher)
    await gs.graph_search("q", "aggregation")
    assert _query_text(fake_neo4j["runs"][0]).rstrip().endswith(expected_tail)


async def test_keywords_inside_string_literals_are_allowed(monkeypatch, fake_neo4j):
    # A read query that merely mentions a write keyword inside a string must still run.
    _llm_returns(monkeypatch, "MATCH (d:Document) WHERE d.title CONTAINS 'DELETE log' RETURN d LIMIT 3")
    await gs.graph_search("q", "single-fact")
    assert len(fake_neo4j["runs"]) == 1
