from decimal import Decimal
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, Boolean, Date,
    DateTime, ForeignKey, UniqueConstraint, Index, text
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

try:
    from backend.database import Base
except ImportError:
    from database import Base


# ==============================================================================
# 1. STUDENT MODEL
# ==============================================================================
class Student(Base):
    """
    Represents registered students on UniLink.
    Accounts are created unverified (is_verified=False) by default and verified
    via official college email (@vitapstudent.ac.in).
    """
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    reg_no = Column(String(50), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    avatar_index = Column(Integer, default=0, nullable=False)  # Mascot 0 to 19
    year_of_study = Column(String(50), default="1st Year", nullable=False)
    program = Column(String(100), default="B.Tech", nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)  # Requires college-email verification
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    listings = relationship("Listing", back_populates="owner", cascade="all, delete-orphan")
    lost_found_reports = relationship("LostFoundReport", back_populates="reporter")
    lost_found_claims = relationship("LostFoundClaim", back_populates="claimant", cascade="all, delete-orphan")
    borrow_requests = relationship("BorrowRequest", back_populates="borrower", cascade="all, delete-orphan")
    saved_items = relationship("SavedItem", back_populates="student", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="recipient", cascade="all, delete-orphan")
    sent_messages = relationship(
        "Message",
        foreign_keys="Message.sender_id",
        back_populates="sender"
    )
    received_messages = relationship(
        "Message",
        foreign_keys="Message.receiver_id",
        back_populates="receiver"
    )


# ==============================================================================
# 2. LISTING MODEL
# ==============================================================================
class Listing(Base):
    """
    Unified model for both Marketplace (for sale) and Peer Borrow/Lend items.
    Distinguished by `listing_type`: 'marketplace' or 'borrow'.
    Price uses Numeric(10, 2) in INR, default 0.00 for free peer borrow items.
    """
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    listing_type = Column(String(20), nullable=False, default="marketplace")  # 'marketplace' or 'borrow'
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False)  # 'Electronics', 'Books', 'Clothing', 'Sports', 'Others'
    price = Column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))  # Exact INR currency representation
    location = Column(String(100), nullable=False)  # e.g., 'CB 303', 'LH3', 'MH1', 'Library'
    image_url = Column(String(255), nullable=True)
    condition = Column(String(50), default="Good", nullable=False)  # 'Like New', 'Good', 'Fair'
    available_till = Column(Date, nullable=True)  # Date until item is available for borrow (nullable)
    status = Column(String(30), default="active", nullable=False)  # 'active', 'sold', 'borrowed', 'archived'
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    owner = relationship("Student", back_populates="listings")
    borrow_requests = relationship("BorrowRequest", back_populates="listing", cascade="all, delete-orphan")
    saved_by = relationship("SavedItem", back_populates="listing", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="listing")
    notifications = relationship("Notification", back_populates="listing")


# ==============================================================================
# 3. LOST & FOUND REPORT MODEL
# ==============================================================================
class LostFoundReport(Base):
    """
    Lost & Found notices reported across campus.
    Distinguished by `report_type`: 'lost' or 'found'.
    """
    __tablename__ = "lost_found_reports"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="SET NULL"), nullable=True)
    report_type = Column(String(10), nullable=False)  # 'lost' or 'found'
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    location = Column(String(100), nullable=False)  # e.g., 'Rock plaza', 'AB1 G02', 'Library'
    image_url = Column(String(255), nullable=True)
    status = Column(String(30), default="open", nullable=False)  # 'open', 'claimed', 'resolved'
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    reporter = relationship("Student", back_populates="lost_found_reports")
    claims = relationship("LostFoundClaim", back_populates="report", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="lost_found_report")


# ==============================================================================
# 4. LOST & FOUND CLAIM MODEL
# ==============================================================================
class LostFoundClaim(Base):
    """
    Tracks claims on found items or 'Found Match' notices for lost items.
    Uses a PostgreSQL partial unique index so students cannot submit duplicate
    active ('pending' or 'approved') claims, but CAN resubmit if a previous claim
    was 'rejected'.
    """
    __tablename__ = "lost_found_claims"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("lost_found_reports.id", ondelete="CASCADE"), nullable=False)
    claimant_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    claim_type = Column(String(20), default="ownership_claim", nullable=False)  # 'ownership_claim' or 'found_match'
    proof_details = Column(Text, nullable=True)
    status = Column(String(30), default="pending", nullable=False)  # 'pending', 'approved', 'rejected'
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Partial unique index: allows resubmission only after rejection
    __table_args__ = (
        Index(
            "uq_active_claim_per_report",
            "report_id",
            "claimant_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'approved')")
        ),
    )

    # Relationships
    report = relationship("LostFoundReport", back_populates="claims")
    claimant = relationship("Student", back_populates="lost_found_claims")


# ==============================================================================
# 5. BORROW REQUEST MODEL
# ==============================================================================
class BorrowRequest(Base):
    """
    Tracks peer borrow requests submitted by students for items listed under borrow/lend.
    """
    __tablename__ = "borrow_requests"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    borrower_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(30), default="pending", nullable=False)  # 'pending', 'approved', 'returned', 'declined'
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    listing = relationship("Listing", back_populates="borrow_requests")
    borrower = relationship("Student", back_populates="borrow_requests")
    notifications = relationship("Notification", back_populates="borrow_request")


# ==============================================================================
# 6. SAVED ITEM MODEL
# ==============================================================================
class SavedItem(Base):
    """
    Bookmarks saved by students across Marketplace and Borrow items.
    Unique constraint prevents duplicate saves for the same item.
    """
    __tablename__ = "saved_items"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("student_id", "listing_id", name="uq_student_saved_listing"),
    )

    # Relationships
    student = relationship("Student", back_populates="saved_items")
    listing = relationship("Listing", back_populates="saved_by")


# ==============================================================================
# 7. MESSAGE MODEL
# ==============================================================================
class Message(Base):
    """
    Direct messaging between students.
    Optional listing_id links the chat to the specific marketplace or borrow item.
    """
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("students.id", ondelete="SET NULL"), nullable=True)
    receiver_id = Column(Integer, ForeignKey("students.id", ondelete="SET NULL"), nullable=True)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="SET NULL"), nullable=True)
    content = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    sender = relationship("Student", foreign_keys=[sender_id], back_populates="sent_messages")
    receiver = relationship("Student", foreign_keys=[receiver_id], back_populates="received_messages")
    listing = relationship("Listing", back_populates="messages")


# ==============================================================================
# 8. NOTIFICATION MODEL
# ==============================================================================
class Notification(Base):
    """
    In-app notifications supporting tabs: 'All', 'Messages', 'Item Updates', 'System'.
    Includes optional foreign keys to listings, borrow requests, or lost/found reports.
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    notification_type = Column(String(30), nullable=False)  # 'message', 'item_update', 'borrow_request', 'claim_update', 'system'
    title = Column(String(150), nullable=False)
    content = Column(Text, nullable=True)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="SET NULL"), nullable=True)
    borrow_request_id = Column(Integer, ForeignKey("borrow_requests.id", ondelete="SET NULL"), nullable=True)
    lost_found_report_id = Column(Integer, ForeignKey("lost_found_reports.id", ondelete="SET NULL"), nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    recipient = relationship("Student", back_populates="notifications")
    listing = relationship("Listing", back_populates="notifications")
    borrow_request = relationship("BorrowRequest", back_populates="notifications")
    lost_found_report = relationship("LostFoundReport", back_populates="notifications")
