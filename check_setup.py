"""
Startup health check - run this after pip install to verify all dependencies
are available and the configuration is valid.

Usage:
    .venv\Scripts\python check_setup.py
"""
import sys

print("IndustrialIQ Setup Check")
print("=" * 40)

errors = []
warnings = []

# --- Core deps ---
checks = [
    ("fastapi", "FastAPI"),
    ("uvicorn", "Uvicorn"),
    ("pydantic", "Pydantic"),
    ("openai", "OpenAI SDK"),
    ("langchain", "LangChain"),
    ("langgraph", "LangGraph"),
    ("chromadb", "ChromaDB"),
    ("neo4j", "Neo4j driver"),
    ("pypdf", "pypdf"),
    ("pdfplumber", "pdfplumber"),
    ("docx", "python-docx"),
    ("openpyxl", "openpyxl"),
    ("PIL", "Pillow"),
    ("pytesseract", "pytesseract"),
    ("ragas", "Ragas eval"),
    ("langfuse", "Langfuse"),
    ("watchdog", "watchdog"),
    ("rich", "rich"),
    ("typer", "typer"),
]

for module, name in checks:
    try:
        __import__(module)
        print(f"  [OK] {name}")
    except ImportError as e:
        print(f"  [MISSING] {name}: {e}")
        errors.append(name)

# --- Optional deps ---
print("\nOptional:")
try:
    import cv2
    print(f"  [OK] OpenCV {cv2.__version__} (P&ID preprocessing enabled)")
except ImportError:
    print(f"  [WARN] OpenCV not installed - P&ID parsing will use OCR-only mode")
    warnings.append("opencv-python")

try:
    import pytesseract
    version = pytesseract.get_tesseract_version()
    print(f"  [OK] Tesseract binary found: {version}")
except Exception:
    print(f"  [WARN] Tesseract binary not found - OCR will fail on scanned docs")
    print(f"         Install from: https://github.com/UB-Mannheim/tesseract/wiki")
    warnings.append("tesseract-binary")

# --- Config check ---
print("\nConfiguration:")
try:
    from dotenv import load_dotenv
    import os
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key and api_key != "sk-...your-key-here...":
        print(f"  [OK] OPENAI_API_KEY is set")
    else:
        print(f"  [MISSING] OPENAI_API_KEY not set in .env")
        errors.append("OPENAI_API_KEY")

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    print(f"  [INFO] NEO4J_URI = {neo4j_uri}")
except Exception as e:
    print(f"  [ERROR] Could not read .env: {e}")

# --- Neo4j connectivity ---
print("\nNeo4j Connection:")
try:
    from dotenv import load_dotenv
    import os
    load_dotenv()
    from neo4j import GraphDatabase
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USERNAME", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "industrialiq123")
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    driver.verify_connectivity()
    driver.close()
    print(f"  [OK] Connected to Neo4j at {uri}")
except Exception as e:
    print(f"  [WARN] Cannot connect to Neo4j: {e}")
    print(f"         Make sure Docker Desktop is running and 'docker compose up -d' is done")
    warnings.append("neo4j-connection")

# --- Summary ---
print("\n" + "=" * 40)
if errors:
    print(f"ERRORS ({len(errors)}): {', '.join(errors)}")
    print("Fix these before running the pipeline.")
    sys.exit(1)
elif warnings:
    print(f"WARNINGS ({len(warnings)}): {', '.join(warnings)}")
    print("System can run but some features will be limited.")
else:
    print("All checks passed! Ready to run.")
    print("\nNext steps:")
    print("  1. python -m backend.ingestion.pipeline --dir ./sample_docs")
    print("  2. uvicorn backend.api.main:app --reload --port 8000")
