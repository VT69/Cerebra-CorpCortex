"""
Fix 12 — CSV ingests, spreadsheet chunks keep their header, .xls fails cleanly.

Audit findings (verified): openpyxl raised InvalidFileException for .csv and
.xls (an unhandled 500 from /ingest), and spreadsheets used generic
800-char windows, so every chunk after the first lost its column headers.
"""
import openpyxl

from backend.ingestion.parsers.document_parsers import parse_document
from backend.ingestion.pipeline import ingest_document
from tests.helpers import install_ingest_fakes

HEADER = ["tag", "date", "vibration_mm_s", "status"]
ROWS = [[f"P-{100 + i}", f"2024-03-{(i % 28) + 1:02d}", f"{2 + (i % 30) / 10:.1f}", "normal"] for i in range(200)]


def _csv(tmp_path):
    p = tmp_path / "vibration_log.csv"
    p.write_text("\n".join(",".join(r) for r in [HEADER] + ROWS))
    return p


def _xlsx(tmp_path):
    p = tmp_path / "vibration_log.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Log"
    for r in [HEADER] + ROWS:
        ws.append(r)
    wb.save(p)
    return p


def test_csv_is_parsed(tmp_path):
    parsed = parse_document(str(_csv(tmp_path)), "spreadsheet")
    assert parsed and parsed["chunks"]
    assert "P-150" in parsed["text"]


def test_every_csv_chunk_repeats_the_header(tmp_path):
    chunks = parse_document(str(_csv(tmp_path)), "spreadsheet")["chunks"]
    assert len(chunks) > 1
    assert all("tag | date | vibration_mm_s | status" in c for c in chunks)


def test_every_xlsx_chunk_repeats_the_header(tmp_path):
    chunks = parse_document(str(_xlsx(tmp_path)), "spreadsheet")["chunks"]
    assert len(chunks) > 1
    assert all("tag | date | vibration_mm_s | status" in c for c in chunks)


async def test_xls_is_rejected_with_a_clear_error(monkeypatch, tmp_path):
    p = tmp_path / "legacy.xls"
    p.write_bytes(b"\xd0\xcf\x11\xe0 not really an xls")
    install_ingest_fakes(monkeypatch, chunks=[], patch_parser=False)
    result = await ingest_document(str(p), "spreadsheet", {})
    assert result["status"] == "error"
    assert "xls" in result["reason"].lower()
