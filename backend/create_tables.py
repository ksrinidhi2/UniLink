"""
create_tables.py
================
Initializes and creates all database tables for UniLink in PostgreSQL.
Reads the eight SQLAlchemy models defined in backend/models.py and generates
the corresponding tables in the connected 'unilink_db' database.
"""

import sys

try:
    from backend.database import engine, Base
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
except ImportError:
    from database import engine, Base
    from models import (
        Student,
        Listing,
        LostFoundReport,
        LostFoundClaim,
        BorrowRequest,
        SavedItem,
        Message,
        Notification
    )


def create_all_tables():
    # Safely get database name and host without exposing password/credentials
    db_name = engine.url.database or "unilink_db"
    db_host = engine.url.host or "localhost"

    print("=" * 60)
    print("UniLink - PostgreSQL Database Table Creation")
    print("=" * 60)
    print(f"Target Database : {db_name}")
    print(f"Target Host     : {db_host}")
    print(f"Registered Models: {len(Base.metadata.tables)} tables")
    for table_name in Base.metadata.tables.keys():
        print(f"  - {table_name}")
    print("-" * 60)
    print("Creating tables in PostgreSQL...")

    try:
        # Create all tables registered with Base.metadata
        Base.metadata.create_all(bind=engine)
        print("✓ All tables created successfully!")
        print("=" * 60)
    except Exception as exc:
        print("\n✗ Table creation failed!")
        # Print error details safely without leaking the full connection URL or credentials
        error_name = type(exc).__name__
        error_detail = getattr(exc, "orig", str(exc))
        print(f"Error Type: {error_name}")
        print(f"Details   : {error_detail}")
        print("\nTroubleshooting tips:")
        print("1. Ensure PostgreSQL service is running on your machine.")
        print("2. Verify your database name 'unilink_db' exists.")
        print("3. Check your database password inside backend/.env.")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    create_all_tables()
