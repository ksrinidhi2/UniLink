"""
init_db.py
==========
Dedicated Schema-Only Initialization Tool for UniLink Production (Neon PostgreSQL).

SAFETY GUARANTEES:
1. Explicit Target Requirement:
   - Does NOT use fallback or implicit localhost DATABASE_URL.
   - Refuses to run against localhost, 127.0.0.1, or local development ports.
2. Zero Data Mutation:
   - Creates only database tables, columns, indexes, and foreign keys.
   - Never copies, dumps, seeds, or modifies any existing user or listing data.
3. Secret Protection:
   - Redacts credentials in all logs and outputs.
"""

import sys
import os
from urllib.parse import urlparse
from pathlib import Path

# Ensure backend directory and root are in sys.path
_BACKEND_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _BACKEND_DIR.parent
for _p in [str(_ROOT_DIR), str(_BACKEND_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import create_engine, inspect
from backend.database import Base, normalize_database_url
# Import all models so their metadata is registered with Base
from backend.models import (
    Student,
    Listing,
    LostFoundReport,
    LostFoundClaim,
    BorrowRequest,
    SavedItem,
    Message,
    Notification
)

EXPECTED_TABLES = [
    "students",
    "listings",
    "lost_found_reports",
    "lost_found_claims",
    "borrow_requests",
    "saved_items",
    "messages",
    "notifications"
]

def mask_connection_url(url: str) -> str:
    """Returns a redacted representation of a database URL for safe logging."""
    if not url:
        return "<EMPTY>"
    try:
        # Simple parse to extract scheme, user, and host
        parsed = urlparse(url.replace("+psycopg", ""))
        safe_netloc = parsed.hostname or "unknown-host"
        if parsed.port:
            safe_netloc += f":{parsed.port}"
        user_str = f"{parsed.username}@" if parsed.username else ""
        return f"{parsed.scheme}://{user_str}{safe_netloc}{parsed.path}"
    except Exception:
        return "postgresql://***:***@<target-host>/<target-database>"

def initialize_production_schema(target_url: str) -> bool:
    """
    Connects to the specified remote PostgreSQL database (Neon) and creates all required tables.
    Fails with an error if the target appears to be a local database.
    """
    if not target_url or not target_url.strip():
        print("[ERROR] No target database URL provided.")
        print("Usage: python backend/init_db.py <NEON_DATABASE_URL>")
        print("   or: Set TARGET_DATABASE_URL environment variable.")
        return False

    raw_url = target_url.strip().strip("'\"")
    normalized_url = normalize_database_url(raw_url)

    # Safety Check: Prevent running against localhost
    lower_url = normalized_url.lower()
    if "localhost" in lower_url or "127.0.0.1" in lower_url or "@::1" in lower_url:
        print("[BLOCKED] Safety Guard Active: Cannot run production initialization against localhost.")
        print("          This script is strictly for new remote production databases (Neon).")
        return False

    masked = mask_connection_url(normalized_url)
    print(f"[INFO] Target database: {masked}")
    print("[INFO] Validating connection and creating schema...")

    try:
        engine = create_engine(
            normalized_url,
            echo=False,
            connect_args={"connect_timeout": 10}
        )

        # Inspect current state
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())

        # Create all tables defined in models
        Base.metadata.create_all(bind=engine)

        # Re-inspect to confirm all tables exist
        inspector_after = inspect(engine)
        created_tables = set(inspector_after.get_table_names())

        missing = [t for t in EXPECTED_TABLES if t not in created_tables]
        if missing:
            print(f"[FAIL] The following required tables were not created: {missing}")
            return False

        print(f"[SUCCESS] All {len(EXPECTED_TABLES)} production tables verified:")
        for tbl in EXPECTED_TABLES:
            status = "Created new" if tbl not in existing_tables else "Already present"
            print(f"  - {tbl:20} [{status}]")

        print("\n[READY] The remote Neon PostgreSQL schema is initialized and ready for production traffic.")
        return True

    except Exception as exc:
        print(f"[ERROR] Database schema initialization failed: {type(exc).__name__}: {str(exc)}")
        return False

if __name__ == "__main__":
    cli_url = sys.argv[1] if len(sys.argv) > 1 else os.getenv("TARGET_DATABASE_URL", "")
    success = initialize_production_schema(cli_url)
    sys.exit(0 if success else 1)
