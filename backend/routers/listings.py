"""
listings.py
===========
Marketplace Listing API endpoints for UniLink:
- GET /listings: Browse active marketplace listings with keyword and category filters.
- GET /listings/me: Retrieve current student's marketplace listings.
- GET /listings/{listing_id}: View single marketplace listing details.
- POST /listings: Create a new marketplace listing (authenticated student).
- PUT /listings/{listing_id}: Update an owned marketplace listing (authenticated owner only).
- DELETE /listings/{listing_id}: Delete an owned marketplace listing (authenticated owner only).
"""

from typing import List, Optional
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

try:
    from backend.database import get_db
    from backend.models import Listing, Student
    from backend.schemas import (
        ListingCreate,
        ListingUpdate,
        ListingOut,
        ListingActionResponse,
    )
    from backend.dependencies import get_current_student
except ImportError:
    from database import get_db
    from models import Listing, Student
    from schemas import (
        ListingCreate,
        ListingUpdate,
        ListingOut,
        ListingActionResponse,
    )
    from dependencies import get_current_student

router = APIRouter(prefix="/listings", tags=["Marketplace Listings"])


# ==============================================================================
# 1. BROWSE ACTIVE MARKETPLACE LISTINGS
# ==============================================================================
@router.get(
    "",
    response_model=List[ListingOut],
    status_code=status.HTTP_200_OK,
    summary="Browse active marketplace listings",
    description="Returns active marketplace listings. Supports optional search keywords, category filtering, price ranges, and pagination."
)
def get_marketplace_listings(
    q: Optional[str] = Query(None, description="Search keyword in title, description, or location"),
    category: Optional[str] = Query(None, description="Category filter (e.g. Electronics, Books, Clothing)"),
    min_price: Optional[Decimal] = Query(None, ge=Decimal("0.00"), description="Minimum price filter in INR"),
    max_price: Optional[Decimal] = Query(None, ge=Decimal("0.00"), description="Maximum price filter in INR"),
    skip: int = Query(0, ge=0, description="Number of listings to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of listings to return"),
    db: Session = Depends(get_db)
):
    query = (
        db.query(Listing)
        .options(joinedload(Listing.owner))
        .filter(
            Listing.listing_type == "marketplace",
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

    # Optional price range filters
    if min_price is not None:
        query = query.filter(Listing.price >= min_price)
    if max_price is not None:
        query = query.filter(Listing.price <= max_price)

    listings = query.order_by(Listing.created_at.desc()).offset(skip).limit(limit).all()
    return listings


# ==============================================================================
# 2. CURRENT STUDENT'S MARKETPLACE LISTINGS
# ==============================================================================
@router.get(
    "/me",
    response_model=List[ListingOut],
    status_code=status.HTTP_200_OK,
    summary="Get current student's marketplace listings",
    description="Returns all marketplace listings created by the currently authenticated student."
)
def get_my_marketplace_listings(
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    listings = (
        db.query(Listing)
        .options(joinedload(Listing.owner))
        .filter(
            Listing.listing_type == "marketplace",
            Listing.student_id == current_student.id
        )
        .order_by(Listing.created_at.desc())
        .all()
    )
    return listings


# ==============================================================================
# 3. GET SINGLE MARKETPLACE LISTING
# ==============================================================================
@router.get(
    "/{listing_id}",
    response_model=ListingOut,
    status_code=status.HTTP_200_OK,
    summary="Get marketplace listing by ID",
    description="Returns details of a single marketplace listing."
)
def get_marketplace_listing_by_id(
    listing_id: int,
    db: Session = Depends(get_db)
):
    listing = (
        db.query(Listing)
        .options(joinedload(Listing.owner))
        .filter(
            Listing.id == listing_id,
            Listing.listing_type == "marketplace"
        )
        .first()
    )

    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Marketplace listing with ID {listing_id} not found."
        )

    return listing


# ==============================================================================
# 4. CREATE MARKETPLACE LISTING (PROTECTED)
# ==============================================================================
@router.post(
    "",
    response_model=ListingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a marketplace listing",
    description="Creates a new Marketplace listing for the authenticated student. Ownership is strictly bound to the authenticated user."
)
def create_marketplace_listing(
    payload: ListingCreate,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    new_listing = Listing(
        student_id=current_student.id,
        listing_type="marketplace",
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        category=payload.category.strip(),
        price=payload.price,
        location=payload.location.strip(),
        image_url=payload.image_url.strip() if payload.image_url else None,
        condition=payload.condition.strip() if payload.condition else "Good",
        available_till=None,
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
            detail="Failed to create marketplace listing due to a database error."
        )

    # Re-fetch with eager loaded owner relationship
    refreshed = (
        db.query(Listing)
        .options(joinedload(Listing.owner))
        .filter(Listing.id == new_listing.id)
        .first()
    )
    return refreshed or new_listing


# ==============================================================================
# 5. UPDATE MARKETPLACE LISTING (PROTECTED - OWNER ONLY)
# ==============================================================================
@router.put(
    "/{listing_id}",
    response_model=ListingOut,
    status_code=status.HTTP_200_OK,
    summary="Update marketplace listing",
    description="Updates an existing marketplace listing. Only the verified owner who created the listing can update it."
)
def update_marketplace_listing(
    listing_id: int,
    payload: ListingUpdate,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    listing = (
        db.query(Listing)
        .filter(
            Listing.id == listing_id,
            Listing.listing_type == "marketplace"
        )
        .first()
    )

    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Marketplace listing with ID {listing_id} not found."
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
        valid_statuses = {"active", "sold", "archived"}
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
            detail="Failed to update marketplace listing due to a database error."
        )

    refreshed = (
        db.query(Listing)
        .options(joinedload(Listing.owner))
        .filter(Listing.id == listing.id)
        .first()
    )
    return refreshed or listing


# ==============================================================================
# 6. DELETE MARKETPLACE LISTING (PROTECTED - OWNER ONLY)
# ==============================================================================
@router.delete(
    "/{listing_id}",
    response_model=ListingActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete marketplace listing",
    description="Deletes a marketplace listing. Only the verified owner can delete their listing."
)
def delete_marketplace_listing(
    listing_id: int,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    listing = (
        db.query(Listing)
        .filter(
            Listing.id == listing_id,
            Listing.listing_type == "marketplace"
        )
        .first()
    )

    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Marketplace listing with ID {listing_id} not found."
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
            detail="Failed to delete marketplace listing due to a database error."
        )

    return ListingActionResponse(
        message="Marketplace listing deleted successfully.",
        id=listing_id
    )
