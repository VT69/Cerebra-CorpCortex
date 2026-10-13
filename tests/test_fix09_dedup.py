"""
Fix 9 — dedup survives a lost fingerprint cache, persists immediately, and
catches near-duplicate chunks (MinHash).

Audit findings: the fingerprint cache was committed as '{}' while the store
held 3-4 copies of five files (cache lost -> silent re-ingestion), and
SHA-256 on whole files cannot catch slightly edited copies.
"""
import json
import random

from backend.config import settings
from backend.ingestion.pipeline import ingest_document
from tests.helpers import FakeCollection, install_ingest_fakes

INCIDENT = (
    "At 14:30 hours, during routine operation, a loud screeching noise was heard from the drive "
    "pulley of Conveyor Belt C-202. The operator immediately hit the emergency stop. Upon inspection, "
    "it was found that the main bearing (Part # BRG-405) had seized due to complete lubrication failure. "
    "The auto-lubrication system for C-202 had a blocked line. The blockage prevented grease from "
    "reaching the bearing. The daily inspection checklist did not include a physical verification of "
    "grease flow at the bearing housing. Corrective actions: replaced the seized bearing and cleared "
    "the auto-lube line, updated the maintenance checklist, scheduled ultrasonic vibration analysis."
)
UNRELATED = (
    "Blast Furnace BF-1 has a working volume of 3200 cubic meters and operates at a design pressure "
    "of 2.5 bar. Daily: inspect tuyere cooling water flow. Weekly: check top gas analyzer calibration. "
    "Monthly: lubricate charging bell mechanism using high-temperature grease (Spec: VSW-HTG-99). "
    "High hearth temperature indicates refractory wear; reduce blast temperature immediately."
)


def _edit(text, n, rng):
    words = text.split()
    for _ in range(n):
        words[rng.randrange(len(words))] = rng.choice(["revised", "updated", "noted", "per", "unit"])
    return " ".join(words)


async def _ingest(monkeypatch, tmp_path, name, chunks, collection, cache):
    f = tmp_path / name
    f.write_text("\n".join(chunks))
    install_ingest_fakes(monkeypatch, chunks, collection=collection)
    return await ingest_document(str(f), "generic", cache)


async def test_reingest_is_skipped_even_if_fingerprint_cache_is_lost(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DOC_FINGERPRINT_CACHE", str(tmp_path / "fp.json"))
    col = FakeCollection()
    first = await _ingest(monkeypatch, tmp_path, "a.txt", [INCIDENT], col, {})
    (tmp_path / "fp.json").unlink(missing_ok=True)              # cache lost (as in the repo)
    again = await _ingest(monkeypatch, tmp_path, "a.txt", [INCIDENT], col, {})
    assert first["status"] == "success" and again["status"] == "skipped"
    assert len(col.rows) == 1


async def test_fingerprint_is_persisted_to_disk_immediately(monkeypatch, tmp_path):
    cache_path = tmp_path / "fp.json"
    monkeypatch.setattr(settings, "DOC_FINGERPRINT_CACHE", str(cache_path))
    await _ingest(monkeypatch, tmp_path, "a.txt", [INCIDENT], FakeCollection(), {})
    await _ingest(monkeypatch, tmp_path, "b.txt", [UNRELATED], FakeCollection(), {})
    assert len(json.loads(cache_path.read_text())) == 2         # both kept, written as they happen


async def test_twenty_slightly_edited_copies_do_not_flood_the_store(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DOC_FINGERPRINT_CACHE", str(tmp_path / "fp.json"))
    col, rng = FakeCollection(), random.Random(7)
    await _ingest(monkeypatch, tmp_path, "orig.txt", [INCIDENT], col, {})
    for i in range(20):
        await _ingest(monkeypatch, tmp_path, f"copy{i}.txt", [_edit(INCIDENT, 3, rng)], col, {})
    assert len(col.rows) <= 2, f"{len(col.rows)} chunks stored from 1 original + 20 near-copies"


async def test_unrelated_document_is_not_treated_as_duplicate(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DOC_FINGERPRINT_CACHE", str(tmp_path / "fp.json"))
    col = FakeCollection()
    await _ingest(monkeypatch, tmp_path, "a.txt", [INCIDENT], col, {})
    r = await _ingest(monkeypatch, tmp_path, "b.txt", [UNRELATED], col, {})
    assert r["status"] == "success" and len(col.rows) == 2
