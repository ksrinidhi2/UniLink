"""
borrow.py
=========
Peer Borrow Listing API endpoints for UniLink:
- GET /borrow: Browse active peer borrow listings with search and category filters.
- GET /borrow/me: Retrieve current student's borrow listings.
- GET /borrow/{listing_id}: View single borrow listing details.
- POST /borrow: Create a new peer borrow listing (authenticated student).
- PUT /borrow/{listing_id}: Update an owned borrow listing (authenticated owner only).
- DELETE /borrow/{listing_id}: Delete an owned borrow listing (authenticated owner only).
"""

from typing import List, Optional
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

try:
    from backend.database import get_db
    from backend.models import Listing, Student, BorrowRequest, Notification
    from backend.schemas import (
        BorrowListingCreate,
        BorrowListingUpdate,
        ListingOut,
        ListingActionResponse,
        BorrowRequestCreate,
        BorrowRequestReview,
        BorrowRequestOut,
        BorrowRequestActionResponse,
    )
    from backend.dependencies import get_current_student
except ImportError:
    from database import get_db
    from models import Listing, Student, BorrowRequest, Notification
    from schemas import (
        BorrowListingCreate,
        BorrowListingUpdate,
        ListingOut,
        ListingActionResponse,
        BorrowRequestCreate,
        BorrowRequestReview,
        BorrowRequestOut,
        BorrowRequestActionResponse,
    )
    from dependencies import get_current_student

router = APIRouter(prefix="/borrow", tags=["Peer Borrow Listings"])


# ==============================================================================
# 1. BROWSE ACTIVE BORROW LISTINGS
# ==============================================================================
@router.get(
    "",
    response_model=List[ListingOut],
    status_code=status.HTTP_200_OK,
    summary="Browse active peer borrow listings",
    description="Returns active peer borrow listings. Supports optional search keywords, category filtering, and pagination."
)
def get_borrow_listings(
    q: Optional[str] = Query(None, description="Search keyword in title, description, or location"),
    category: Optional[str] = Query(None, description="Category filter (e.g. Books, Electronics, Sports)"),
    skip: int = Query(0, ge=0, description="Number of listings to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of listings to return"),
    db: Session = Depends(get_db)
):
    query = (
        db.query(Listing)
        .options(joinedload(Listing.owner))
        .filter(
            Listing.listing_type == "borrow",
            Listing.status == "active"
        )
    )

    # Optional category filter (case-insensitive, ignoring 'all')
    if category and category.strip().lower() != "all":
        query = query.filter(func.lower(Listing.category) == category.strip().lower())

    # Optional text search filter
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            (Listing.title.ilike(term)) |
            (Listing.description.ilike(term)) |
            (Listing.location.ilike(term))
        )

    listings = query.order_by(Listing.created_at.desc()).offset(skip).limit(limit).all()
    return listings


