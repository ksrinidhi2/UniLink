"""
seed_production_demo.py
=======================
Dedicated, idempotent production demo-data seeding tool for UniLink on Neon PostgreSQL.

SAFETY GUARANTEES:
1. Explicit Target Requirement:
   - Does NOT connect to localhost, 127.0.0.1, ::1, or local development ports.
   - Requires TARGET_DATABASE_URL environment variable or CLI argument.
2. Zero Overwrite / Non-Destructive:
   - Preserves existing accounts, passwords, profile fields, and production data.
   - If an account already exists, reuses it without overwriting credentials.
   - Never deletes, drops, or truncates any table or record.
3. 100% Idempotent:
   - Checks for existing records before inserting (students, listings, lost & found,
     borrow requests, messages, notifications, saved items).
   - Safe to rerun multiple times without generating duplicates.
4. Transactional:
   - All operations execute in a database transaction; any failure triggers rollback.
5. Secret Protection:
   - Redacts database connection URLs and credentials in all logs and outputs.
   - Never prints passwords, hashes, or tokens to the console.
"""

import sys
import os
import getpass
import argparse
from pathlib import Path
from decimal import Decimal
from datetime import datetime, date, timedelta, timezone
from urllib.parse import urlparse

# Ensure repository root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import normalize_database_url
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
from backend.security import get_password_hash

# ==============================================================================
# DEMO ACCOUNT DEFINITIONS
# ==============================================================================
VARSHITHA_EMAIL = "varshitha.25bca1234@vitapstudent.ac.in"
ANANYA_EMAIL = "ananya.25bce1234@vitapstudent.ac.in"
TEST_STUDENT_EMAIL = "test.25bca2008@vitapstudent.ac.in"

DEMO_ACCOUNTS = [
    {
        "email": VARSHITHA_EMAIL,
        "full_name": "Varshitha",
        "reg_no": "25BCA1234",
        "year_of_study": "2nd Year",
        "program": "B.Tech CSE",
        "avatar_index": 0,
        "is_verified": True
    },
    {
        "email": ANANYA_EMAIL,
        "full_name": "Ananya",
        "reg_no": "25BCE1234",
        "year_of_study": "2nd Year",
        "program": "B.Tech CSE",
        "avatar_index": 5,
        "is_verified": True
    },
    {
        "email": TEST_STUDENT_EMAIL,
        "full_name": "Test Student",
        "reg_no": "25BCA2008",
        "year_of_study": "1st Year",
        "program": "B.Tech",
        "avatar_index": 1,
        "is_verified": True
    }
]

# Optional demo password from environment (never hardcoded)
DEMO_PASSWORD_ENV = os.getenv("DEMO_PASSWORD", "").strip()


def mask_connection_url(url: str) -> str:
    """Returns a redacted representation of a database URL for safe logging."""
    if not url:
        return "<EMPTY>"
    try:
        parsed = urlparse(url.replace("+psycopg", ""))
        safe_netloc = parsed.hostname or "unknown-host"
        if parsed.port:
            safe_netloc += f":{parsed.port}"
        user_str = f"{parsed.username}@" if parsed.username else ""
        return f"{parsed.scheme}://{user_str}{safe_netloc}{parsed.path}"
    except Exception:
        return "postgresql://***:***@<target-host>/<target-database>"


def validate_sample_data_spec() -> dict:
    """
    Validates sample data specifications statically without database connection.
    Used for safe dry-run checks and unit testing.
    """
    assert len(DEMO_ACCOUNTS) == 3, "Must define 3 demo accounts"
    for acc in DEMO_ACCOUNTS:
        email = acc["email"]
        assert "@" in email, f"Invalid email {email}"
        assert 0 <= acc["avatar_index"] <= 19, f"Invalid avatar {acc['avatar_index']}"
        assert acc["full_name"], "Full name required"
        
        # Validate demo password rule (email local part: min 8 chars, max 72 bytes)
        local_part = email.split("@")[0].strip()
        assert len(local_part) >= 8, f"Demo email local part too short for {email}"
        assert len(local_part.encode("utf-8")) <= 72, f"Demo email local part exceeds 72 bytes for {email}"

    if DEMO_PASSWORD_ENV:
        assert len(DEMO_PASSWORD_ENV) >= 8, "Demo password override must be at least 8 characters"
        assert len(DEMO_PASSWORD_ENV.encode("utf-8")) <= 72, "Demo password override exceeds 72 bytes"

    return {
        "status": "valid",
        "demo_accounts_count": len(DEMO_ACCOUNTS),
        "target_emails": [acc["email"] for acc in DEMO_ACCOUNTS]
    }


