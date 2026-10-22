"""
seed_demo_data.py
=================
Idempotent script to seed realistic demo data for Varshitha's account on UniLink:
- 3 Marketplace listings (Scientific Calculator, Wireless Headphones, Engineering Notebook)
- 2 Borrow listings (DSA Textbook, Laptop Stand)
- Realistic 2-way conversations with Ananya and Test Student
- A realistic borrow request from Ananya on Varshitha's Borrow listing
- Realistic in-app notifications (messages, borrow request, lost & found alert)

Safety rules:
- Resolves accounts dynamically from DB by email.
- Never creates duplicate records on repeated runs.
- Does not modify existing student passwords, schemas, or unrelated accounts.
"""

import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime, date, timedelta, timezone

# Ensure backend can be imported
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal
from backend.models import Student, Listing, Message, Notification, BorrowRequest, LostFoundReport

VARSHITHA_EMAIL = "varshitha.25bca1234@vitapstudent.ac.in"
ANANYA_EMAIL = "ananya.25bce1234@vitapstudent.ac.in"
TEST_STUDENT_EMAIL = "test.25bca2008@vitapstudent.ac.in"

def run_seed():
    print("=" * 65)
    print(" UniLink - Seed Realistic Demo Data for Varshitha")
    print("=" * 65)

    db = SessionLocal()
    try:
        # 1. Resolve student records
        varshitha = db.query(Student).filter(Student.email == VARSHITHA_EMAIL).first()
        ananya = db.query(Student).filter(Student.email == ANANYA_EMAIL).first()
        test_student = db.query(Student).filter(Student.email == TEST_STUDENT_EMAIL).first()

        if not varshitha:
            print(f"ERROR: Varshitha account not found ({VARSHITHA_EMAIL}).")
            sys.exit(1)
        if not ananya:
            print(f"ERROR: Ananya account not found ({ANANYA_EMAIL}).")
            sys.exit(1)
        if not test_student:
            print(f"ERROR: Test Student account not found ({TEST_STUDENT_EMAIL}).")
            sys.exit(1)

        print(f"Resolved Target Accounts:")
        print(f" - Varshitha:   ID={varshitha.id} ({varshitha.full_name})")
        print(f" - Ananya:      ID={ananya.id} ({ananya.full_name})")
        print(f" - Test Student:ID={test_student.id} ({test_student.full_name})\n")

        now = datetime.now(timezone.utc)

        # -------------------------------------------------------------
        # 2. Seed My Listings (3 Marketplace + 2 Borrow owned by Varshitha)
        # -------------------------------------------------------------
        print("Checking Varshitha's Listings...")

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

        created_listings = []

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
                    status=item["status"]
                )
                db.add(l)
                db.flush()
                created_listings.append(l)
                print(f" [+] Created Marketplace listing: '{l.title}' (ID {l.id})")
            else:
                created_listings.append(existing)
                print(f" [=] Existing Marketplace listing: '{existing.title}' (ID {existing.id})")

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
                    status=item["status"]
                )
                db.add(l)
                db.flush()
                created_listings.append(l)
                print(f" [+] Created Borrow listing: '{l.title}' (ID {l.id})")
            else:
                created_listings.append(existing)
                print(f" [=] Existing Borrow listing: '{existing.title}' (ID {existing.id})")

        calc_listing = created_listings[0]
        laptop_stand_borrow = created_listings[4]

        # -------------------------------------------------------------
        # 3. Seed Realistic Borrow Request from Ananya on Varshitha's Laptop Stand
        # -------------------------------------------------------------
        print("\nChecking Borrow Requests...")
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
            print(f" [+] Created BorrowRequest from Ananya: ID {breq.id} on '{laptop_stand_borrow.title}'")
        else:
            breq = existing_breq
            print(f" [=] Existing BorrowRequest found: ID {breq.id}")

        # -------------------------------------------------------------
        # 4. Seed Messages (Conversations with Ananya and Test Student)
        # -------------------------------------------------------------
        print("\nChecking Messages...")

        # Conversation 1: Ananya & Varshitha (about borrowing laptop stand & marketplace calculator)
        ananya_dialogues = [
            (ananya.id, varshitha.id, laptop_stand_borrow.id, "Hey Varshitha! Is your foldable laptop stand still available for borrowing this weekend?", now - timedelta(hours=4, minutes=10), True),
            (varshitha.id, ananya.id, laptop_stand_borrow.id, "Hi Ananya! Yes, it's completely available. You can pick it up near the central library or Rock Plaza.", now - timedelta(hours=3, minutes=45), True),
            (ananya.id, varshitha.id, laptop_stand_borrow.id, "That's awesome! I just sent a borrow request through UniLink. I'll meet you near Library Block at 4 PM.", now - timedelta(hours=3, minutes=10), True),
            (varshitha.id, ananya.id, laptop_stand_borrow.id, "Sounds perfect! See you there. Please bring your campus ID card.", now - timedelta(hours=2, minutes=30), True),
            (ananya.id, varshitha.id, laptop_stand_borrow.id, "Will do! Also, is your Casio calculator still for sale? My lab partner was looking for one.", now - timedelta(minutes=45), False)
        ]

        # Conversation 2: Test Student & Varshitha (about calculator marketplace listing)
        test_student_dialogues = [
            (test_student.id, varshitha.id, calc_listing.id, "Hello Varshitha! I saw your listing for the Casio FX-991ES Plus calculator. Is the price negotiable to Rs 700?", now - timedelta(days=1, hours=2), True),
            (varshitha.id, test_student.id, calc_listing.id, "Hi! Rs 700 works for me if you can collect it from AB1 2nd Floor today.", now - timedelta(days=1, hours=1), True),
            (test_student.id, varshitha.id, calc_listing.id, "Deal! Can we meet near AB1 G02 around 5 PM after classes?", now - timedelta(hours=5), True),
            (varshitha.id, test_student.id, calc_listing.id, "Yes, 5 PM at AB1 G02 works great. I'll bring the original case as well.", now - timedelta(hours=4), True),
            (test_student.id, varshitha.id, calc_listing.id, "Thanks Varshitha! I'm on my way there now.", now - timedelta(minutes=25), False)
        ]

        # Conversation 3: Ananya & Varshitha (Lost & Found coordination)
        # Checking for existing lost found report on campus
        lf_report = db.query(LostFoundReport).first()
        lf_report_id = lf_report.id if lf_report else None

        for sender_id, receiver_id, list_id, text, timestamp, is_read in (ananya_dialogues + test_student_dialogues):
            existing_msg = db.query(Message).filter(
                Message.sender_id == sender_id,
                Message.receiver_id == receiver_id,
                Message.content == text
            ).first()
            if not existing_msg:
                m = Message(
                    sender_id=sender_id,
                    receiver_id=receiver_id,
                    listing_id=list_id,
                    content=text,
                    is_read=is_read,
                    created_at=timestamp
                )
                db.add(m)
                print(f" [+] Inserted message: '{text[:40]}...' (from {sender_id} to {receiver_id})")

        # -------------------------------------------------------------
        # 5. Seed Notifications for Varshitha (Messages, Borrow, Lost & Found)
        # -------------------------------------------------------------
        print("\nChecking Notifications...")

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
                "content": "A found item matching 'Blue Water Bottle' was turned in at CB Cafeteria security desk.",
                "listing_id": None,
                "borrow_request_id": None,
                "lost_found_report_id": lf_report_id,
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
                print(f" [+] Inserted notification: '{n.title}' (read={n.is_read})")
            else:
                print(f" [=] Existing notification: '{existing_notif.title}'")

        db.commit()
        print("\n" + "=" * 65)
        print(" SEEDING COMPLETE: Demo data successfully populated for Varshitha!")
        print("=" * 65)

    except Exception as exc:
        db.rollback()
        print(f"\nERROR during seeding: {exc}")
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    run_seed()