# ==============================================================================
# 2. CURRENT STUDENT'S BORROW LISTINGS
# ==============================================================================
@router.get(
    "/me",
    response_model=List[ListingOut],
    status_code=status.HTTP_200_OK,
    summary="Get current student's borrow listings",
    description="Returns all peer borrow listings created by the currently authenticated student."
)
def get_my_borrow_listings(
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    listings = (
        db.query(Listing)
        .options(joinedload(Listing.owner))
        .filter(
            Listing.listing_type == "borrow",
            Listing.student_id == current_student.id
        )
        .order_by(Listing.created_at.desc())
        .all()
    )
    return listings


# ==============================================================================
# 3. GET SENT BORROW REQUESTS (AUTHENTICATED BORROWER)
# ==============================================================================
@router.get(
    "/requests/sent",
    response_model=List[BorrowRequestOut],
    status_code=status.HTTP_200_OK,
    summary="Get sent borrow requests",
    description="Returns all peer borrow requests submitted by the authenticated student."
)
def get_sent_borrow_requests(
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    requests = (
        db.query(BorrowRequest)
        .options(
            joinedload(BorrowRequest.borrower),
            joinedload(BorrowRequest.listing).joinedload(Listing.owner)
        )
        .filter(BorrowRequest.borrower_id == current_student.id)
        .order_by(BorrowRequest.created_at.desc())
        .all()
    )
    return requests


# ==============================================================================
# 4. GET RECEIVED BORROW REQUESTS (AUTHENTICATED LISTING OWNER)
# ==============================================================================
@router.get(
    "/requests/received",
    response_model=List[BorrowRequestOut],
    status_code=status.HTTP_200_OK,
    summary="Get received borrow requests",
    description="Returns all peer borrow requests received for listings owned by the authenticated student."
)
def get_received_borrow_requests(
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    requests = (
        db.query(BorrowRequest)
        .join(Listing, BorrowRequest.listing_id == Listing.id)
        .options(
            joinedload(BorrowRequest.borrower),
            joinedload(BorrowRequest.listing).joinedload(Listing.owner)
        )
        .filter(Listing.student_id == current_student.id)
        .order_by(BorrowRequest.created_at.desc())
        .all()
    )
    return requests


# ==============================================================================
# 5. REVIEW / DECIDE BORROW REQUEST (AUTHENTICATED LISTING OWNER ONLY)
# ==============================================================================
@router.put(
    "/requests/{request_id}",
    response_model=BorrowRequestOut,
    status_code=status.HTTP_200_OK,
    summary="Review/Update borrow request status",
    description="Allows only the listing owner to approve, decline, or mark returned a borrow request. Generates in-app notification to the borrower."
)
def review_borrow_request(
    request_id: int,
    payload: BorrowRequestReview,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    req = (
        db.query(BorrowRequest)
        .options(
            joinedload(BorrowRequest.borrower),
            joinedload(BorrowRequest.listing).joinedload(Listing.owner)
        )
        .filter(BorrowRequest.id == request_id)
        .first()
    )

    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Borrow request with ID {request_id} not found."
        )

    if not req.listing or req.listing.student_id != current_student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the listing owner can decide or update this borrow request."
        )

    target_status = payload.status.strip().lower()

    if req.status == target_status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Borrow request is already '{target_status}'."
        )

    if req.status in ("declined", "returned"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot change borrow request status once it has been '{req.status}'."
        )

    if target_status == "returned" and req.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only an approved borrow request can be marked as 'returned'."
        )

    # Apply status change
    req.status = target_status

    # Keep listing status synchronized
    if target_status == "approved":
        req.listing.status = "borrowed"
    elif target_status == "returned":
        req.listing.status = "active"

    try:
        # Create notification for the borrower
        borrower_notif = Notification(
            student_id=req.borrower_id,
            notification_type="borrow_request",
            title=f"Borrow Request {target_status.capitalize()}: {req.listing.title}",
            content=f"{current_student.full_name} has {target_status} your request to borrow '{req.listing.title}'.",
            listing_id=req.listing_id,
            borrow_request_id=req.id,
            is_read=False
        )
        db.add(borrower_notif)
        db.commit()
        db.refresh(req)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update borrow request due to a database error."
        )

    refreshed = (
        db.query(BorrowRequest)
        .options(
            joinedload(BorrowRequest.borrower),
            joinedload(BorrowRequest.listing).joinedload(Listing.owner)
        )
        .filter(BorrowRequest.id == req.id)
        .first()
    )
    return refreshed or req


# ==============================================================================
# 6. SUBMIT A BORROW REQUEST (AUTHENTICATED STUDENT)
# ==============================================================================
@router.post(
    "/{listing_id}/requests",
    response_model=BorrowRequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a borrow request",
    description="Submits a request to borrow an active peer borrow listing. Prevents requesting own listings, inactive listings, or duplicate active requests."
)
def create_borrow_request(
    listing_id: int,
    payload: Optional[BorrowRequestCreate] = None,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    listing = (
        db.query(Listing)
        .options(joinedload(Listing.owner))
        .filter(Listing.id == listing_id)
        .first()
    )

    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Listing with ID {listing_id} not found."
        )

    if listing.listing_type != "borrow":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This listing is not a peer borrow listing and cannot be requested for borrowing."
        )

    if listing.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot request listing with status '{listing.status}'. Only active listings can be requested."
        )

    if listing.student_id == current_student.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot request to borrow your own listing."
        )

    # Check for duplicate active request (pending or approved)
    existing_active = (
        db.query(BorrowRequest)
        .filter(
            BorrowRequest.listing_id == listing_id,
            BorrowRequest.borrower_id == current_student.id,
            BorrowRequest.status.in_(["pending", "approved"])
        )
        .first()
    )
    if existing_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have an active ({existing_active.status}) borrow request for this item."
        )

    req_note = payload.note.strip() if (payload and payload.note) else None
    new_req = BorrowRequest(
        listing_id=listing_id,
        borrower_id=current_student.id,
        status="pending",
        note=req_note
    )

    try:
        db.add(new_req)
        db.flush()

        # Create in-app notification for the listing owner
        owner_notif = Notification(
            student_id=listing.student_id,
            notification_type="borrow_request",
            title=f"New Borrow Request: {listing.title}",
            content=f"{current_student.full_name} has requested to borrow your item '{listing.title}'.",
            listing_id=listing.id,
            borrow_request_id=new_req.id,
            is_read=False
        )
        db.add(owner_notif)
        db.commit()
        db.refresh(new_req)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit borrow request due to a database error."
        )

    refreshed = (
        db.query(BorrowRequest)
        .options(
            joinedload(BorrowRequest.borrower),
            joinedload(BorrowRequest.listing).joinedload(Listing.owner)
        )
        .filter(BorrowRequest.id == new_req.id)
        .first()
    )
    return refreshed or new_req


