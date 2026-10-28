"""
schemas.py
==========
Pydantic data models for UniLink authentication and data contracts.
Handles input validation, password length bounds (bcrypt 72-byte limit),
and output serialization without exposing sensitive password hashes.
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator


# ==============================================================================
# 1. REGISTRATION SCHEMA
# ==============================================================================
class StudentRegister(BaseModel):
    """
    Schema for manual student registration.
    - Password must be at least 8 characters and at most 72 UTF-8 bytes (bcrypt limit).
    - Email must belong to the approved institutional domain (@vitapstudent.ac.in).
    - Does NOT accept 'is_verified' from the client.
    """
    full_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Full display name of the student"
    )
    email: EmailStr = Field(
        ...,
        description="Official campus email ending with @vitapstudent.ac.in"
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=72,
        description="Account password (min 8 characters, max 72 bytes)"
    )
    reg_no: Optional[str] = Field(
        None,
        max_length=50,
        description="University registration number (e.g. 25bca1234)"
    )
    program: Optional[str] = Field(
        "B.Tech",
        max_length=100,
        description="Degree program (e.g. B.Tech, BBA, M.Tech)"
    )
    year_of_study: Optional[str] = Field(
        "1st Year",
        max_length=50,
        description="Academic year (e.g. 1st Year, 2nd Year)"
    )
    avatar_index: int = Field(
        0,
        ge=0,
        le=19,
        description="Selected mascot avatar index (0 to 19)"
    )

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        """
        Bcrypt has an algorithmic limit of 72 bytes.
        Validates the raw UTF-8 byte length to avoid unexpected truncation.
        """
        raw_bytes = value.encode("utf-8")
        if len(raw_bytes) > 72:
            raise ValueError(
                "Password exceeds the 72-byte limit. Please choose a slightly shorter password."
            )
        return value

    @field_validator("email")
    @classmethod
    def validate_campus_domain(cls, value: str) -> str:
        """
        Enforces that registrations use an approved institutional domain (@vitapstudent.ac.in or @vitap.ac.in).
        NOTE: Validating domain policy here does NOT prove mailbox ownership.
        All manual registrations remain is_verified=False until a verification flow occurs.
        """
        email_clean = value.strip().lower()
        if not (email_clean.endswith("@vitapstudent.ac.in") or email_clean.endswith("@vitap.ac.in")):
            raise ValueError(
                "Registration is restricted to official campus emails (@vitapstudent.ac.in, @vitap.ac.in)."
            )
        return email_clean


# ==============================================================================
# 2. LOGIN SCHEMA
# ==============================================================================
class StudentLogin(BaseModel):
    """
    Schema for authenticating existing students.
    """
    email: EmailStr = Field(..., description="Registered campus email")
    password: str = Field(..., min_length=1, max_length=72, description="Account password")


# ==============================================================================
# 3. TOKEN SCHEMAS
# ==============================================================================
class Token(BaseModel):
    """
    Standard OAuth2 / JWT access token response.
    """
    access_token: str
    token_type: str = "bearer"


class TokenResponse(BaseModel):
    """
    Login response returning access token and public student profile.
    """
    access_token: str
    token_type: str = "bearer"
    student: "StudentOut"


class TokenData(BaseModel):
    """
    Internal decoded token payload.
    The 'sub' claim stores the student's integer ID serialized as a string.
    """
    student_id: int
    email: Optional[str] = None


# ==============================================================================
# 4. STUDENT OUTPUT (PUBLIC PROFILE) SCHEMA
# ==============================================================================
class StudentOut(BaseModel):
    """
    Safe public student profile representation.
    Never exposes 'hashed_password'.
    """
    id: int
    full_name: str
    email: str
    reg_no: Optional[str] = None
    avatar_index: int
    year_of_study: str
    program: str
    is_verified: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class StudentUpdate(BaseModel):
    """
    Schema for updating student profile fields.
    Restricted to permitted, safe attributes (e.g. avatar_index, full_name, program, year_of_study, reg_no).
    Does NOT allow updating password, email, or is_verified here.
    """
    avatar_index: Optional[int] = Field(None, ge=0, le=19, description="Mascot index (0 to 19)")
    full_name: Optional[str] = Field(None, min_length=1, max_length=100, description="Full student name")
    program: Optional[str] = Field(None, max_length=100, description="Degree or academic program")
    year_of_study: Optional[str] = Field(None, max_length=50, description="Academic year")
    reg_no: Optional[str] = Field(None, max_length=50, description="Registration number")


# ==============================================================================
# 5. GOOGLE LOGIN SCHEMA (For Phase 2)
# ==============================================================================
class GoogleLoginRequest(BaseModel):
    """
    Schema for receiving Google Identity Services ID token from frontend.
    """
    id_token: str = Field(..., description="Google ID Token issued by Google Identity Services")


# ==============================================================================
# 6. STUDENT BRIEF (PUBLIC OWNER INFO FOR LISTINGS)
# ==============================================================================
class StudentBrief(BaseModel):
    """
    Sanitized public profile of a listing owner / student lender.
    Never exposes passwords, tokens, or private system attributes.
    """
    id: int
    full_name: str
    email: str
    avatar_index: int = 0
    year_of_study: Optional[str] = "1st Year"
    program: Optional[str] = "B.Tech"
    is_verified: bool = False

    class Config:
        from_attributes = True


# ==============================================================================
# 7. MARKETPLACE LISTING SCHEMAS
# ==============================================================================
class ListingBase(BaseModel):
    """
    Base attributes shared between marketplace and borrow listings.
    """
    title: str = Field(..., min_length=2, max_length=150, description="Item title")
    description: Optional[str] = Field(None, max_length=2000, description="Item description")
    category: str = Field(..., min_length=2, max_length=50, description="Item category (e.g. Electronics, Books)")
    location: str = Field(..., min_length=2, max_length=100, description="Campus location or pickup spot (e.g. CB 303, LH3)")
    image_url: Optional[str] = Field(None, max_length=255, description="Image asset path or URL")
    condition: Optional[str] = Field("Good", max_length=50, description="Item condition (Like New, Good, Fair)")


class ListingCreate(ListingBase):
    """
    Payload for creating a new Marketplace item listing (for sale).
    Owner is resolved server-side from Bearer JWT.
    """
    price: Decimal = Field(
        default=Decimal("0.00"),
        ge=Decimal("0.00"),
        le=Decimal("999999.99"),
        description="Price in INR (0.00 for free items)"
    )


class ListingUpdate(BaseModel):
    """
    Payload for modifying an existing Marketplace item listing.
    Only non-null supplied fields will be updated.
    """
    title: Optional[str] = Field(None, min_length=2, max_length=150)
    description: Optional[str] = Field(None, max_length=2000)
    category: Optional[str] = Field(None, min_length=2, max_length=50)
    price: Optional[Decimal] = Field(None, ge=Decimal("0.00"), le=Decimal("999999.99"))
    location: Optional[str] = Field(None, min_length=2, max_length=100)
    image_url: Optional[str] = Field(None, max_length=255)
    condition: Optional[str] = Field(None, max_length=50)
    status: Optional[str] = Field(None, max_length=30, description="Status: 'active', 'sold', or 'archived'")


# ==============================================================================
# 8. BORROW LISTING SCHEMAS
# ==============================================================================
class BorrowListingCreate(ListingBase):
    """
    Payload for creating a peer borrow item listing.
    Price is locked to 0.00 INR on the backend since campus peer borrowing is free.
    """
    available_till: Optional[date] = Field(None, description="Date until item is available to borrow (YYYY-MM-DD)")


class BorrowListingUpdate(BaseModel):
    """
    Payload for modifying an existing peer borrow listing.
    """
    title: Optional[str] = Field(None, min_length=2, max_length=150)
    description: Optional[str] = Field(None, max_length=2000)
    category: Optional[str] = Field(None, min_length=2, max_length=50)
    location: Optional[str] = Field(None, min_length=2, max_length=100)
    image_url: Optional[str] = Field(None, max_length=255)
    condition: Optional[str] = Field(None, max_length=50)
    available_till: Optional[date] = Field(None, description="Date until item is available to borrow")
    status: Optional[str] = Field(None, max_length=30, description="Status: 'active', 'borrowed', or 'archived'")



# ==============================================================================
# 9. OUTPUT & ACTION SCHEMAS
# ==============================================================================
class ListingOut(BaseModel):
    """
    Public listing response schema.
    Includes the owner's safe brief public profile.
    """
    id: int
    student_id: int
    listing_type: str
    title: str
    description: Optional[str] = None
    category: str
    price: Decimal
    location: str
    image_url: Optional[str] = None
    condition: str
    available_till: Optional[date] = None
    status: str
    created_at: datetime
    owner: Optional[StudentBrief] = None

    class Config:
        from_attributes = True


class ListingActionResponse(BaseModel):
    """
    Response schema for actions like delete or status toggles.
    """
    message: str
    id: int


# ==============================================================================
# 10. LOST & FOUND SCHEMAS
# ==============================================================================
class LostFoundReportCreate(BaseModel):
    """
    Payload for creating a Lost or Found campus report.
    Reporter is resolved server-side from Bearer JWT.
    """
    report_type: str = Field(..., description="'lost' or 'found'")
    title: str = Field(..., min_length=2, max_length=150, description="Title/name of the item")
    description: Optional[str] = Field(None, max_length=2000, description="Detailed item description and unique identifying marks")
    location: str = Field(..., min_length=2, max_length=100, description="Location where item was lost or found (e.g. Rock Plaza, Library)")
    image_url: Optional[str] = Field(None, max_length=255, description="Image asset path or URL")

    @field_validator("report_type")
    @classmethod
    def validate_report_type(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in ("lost", "found"):
            raise ValueError("report_type must be either 'lost' or 'found'")
        return clean


class LostFoundReportUpdate(BaseModel):
    """
    Payload for modifying an existing Lost or Found report (by report owner).
    """
    title: Optional[str] = Field(None, min_length=2, max_length=150)
    description: Optional[str] = Field(None, max_length=2000)
    location: Optional[str] = Field(None, min_length=2, max_length=100)
    image_url: Optional[str] = Field(None, max_length=255)
    status: Optional[str] = Field(None, max_length=30, description="'open', 'claimed', or 'resolved'")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        clean = v.strip().lower()
        if clean not in ("open", "claimed", "resolved"):
            raise ValueError("status must be 'open', 'claimed', or 'resolved'")
        return clean


class LostFoundClaimCreate(BaseModel):
    """
    Payload for submitting an ownership claim or found match notice.
    Claimant is resolved server-side from Bearer JWT.
    """
    claim_type: Optional[str] = Field("ownership_claim", description="'ownership_claim' or 'found_match'")
    proof_details: Optional[str] = Field(None, max_length=2000, description="Detailed proof of ownership or where found")

    @field_validator("claim_type")
    @classmethod
    def validate_claim_type(cls, v: Optional[str]) -> str:
        if not v:
            return "ownership_claim"
        clean = v.strip().lower()
        if clean not in ("ownership_claim", "found_match"):
            raise ValueError("claim_type must be 'ownership_claim' or 'found_match'")
        return clean


class LostFoundClaimReview(BaseModel):
    """
    Payload for the report owner to review/resolve a claim ('approved' or 'rejected').
    """
    status: str = Field(..., description="Target status: 'approved' or 'rejected'")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in ("approved", "rejected"):
            raise ValueError("status must be 'approved' or 'rejected'")
        return clean


class LostFoundClaimOut(BaseModel):
    """
    Public schema for a Lost & Found claim.
    """
    id: int
    report_id: int
    claimant_id: int
    claim_type: str
    proof_details: Optional[str] = None
    status: str
    created_at: datetime
    claimant: Optional[StudentBrief] = None

    class Config:
        from_attributes = True


class LostFoundReportOut(BaseModel):
    """
    Public schema for a Lost & Found report.
    Includes reporter public summary and claims count or claim details.
    """
    id: int
    student_id: Optional[int] = None
    report_type: str
    title: str
    description: Optional[str] = None
    location: str
    image_url: Optional[str] = None
    status: str
    created_at: datetime
    reporter: Optional[StudentBrief] = None
    claims_count: int = 0
    claims: Optional[List[LostFoundClaimOut]] = None

    class Config:
        from_attributes = True


class LostFoundActionResponse(BaseModel):
    """
    Response schema for general Lost & Found actions.
    """
    message: str
    id: int


# ==============================================================================
# 11. MESSAGING SCHEMAS
# ==============================================================================
class MessageCreate(BaseModel):
    """
    Payload for sending a message to another student.
    Sender is derived server-side from Bearer JWT.
    """
    receiver_id: int = Field(..., gt=0, description="Recipient student ID")
    content: str = Field(..., min_length=1, max_length=5000, description="Message text content")
    listing_id: Optional[int] = Field(None, gt=0, description="Optional associated marketplace or borrow listing ID")

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Message content cannot be empty or only whitespace")
        return clean


class MessageOut(BaseModel):
    """
    Public schema for a direct message between students.
    """
    id: int
    sender_id: Optional[int] = None
    receiver_id: Optional[int] = None
    listing_id: Optional[int] = None
    content: str
    is_read: bool
    created_at: datetime
    sender: Optional[StudentBrief] = None
    receiver: Optional[StudentBrief] = None

    class Config:
        from_attributes = True


class ConversationSummary(BaseModel):
    """
    Summary of a 1-on-1 conversation for inbox listing.
    """
    other_student: StudentBrief
    last_message: MessageOut
    unread_count: int = 0
    listing_id: Optional[int] = None


class MessageMarkReadResponse(BaseModel):
    """
    Response schema after marking messages as read.
    """
    message: str
    marked_count: int


# ==============================================================================
# 12. NOTIFICATION SCHEMAS
# ==============================================================================
class NotificationOut(BaseModel):
    """
    Public schema for an in-app student notification.
    """
    id: int
    student_id: int
    notification_type: str
    title: str
    content: Optional[str] = None
    listing_id: Optional[int] = None
    borrow_request_id: Optional[int] = None
    lost_found_report_id: Optional[int] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationMarkReadResponse(BaseModel):
    """
    Response schema after updating notification read status.
    """
    message: str
    id: Optional[int] = None
    marked_count: Optional[int] = None


# ==============================================================================
# 13. SAVED ITEM SCHEMAS
# ==============================================================================
class SavedItemOut(BaseModel):
    """
    Public schema for a student's bookmarked listing.
    Includes full listing details and whether it is marketplace or borrow.
    """
    id: int
    student_id: int
    listing_id: int
    created_at: datetime
    listing: Optional[ListingOut] = None

    class Config:
        from_attributes = True


class SavedItemActionResponse(BaseModel):
    """
    Response schema for saving or removing an item from bookmarks.
    """
    message: str
    listing_id: int
    is_saved: bool


# ==============================================================================
# 14. BORROW REQUEST SCHEMAS
# ==============================================================================
class BorrowRequestCreate(BaseModel):
    """
    Payload for requesting to borrow a peer listing.
    Borrower identity is resolved server-side from Bearer JWT.
    """
    note: Optional[str] = Field(None, max_length=1000, description="Optional note or request message")

    @field_validator("note")
    @classmethod
    def clean_note(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            return v if v else None
        return None


class BorrowRequestReview(BaseModel):
    """
    Payload for the listing owner to review/update request status.
    """
    status: str = Field(..., description="Target status: 'approved', 'declined', or 'returned'")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in ("approved", "declined", "returned"):
            raise ValueError("Status must be 'approved', 'declined', or 'returned'")
        return clean


class BorrowRequestOut(BaseModel):
    """
    Public schema for a peer borrow request.
    """
    id: int
    listing_id: int
    borrower_id: int
    status: str
    note: Optional[str] = None
    created_at: datetime
    borrower: Optional[StudentBrief] = None
    listing: Optional[ListingOut] = None

    class Config:
        from_attributes = True


class BorrowRequestActionResponse(BaseModel):
    """
    Response schema for borrow request status actions.
    """
    message: str
    id: int
    status: str