def resolve_demo_password_for_account(email: str, override_password: str = "") -> str:
    """
    Resolves the password for a newly created demo account:
    - Precedence 1: Explicit in-memory override parameter
    - Precedence 2: DEMO_PASSWORD environment variable (if explicitly set)
    - Precedence 3: Demo rule default: the email's local part (everything before '@')
      e.g. 'ananya.25bce1234@vitapstudent.ac.in' -> 'ananya.25bce1234'
    """
    pwd = (override_password or os.getenv("DEMO_PASSWORD", "")).strip()
    if not pwd:
        pwd = email.split("@")[0].strip()
    return pwd


def seed_demo_data(target_url: str, demo_password: str = "") -> bool:
    """
    Idempotently seeds demo data into the specified production Neon database.
    """
    if not target_url or not target_url.strip():
        print("[ERROR] No target database URL provided.")
        print("Usage: python seed_production_demo.py <NEON_DATABASE_URL>")
        print("   or: set TARGET_DATABASE_URL=<NEON_DATABASE_URL>")
        return False

    raw_url = target_url.strip().strip("'\"")
    normalized_url = normalize_database_url(raw_url)

    # Safety Guard: Prevent connecting to local database
    lower_url = normalized_url.lower()
    if "localhost" in lower_url or "127.0.0.1" in lower_url or "@::1" in lower_url:
        print("[BLOCKED] Safety Guard Active: Cannot run production seeder against localhost.")
        print("          This script is strictly intended for remote production databases (Neon).")
        return False

    masked = mask_connection_url(normalized_url)
    print("=" * 70)
    print(" UniLink - Production Demo Data Seeder (Idempotent)")
    print("=" * 70)
    print(f"Target Database : {masked}")
    print("Zero Overwrite   : Enabled (preserves existing accounts, passwords & records)")
    print("Transaction Mode : Enabled (all changes roll back on unexpected error)")
    print("-" * 70)

    try:
        engine = create_engine(
            normalized_url,
            echo=False,
            connect_args={"connect_timeout": 10}
        )
        SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    except Exception as exc:
        print(f"[ERROR] Failed to initialize engine: {type(exc).__name__}: {exc}")
        return False

    db = SessionFactory()
    try:
        now = datetime.now(timezone.utc)

        # ----------------------------------------------------------------------
        # 1. RESOLVE OR CREATE DEMO STUDENTS
        # ----------------------------------------------------------------------
        print("\n[1/7] Resolving / creating demo student accounts...")
        students_by_email = {}
        for acc_spec in DEMO_ACCOUNTS:
            email = acc_spec["email"].strip().lower()
            existing = db.query(Student).filter(Student.email == email).first()
            if existing:
                print(f" [=] Preserved existing account: {existing.full_name} ({email}) [ID {existing.id}]")
                students_by_email[email] = existing
            else:
                account_pwd = resolve_demo_password_for_account(email, override_password=demo_password)
                if not account_pwd or len(account_pwd) < 8:
                    print(f" [!] Derived password for {email} is too short (minimum 8 characters).")
                    db.rollback()
                    return False
                if len(account_pwd.encode("utf-8")) > 72:
                    print(f" [!] Password for {email} exceeds bcrypt 72-byte limit.")
                    db.rollback()
                    return False
                hashed_pwd = get_password_hash(account_pwd)
                new_student = Student(
                    full_name=acc_spec["full_name"],
                    email=email,
                    reg_no=acc_spec["reg_no"],
                    hashed_password=hashed_pwd,
                    avatar_index=acc_spec["avatar_index"],
                    year_of_study=acc_spec["year_of_study"],
                    program=acc_spec["program"],
                    is_verified=acc_spec["is_verified"],
                    created_at=now - timedelta(days=7)
                )
                db.add(new_student)
                db.flush()
                print(f" [+] Created demo account: {new_student.full_name} ({email}) [ID {new_student.id}]")
                students_by_email[email] = new_student

        varshitha = students_by_email[VARSHITHA_EMAIL]
        ananya = students_by_email[ANANYA_EMAIL]
        test_student = students_by_email[TEST_STUDENT_EMAIL]

        # ----------------------------------------------------------------------
        # 2. SEED FIVE LISTINGS (3 Marketplace, 2 Borrow) OWNED BY VARSHITHA
        # ----------------------------------------------------------------------
        print("\n[2/7] Checking Varshitha's listings (3 Marketplace, 2 Borrow)...")
        sample_marketplace = [
            {
                "title": "Casio FX-991ES Plus Scientific Calculator",
                "description": "Original Casio non-programmable scientific calculator. Natural textbook display, pristine condition, battery working perfectly. Allowed for university exams.",
                "category": "Electronics",
                "price": Decimal("750.00"),
                "location": "AB1 2nd Floor / Central Library",
                "image_url": "assets/items/calc -new.webp",
                "condition": "Like New",
                "status": "active"
            },
            {
                "title": "Wireless Bluetooth Over-Ear Headphones",
                "description": "Deep bass, 30h battery life, comfortable cushioned earcups. Great for quiet study sessions in the campus library. Comes with 3.5mm aux cable and pouch.",
                "category": "Electronics",
                "price": Decimal("1200.00"),
                "location": "Rock Plaza / Girls Hostel Block",
                "image_url": "assets/items/headphones.jpg",
                "condition": "Good",
                "status": "active"
            },
            {
                "title": "Classmate Hardcover Engineering Notebook (Unused)",
                "description": "Premium 400-page spiral-bound grid ruled notebook for engineering drawings and laboratory coursework. Completely unused, fresh pages.",
                "category": "Books",
                "price": Decimal("180.00"),
                "location": "Student Activity Center (SAC)",
                "image_url": "assets/items/dsa_book.jpg",
                "condition": "Like New",
                "status": "active"
            }
        ]

        sample_borrow = [
            {
                "title": "Data Structures & Algorithms in Java (Core Textbook)",
                "description": "Recommended textbook for 2nd Year CSE exams. Clear explanations of trees, graphs, and dynamic programming. Clean pages without pen marks.",
                "category": "Books",
                "price": Decimal("0.00"),
                "location": "Central Library / AB1",
                "image_url": "assets/items/dsa_book - new.jpg",
                "condition": "Good",
                "available_till": date.today() + timedelta(days=21),
                "status": "active"
            },
            {
                "title": "Ergonomic Aluminum Foldable Laptop Stand",
                "description": "Sturdy 6-level adjustable laptop riser. Keeps laptop cool during coding sprints and hackathons. Lightweight and easily portable.",
                "category": "Electronics",
                "price": Decimal("0.00"),
                "location": "LH3 / Central Library",
                "image_url": "assets/items/laptop_stand - neww.jpg",
                "condition": "Like New",
                "available_till": date.today() + timedelta(days=14),
                "status": "active"
            }
        ]

        created_listings = {}

        for item in sample_marketplace:
            existing = db.query(Listing).filter(
                Listing.student_id == varshitha.id,
                Listing.listing_type == "marketplace",
                Listing.title == item["title"]
            ).first()
            if not existing:
                l = Listing(
                    student_id=varshitha.id,
                    listing_type="marketplace",
                    title=item["title"],
                    description=item["description"],
                    category=item["category"],
                    price=item["price"],
                    location=item["location"],
                    image_url=item["image_url"],
                    condition=item["condition"],
                    status=item["status"],
                    created_at=now - timedelta(days=2, hours=3)
                )
                db.add(l)
                db.flush()
                created_listings[item["title"]] = l
                print(f" [+] Created Marketplace listing: '{l.title}' [ID {l.id}]")
            else:
                created_listings[item["title"]] = existing
                print(f" [=] Preserved Marketplace listing: '{existing.title}' [ID {existing.id}]")

        for item in sample_borrow:
            existing = db.query(Listing).filter(
                Listing.student_id == varshitha.id,
                Listing.listing_type == "borrow",
                Listing.title == item["title"]
            ).first()
            if not existing:
                l = Listing(
                    student_id=varshitha.id,
                    listing_type="borrow",
                    title=item["title"],
                    description=item["description"],
                    category=item["category"],
                    price=item["price"],
                    location=item["location"],
                    image_url=item["image_url"],
                    condition=item["condition"],
                    available_till=item["available_till"],
                    status=item["status"],
                    created_at=now - timedelta(days=3)
                )
                db.add(l)
                db.flush()
                created_listings[item["title"]] = l
                print(f" [+] Created Borrow listing: '{l.title}' [ID {l.id}]")
            else:
                created_listings[item["title"]] = existing
                print(f" [=] Preserved Borrow listing: '{existing.title}' [ID {existing.id}]")

        calc_listing = created_listings["Casio FX-991ES Plus Scientific Calculator"]
        dsa_book_listing = created_listings["Data Structures & Algorithms in Java (Core Textbook)"]
        laptop_stand_borrow = created_listings["Ergonomic Aluminum Foldable Laptop Stand"]

        # ----------------------------------------------------------------------
        # 3. SEED TWO LOST & FOUND REPORTS
        # ----------------------------------------------------------------------
        print("\n[3/7] Checking Lost & Found reports...")
        sample_reports = [
            {
                "student_id": ananya.id,
                "report_type": "found",
                "title": "Blue Milton Stainless Steel Water Bottle",
                "description": "Found an insulated blue stainless steel water bottle left behind in CB Cafeteria. Handed over to CB cafeteria security desk.",
                "location": "CB Cafeteria",
                "image_url": "assets/items/bottle.jpg",
                "status": "open",
                "created_at": now - timedelta(days=1, hours=4)
            },
            {
                "student_id": test_student.id,
                "report_type": "lost",
                "title": "Casio Scientific Calculator Hard Slipcase",
                "description": "Misplaced black protective cover for Casio FX-991ES during morning lecture in AB1 2nd Floor.",
                "location": "AB1 2nd Floor",
                "image_url": "assets/items/calc -new.webp",
                "status": "open",
                "created_at": now - timedelta(days=2, hours=1)
            }
        ]

        created_reports = {}
        for r_spec in sample_reports:
            existing_rep = db.query(LostFoundReport).filter(
                LostFoundReport.student_id == r_spec["student_id"],
                LostFoundReport.title == r_spec["title"],
                LostFoundReport.report_type == r_spec["report_type"]
            ).first()
            if not existing_rep:
                rep = LostFoundReport(
                    student_id=r_spec["student_id"],
                    report_type=r_spec["report_type"],
                    title=r_spec["title"],
                    description=r_spec["description"],
                    location=r_spec["location"],
                    image_url=r_spec["image_url"],
                    status=r_spec["status"],
                    created_at=r_spec["created_at"]
                )
                db.add(rep)
                db.flush()
                created_reports[r_spec["title"]] = rep
                print(f" [+] Created Lost & Found ({rep.report_type}): '{rep.title}' [ID {rep.id}]")
            else:
                created_reports[r_spec["title"]] = existing_rep
                print(f" [=] Preserved Lost & Found ({existing_rep.report_type}): '{existing_rep.title}' [ID {existing_rep.id}]")

        bottle_report = created_reports["Blue Milton Stainless Steel Water Bottle"]

        # ----------------------------------------------------------------------
        # 4. SEED ONE BORROW REQUEST FROM ANANYA
        # ----------------------------------------------------------------------
        print("\n[4/7] Checking Borrow Requests...")
        existing_breq = db.query(BorrowRequest).filter(
            BorrowRequest.listing_id == laptop_stand_borrow.id,
            BorrowRequest.borrower_id == ananya.id
        ).first()

        if not existing_breq:
            breq = BorrowRequest(
                listing_id=laptop_stand_borrow.id,
                borrower_id=ananya.id,
                status="pending",
                note="Hi Varshitha! I have a 24-hour hackathon presentation this weekend at AB1. May I borrow your laptop stand till Sunday evening?",
                created_at=now - timedelta(hours=3, minutes=15)
            )
            db.add(breq)
            db.flush()
            print(f" [+] Created BorrowRequest from Ananya: [ID {breq.id}] on '{laptop_stand_borrow.title}'")
        else:
            breq = existing_breq
            print(f" [=] Preserved BorrowRequest from Ananya: [ID {breq.id}]")

        # ----------------------------------------------------------------------
        # 5. SEED TEN MESSAGES ACROSS TWO ACTIVE CONVERSATIONS
        # ----------------------------------------------------------------------
        print("\n[5/7] Checking direct messages (10 messages in 2 conversations)...")
        ananya_dialogues = [
            (ananya.id, varshitha.id, laptop_stand_borrow.id, "Hey Varshitha! Is your foldable laptop stand still available for borrowing this weekend?", now - timedelta(hours=4, minutes=10), True),
            (varshitha.id, ananya.id, laptop_stand_borrow.id, "Hi Ananya! Yes, it's completely available. You can pick it up near the central library or Rock Plaza.", now - timedelta(hours=3, minutes=45), True),
            (ananya.id, varshitha.id, laptop_stand_borrow.id, "That's awesome! I just sent a borrow request through UniLink. I'll meet you near Library Block at 4 PM.", now - timedelta(hours=3, minutes=10), True),
            (varshitha.id, ananya.id, laptop_stand_borrow.id, "Sounds perfect! See you there. Please bring your campus ID card.", now - timedelta(hours=2, minutes=30), True),
            (ananya.id, varshitha.id, laptop_stand_borrow.id, "Will do! Also, is your Casio calculator still for sale? My lab partner was looking for one.", now - timedelta(minutes=45), False)
        ]

        test_student_dialogues = [
            (test_student.id, varshitha.id, calc_listing.id, "Hello Varshitha! I saw your listing for the Casio FX-991ES Plus calculator. Is the price negotiable to Rs 700?", now - timedelta(days=1, hours=2), True),
            (varshitha.id, test_student.id, calc_listing.id, "Hi! Rs 700 works for me if you can collect it from AB1 2nd Floor today.", now - timedelta(days=1, hours=1), True),
            (test_student.id, varshitha.id, calc_listing.id, "Deal! Can we meet near AB1 G02 around 5 PM after classes?", now - timedelta(hours=5), True),
            (varshitha.id, test_student.id, calc_listing.id, "Yes, 5 PM at AB1 G02 works great. I'll bring the original case as well.", now - timedelta(hours=4), True),
            (test_student.id, varshitha.id, calc_listing.id, "Thanks Varshitha! I'm on my way there now.", now - timedelta(minutes=25), False)
        ]

        total_seeded_messages = 0
        for s_id, r_id, l_id, text, timestamp, is_read in (ananya_dialogues + test_student_dialogues):
            existing_msg = db.query(Message).filter(
                Message.sender_id == s_id,
                Message.receiver_id == r_id,
                Message.listing_id == l_id,
                Message.content == text
            ).first()
            if not existing_msg:
                m = Message(
                    sender_id=s_id,
                    receiver_id=r_id,
                    listing_id=l_id,
                    content=text,
                    is_read=is_read,
                    created_at=timestamp
                )
                db.add(m)
                total_seeded_messages += 1
                print(f" [+] Inserted message: '{text[:45]}...'")
            else:
                print(f" [=] Preserved message: '{text[:45]}...'")

        # ----------------------------------------------------------------------
        # 6. SEED SIX NOTIFICATIONS FOR VARSHITHA
        # ----------------------------------------------------------------------
        print("\n[6/7] Checking Notifications for Varshitha (6 notifications)...")
        sample_notifications = [
            {
                "notification_type": "borrow_request",
                "title": "New Borrow Request from Ananya",
                "content": "Ananya requested to borrow your 'Ergonomic Aluminum Foldable Laptop Stand'. Review terms and approve.",
                "listing_id": laptop_stand_borrow.id,
                "borrow_request_id": breq.id,
                "lost_found_report_id": None,
                "is_read": False,
                "created_at": now - timedelta(hours=3, minutes=15)
            },
            {
                "notification_type": "message",
                "title": "New Message from Ananya",
                "content": "Ananya: 'Will do! Also, is your Casio calculator still for sale? My lab partner was looking for one.'",
                "listing_id": laptop_stand_borrow.id,
                "borrow_request_id": None,
                "lost_found_report_id": None,
                "is_read": False,
                "created_at": now - timedelta(minutes=45)
            },
            {
                "notification_type": "message",
                "title": "New Message from Test Student",
                "content": "Test Student: 'Thanks Varshitha! I'm on my way there now.'",
                "listing_id": calc_listing.id,
                "borrow_request_id": None,
                "lost_found_report_id": None,
                "is_read": False,
                "created_at": now - timedelta(minutes=25)
            },
            {
                "notification_type": "claim_update",
                "title": "Lost & Found Campus Notice",
                "content": "A found item matching 'Blue Milton Stainless Steel Water Bottle' was turned in at CB Cafeteria security desk.",
                "listing_id": None,
                "borrow_request_id": None,
                "lost_found_report_id": bottle_report.id,
                "is_read": True,
                "created_at": now - timedelta(days=1, hours=4)
            },
            {
                "notification_type": "item_update",
                "title": "Marketplace Listing Published",
                "content": "Your listing 'Casio FX-991ES Plus Scientific Calculator' is now live on the VIT-AP campus marketplace.",
                "listing_id": calc_listing.id,
                "borrow_request_id": None,
                "lost_found_report_id": None,
                "is_read": True,
                "created_at": now - timedelta(days=2)
            },
            {
                "notification_type": "system",
                "title": "Welcome to UniLink Campus Platform",
                "content": "Explore Marketplace, Peer Borrowing, and Lost & Found with your verified campus student account.",
                "listing_id": None,
                "borrow_request_id": None,
                "lost_found_report_id": None,
                "is_read": True,
                "created_at": now - timedelta(days=3)
            }
        ]

        for notif in sample_notifications:
            existing_notif = db.query(Notification).filter(
                Notification.student_id == varshitha.id,
                Notification.notification_type == notif["notification_type"],
                Notification.title == notif["title"]
            ).first()
            if not existing_notif:
                n = Notification(
                    student_id=varshitha.id,
                    notification_type=notif["notification_type"],
                    title=notif["title"],
                    content=notif["content"],
                    listing_id=notif["listing_id"],
                    borrow_request_id=notif["borrow_request_id"],
                    lost_found_report_id=notif["lost_found_report_id"],
                    is_read=notif["is_read"],
                    created_at=notif["created_at"]
                )
                db.add(n)
                print(f" [+] Inserted notification: '{n.title}'")
            else:
                print(f" [=] Preserved notification: '{existing_notif.title}'")

        # ----------------------------------------------------------------------
        # 7. SEED TWO SAVED ITEM RELATIONSHIPS
        # ----------------------------------------------------------------------
        print("\n[7/7] Checking Saved Items (Bookmarks)...")
        # 1. Varshitha saved the DSA textbook borrow listing
        existing_save1 = db.query(SavedItem).filter(
            SavedItem.student_id == varshitha.id,
            SavedItem.listing_id == dsa_book_listing.id
        ).first()
        if not existing_save1:
            s1 = SavedItem(
                student_id=varshitha.id,
                listing_id=dsa_book_listing.id,
                created_at=now - timedelta(days=1)
            )
            db.add(s1)
            print(f" [+] Created bookmark: Varshitha -> '{dsa_book_listing.title}'")
        else:
            print(f" [=] Preserved bookmark: Varshitha -> '{dsa_book_listing.title}'")

        # 2. Ananya saved Varshitha's Casio Calculator marketplace listing
        existing_save2 = db.query(SavedItem).filter(
            SavedItem.student_id == ananya.id,
            SavedItem.listing_id == calc_listing.id
        ).first()
        if not existing_save2:
            s2 = SavedItem(
                student_id=ananya.id,
                listing_id=calc_listing.id,
                created_at=now - timedelta(hours=5)
            )
            db.add(s2)
            print(f" [+] Created bookmark: Ananya -> '{calc_listing.title}'")
        else:
            print(f" [=] Preserved bookmark: Ananya -> '{calc_listing.title}'")

        # Commit transaction atomically
        db.commit()
        print("\n" + "=" * 70)
        print(" SEEDING SUCCESS: Production demo experience is active & ready!")
        print("=" * 70)
        return True

    except Exception as exc:
        db.rollback()
        print(f"\n[ERROR] Seeding encountered an error and rolled back: {type(exc).__name__}: {exc}")
        return False
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Idempotently seed demo data into UniLink production Neon PostgreSQL."
    )
    parser.add_argument(
        "target_url",
        nargs="?",
        default=os.getenv("TARGET_DATABASE_URL", ""),
        help="Target Neon PostgreSQL connection URL (or set TARGET_DATABASE_URL env var)"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Perform static validation of sample data structures without connecting to any database"
    )

    args = parser.parse_args()

    if args.validate_only:
        spec = validate_sample_data_spec()
        print("Static validation passed:")
        print(f" - Accounts count : {spec['demo_accounts_count']}")
        print(f" - Target emails   : {', '.join(spec['target_emails'])}")
        sys.exit(0)

    target_url = (args.target_url or "").strip()
    if not target_url and sys.stdin.isatty():
        try:
            target_url = getpass.getpass("Enter target Neon database URL (input hidden): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[ABORTED] Operation canceled by user.")
            sys.exit(1)

    if not target_url:
        print("[ERROR] Target database URL is required.")
        print("Usage: python seed_production_demo.py <NEON_DATABASE_URL>")
        print("   or: set TARGET_DATABASE_URL=<NEON_DATABASE_URL>")
        sys.exit(1)

    # Passwords are never accepted as CLI flags. By default, newly created demo accounts
    # use their email local part (before @), or an optional DEMO_PASSWORD env override.
    demo_password_override = os.getenv("DEMO_PASSWORD", "").strip()

    success = seed_demo_data(target_url, demo_password=demo_password_override)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