# ==============================================================================
# 7. GET SINGLE BORROW LISTING
# ==============================================================================
@router.get(
    "/{listing_id}",
    response_model=ListingOut,
    status_code=status.HTTP_200_OK,
    summary="Get peer borrow listing by ID",
    description="Returns details of a single peer borrow listing."
)
def get_borrow_listing_by_id(
    listing_id: int,
    db: Session = Depends(get_db)
):
    listing = (
        db.query(Listing)
        .options(joinedload(Listing.owner))
        .filter(
            Listing.id == listing_id,
            Listing.listing_type == "borrow"
        )
        .first()
    )

    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Borrow listing with ID {listing_id} not found."
        )

    return listing


# ==============================================================================
# 4. CREATE PEER BORROW LISTING (PROTECTED)
# ==============================================================================
@router.post(
    "",
    response_model=ListingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a peer borrow listing",
    description="Creates a new peer borrow listing for the authenticated student. Price is automatically set to 0.00 INR."
)
def create_borrow_listing(
    payload: BorrowListingCreate,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    new_listing = Listing(
        student_id=current_student.id,
        listing_type="borrow",
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        category=payload.category.strip() if payload.category else "Others",
        price=Decimal("0.00"),  # Peer borrowing is free
        location=payload.location.strip(),
        image_url=payload.image_url.strip() if payload.image_url else None,
        condition=payload.condition.strip() if payload.condition else "Good",
        available_till=payload.available_till,
        status="active"
    )

    try:
        db.add(new_listing)
        db.commit()
        db.refresh(new_listing)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create borrow listing due to a database error."
        )

    refreshed = (
        db.query(Listing)
        .options(joinedload(Listing.owner))
        .filter(Listing.id == new_listing.id)
        .first()
    )
    return refreshed or new_listing


# ==============================================================================
# 5. UPDATE PEER BORROW LISTING (PROTECTED - OWNER ONLY)
# ==============================================================================
@router.put(
    "/{listing_id}",
    response_model=ListingOut,
    status_code=status.HTTP_200_OK,
    summary="Update peer borrow listing",
    description="Updates an existing borrow listing. Only the verified owner who created the listing can update it."
)
def update_borrow_listing(
    listing_id: int,
    payload: BorrowListingUpdate,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    listing = (
        db.query(Listing)
        .filter(
            Listing.id == listing_id,
            Listing.listing_type == "borrow"
        )
        .first()
    )

    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Borrow listing with ID {listing_id} not found."
        )

    # Ownership enforcement
    if listing.student_id != current_student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this listing."
        )

    update_dict = payload.model_dump(exclude_unset=True)

    # Validate status transitions if requested
    if "status" in update_dict and update_dict["status"]:
        valid_statuses = {"active", "borrowed", "archived"}
        status_clean = update_dict["status"].strip().lower()
        if status_clean not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{update_dict['status']}'. Allowed statuses: {', '.join(sorted(valid_statuses))}"
            )
        update_dict["status"] = status_clean

    for field, val in update_dict.items():
        if isinstance(val, str):
            val = val.strip()
        setattr(listing, field, val)

    try:
        db.commit()
        db.refresh(listing)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update borrow listing due to a database error."
        )

    refreshed = (
        db.query(Listing)
        .options(joinedload(Listing.owner))
        .filter(Listing.id == listing.id)
        .first()
    )
    return refreshed or listing


# ==============================================================================
# 6. DELETE PEER BORROW LISTING (PROTECTED - OWNER ONLY)
# ==============================================================================
@router.delete(
    "/{listing_id}",
    response_model=ListingActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete peer borrow listing",
    description="Deletes a peer borrow listing. Only the verified owner can delete their listing."
)
def delete_borrow_listing(
    listing_id: int,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    listing = (
        db.query(Listing)
        .filter(
            Listing.id == listing_id,
            Listing.listing_type == "borrow"
        )
        .first()
    )

    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Borrow listing with ID {listing_id} not found."
        )

    # Ownership enforcement
    if listing.student_id != current_student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this listing."
        )

    try:
        db.delete(listing)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete borrow listing due to a database error."
        )

    return ListingActionResponse(
        message="Borrow listing deleted successfully.",
        id=listing_id
    )
