"""
saved_items.py
==============
Saved Items (Bookmarks) API endpoints for UniLink:
- GET /saved-items: Retrieve the authenticated student's saved listings (marketplace and borrow).
- POST /saved-items/{listing_id}: Save a listing to bookmarks (prevents duplicates).
- DELETE /saved-items/{listing_id}: Remove a listing from bookmarks.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

try:
    from backend.database import get_db
    from backend.models import Listing, SavedItem, Student
    from backend.schemas import (
        SavedItemOut,
        SavedItemActionResponse,
    )
    from backend.dependencies import get_current_student, require_non_demo_mutation
except ImportError:
    from database import get_db
    from models import Listing, SavedItem, Student
    from schemas import (
        SavedItemOut,
        SavedItemActionResponse,
    )
    from dependencies import get_current_student, require_non_demo_mutation

router = APIRouter(prefix="/saved-items", tags=["Saved Items"])


# ==============================================================================
# 1. GET AUTHENTICATED STUDENT'S SAVED ITEMS
# ==============================================================================
@router.get(
    "",
    response_model=List[SavedItemOut],
    status_code=status.HTTP_200_OK,
    summary="Get authenticated student's saved items",
    description="Returns all bookmarks saved by the authenticated student, including full listing details and whether each item is Marketplace or Borrow."
)
def get_saved_items(
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    saved_items = (
        db.query(SavedItem)
        .options(
            joinedload(SavedItem.listing).joinedload(Listing.owner)
        )
        .filter(SavedItem.student_id == current_student.id)
        .order_by(SavedItem.created_at.desc())
        .all()
    )
    return saved_items


# ==============================================================================
# 2. SAVE A LISTING (BOOKMARK)
# ==============================================================================
@router.post(
    "/{listing_id}",
    response_model=SavedItemOut,
    status_code=status.HTTP_201_CREATED,
    summary="Save a listing",
    description="Saves a marketplace or borrow listing for the authenticated student. Prevents duplicate saves."
)
def save_item(
    listing_id: int,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    # Verify that listing exists
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

    # Check for existing save
    existing = (
        db.query(SavedItem)
        .filter(
            SavedItem.student_id == current_student.id,
            SavedItem.listing_id == listing_id
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Listing is already in your saved items list."
        )

    new_saved = SavedItem(
        student_id=current_student.id,
        listing_id=listing_id
    )

    try:
        db.add(new_saved)
        db.commit()
        db.refresh(new_saved)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save item due to a database error."
        )

    refreshed = (
        db.query(SavedItem)
        .options(
            joinedload(SavedItem.listing).joinedload(Listing.owner)
        )
        .filter(SavedItem.id == new_saved.id)
        .first()
    )
    return refreshed or new_saved


# ==============================================================================
# 3. REMOVE A SAVED LISTING (UNSAVE)
# ==============================================================================
@router.delete(
    "/{listing_id}",
    response_model=SavedItemActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove a saved listing",
    description="Removes a listing from the authenticated student's saved items."
)
def remove_saved_item(
    listing_id: int,
    current_student: Student = Depends(require_non_demo_mutation),
    db: Session = Depends(get_db)
):
    require_non_demo_mutation(current_student)
    saved = (
        db.query(SavedItem)
        .filter(
            SavedItem.student_id == current_student.id,
            SavedItem.listing_id == listing_id
        )
        .first()
    )
    if not saved:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Listing is not in your saved items list."
        )

    try:
        db.delete(saved)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove saved item due to a database error."
        )

    return SavedItemActionResponse(
        message="Item removed from saved items.",
        listing_id=listing_id,
        is_saved=False
    )
