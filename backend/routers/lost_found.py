"""
lost_found.py
=============
Lost & Found API endpoints for UniLink:
- GET /lost-found: Browse open lost & found campus reports with search and type filters.
- GET /lost-found/me: Retrieve reports created by the authenticated student.
- GET /lost-found/{report_id}: View single report details (including claims if permitted).
- POST /lost-found: Create a lost or found report (authenticated student).
- PUT /lost-found/{report_id}: Edit a report (report reporter only).
- DELETE /lost-found/{report_id}: Delete a report (report reporter only).
- POST /lost-found/{report_id}/claims: Submit an ownership claim or found match notice.
- GET /lost-found/{report_id}/claims: Retrieve all claims for a report (report reporter only).
- PUT /lost-found/{report_id}/claims/{claim_id}: Review claim approval/rejection (report reporter only).
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

try:
    from backend.database import get_db
    from backend.models import LostFoundReport, LostFoundClaim, Student, Notification
    from backend.schemas import (
        LostFoundReportCreate,
        LostFoundReportUpdate,
        LostFoundReportOut,
        LostFoundClaimCreate,
        LostFoundClaimReview,
        LostFoundClaimOut,
        LostFoundActionResponse,
    )
    from backend.dependencies import get_current_student
except ImportError:
    from database import get_db
    from models import LostFoundReport, LostFoundClaim, Student, Notification
    from schemas import (
        LostFoundReportCreate,
        LostFoundReportUpdate,
        LostFoundReportOut,
        LostFoundClaimCreate,
        LostFoundClaimReview,
        LostFoundClaimOut,
        LostFoundActionResponse,
    )
    from dependencies import get_current_student

router = APIRouter(prefix="/lost-found", tags=["Lost & Found"])


# ==============================================================================
# HELPER: Map report model to LostFoundReportOut with claims count
# ==============================================================================
def format_report_out(report: LostFoundReport, include_claims: bool = False) -> LostFoundReportOut:
    claims_list = None
    claims_count = 0
    if hasattr(report, "claims") and report.claims is not None:
        claims_count = len(report.claims)
        if include_claims:
            claims_list = [LostFoundClaimOut.model_validate(c) for c in report.claims]

    return LostFoundReportOut(
        id=report.id,
        student_id=report.student_id,
        report_type=report.report_type,
        title=report.title,
        description=report.description,
        location=report.location,
        image_url=report.image_url,
        status=report.status,
        created_at=report.created_at,
        reporter=report.reporter,
        claims_count=claims_count,
        claims=claims_list,
    )


# ==============================================================================
# 1. BROWSE LOST & FOUND REPORTS
# ==============================================================================
@router.get(
    "",
    response_model=List[LostFoundReportOut],
    status_code=status.HTTP_200_OK,
    summary="Browse Lost & Found reports",
    description="Returns open Lost & Found reports. Supports optional search keywords, report_type ('lost' or 'found'), location filter, and pagination."
)
def get_lost_found_reports(
    q: Optional[str] = Query(None, description="Search keyword in title, description, or location"),
    report_type: Optional[str] = Query(None, description="Filter by 'lost' or 'found'"),
    location: Optional[str] = Query(None, description="Filter by location substring"),
    status_filter: Optional[str] = Query("open", alias="status", description="Status filter: 'open', 'claimed', 'resolved', or 'all'"),
    skip: int = Query(0, ge=0, description="Number of reports to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of reports to return"),
    db: Session = Depends(get_db)
):
    query = (
        db.query(LostFoundReport)
        .options(
            joinedload(LostFoundReport.reporter),
            joinedload(LostFoundReport.claims)
        )
    )

    # Status filter: default 'open', or explicit, or 'all'
    if status_filter and status_filter.lower() != "all":
        query = query.filter(LostFoundReport.status == status_filter.lower())

    # Report type filter: 'lost' or 'found'
    if report_type:
        query = query.filter(LostFoundReport.report_type == report_type.strip().lower())

    # Location filter
    if location:
        query = query.filter(LostFoundReport.location.ilike(f"%{location.strip()}%"))

    # Search keyword
    if q:
        search_pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(
                LostFoundReport.title.ilike(search_pattern),
                LostFoundReport.description.ilike(search_pattern),
                LostFoundReport.location.ilike(search_pattern)
            )
        )

    reports = (
        query.order_by(LostFoundReport.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [format_report_out(r) for r in reports]


# ==============================================================================
# 2. RETRIEVE CURRENT STUDENT'S REPORTS
# ==============================================================================
@router.get(
    "/me",
    response_model=List[LostFoundReportOut],
    status_code=status.HTTP_200_OK,
    summary="Retrieve current student's Lost & Found reports",
    description="Returns all Lost & Found reports submitted by the authenticated student, including full claim details."
)
def get_my_lost_found_reports(
    skip: int = Query(0, ge=0, description="Number of reports to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of reports to return"),
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    reports = (
        db.query(LostFoundReport)
        .options(
            joinedload(LostFoundReport.reporter),
            joinedload(LostFoundReport.claims).joinedload(LostFoundClaim.claimant)
        )
        .filter(LostFoundReport.student_id == current_student.id)
        .order_by(LostFoundReport.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    # Reporter can see claims for their own reports
    return [format_report_out(r, include_claims=True) for r in reports]


# ==============================================================================
# 3. GET SINGLE REPORT DETAILS
# ==============================================================================
@router.get(
    "/{report_id}",
    response_model=LostFoundReportOut,
    status_code=status.HTTP_200_OK,
    summary="Get single Lost & Found report details",
    description="Returns detailed information for a specific report. If requested by the reporter, claims are included."
)
def get_lost_found_report(
    report_id: int,
    db: Session = Depends(get_db)
):
    report = (
        db.query(LostFoundReport)
        .options(
            joinedload(LostFoundReport.reporter),
            joinedload(LostFoundReport.claims).joinedload(LostFoundClaim.claimant)
        )
        .filter(LostFoundReport.id == report_id)
        .first()
    )

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lost & Found report with ID {report_id} was not found"
        )

    return format_report_out(report, include_claims=True)


# ==============================================================================
# 4. CREATE LOST & FOUND REPORT
# ==============================================================================
@router.post(
    "",
    response_model=LostFoundReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a Lost & Found report",
    description="Creates a new Lost or Found report for the authenticated student. Reporter ownership is assigned automatically from Bearer JWT."
)
def create_lost_found_report(
    payload: LostFoundReportCreate,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    new_report = LostFoundReport(
        student_id=current_student.id,
        report_type=payload.report_type.strip().lower(),
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        location=payload.location.strip(),
        image_url=payload.image_url.strip() if payload.image_url else None,
        status="open",
    )

    db.add(new_report)
    db.commit()
    db.refresh(new_report)

    # Re-query with reporter eagerly loaded
    refreshed = (
        db.query(LostFoundReport)
        .options(
            joinedload(LostFoundReport.reporter),
            joinedload(LostFoundReport.claims)
        )
        .filter(LostFoundReport.id == new_report.id)
        .first()
    )

    return format_report_out(refreshed)


# ==============================================================================
# 5. UPDATE AN OWNED LOST & FOUND REPORT
# ==============================================================================
@router.put(
    "/{report_id}",
    response_model=LostFoundReportOut,
    status_code=status.HTTP_200_OK,
    summary="Update an owned Lost & Found report",
    description="Updates title, description, location, image, or status of an existing report. Only the original reporter can update."
)
def update_lost_found_report(
    report_id: int,
    payload: LostFoundReportUpdate,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    report = (
        db.query(LostFoundReport)
        .options(
            joinedload(LostFoundReport.reporter),
            joinedload(LostFoundReport.claims)
        )
        .filter(LostFoundReport.id == report_id)
        .first()
    )

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report with ID {report_id} was not found"
        )

    # Ownership check
    if report.student_id != current_student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to edit this report"
        )

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            if isinstance(value, str):
                setattr(report, key, value.strip().lower() if key == "status" else value.strip())
            else:
                setattr(report, key, value)

    db.commit()
    db.refresh(report)

    return format_report_out(report, include_claims=True)


# ==============================================================================
# 6. DELETE AN OWNED LOST & FOUND REPORT
# ==============================================================================
@router.delete(
    "/{report_id}",
    response_model=LostFoundActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete an owned Lost & Found report",
    description="Permanently removes a report and its associated claims. Only the original reporter can delete."
)
def delete_lost_found_report(
    report_id: int,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    report = db.query(LostFoundReport).filter(LostFoundReport.id == report_id).first()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report with ID {report_id} was not found"
        )

    if report.student_id != current_student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to delete this report"
        )

    db.delete(report)
    db.commit()

    return LostFoundActionResponse(
        message="Lost & Found report deleted successfully",
        id=report_id
    )


# ==============================================================================
# 7. SUBMIT A CLAIM OR FOUND MATCH NOTICE
# ==============================================================================
@router.post(
    "/{report_id}/claims",
    response_model=LostFoundClaimOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a claim or found match notice",
    description="Submits an ownership claim (for found items) or found match notice (for lost items). Claimant cannot be the report reporter. Duplicate active claims are prohibited."
)
def submit_claim(
    report_id: int,
    payload: LostFoundClaimCreate,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    report = db.query(LostFoundReport).filter(LostFoundReport.id == report_id).first()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report with ID {report_id} was not found"
        )

    # Rule 1: A student cannot claim their own report
    if report.student_id == current_student.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot submit a claim or found match on your own report"
        )

    # Rule 2: Cannot claim a report that is already resolved
    if report.status == "resolved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This report has already been resolved and is no longer accepting claims"
        )

    # Rule 3: Check for existing active claims (status in pending, approved)
    existing_active = (
        db.query(LostFoundClaim)
        .filter(
            LostFoundClaim.report_id == report_id,
            LostFoundClaim.claimant_id == current_student.id,
            LostFoundClaim.status.in_(["pending", "approved"])
        )
        .first()
    )
    if existing_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have an active claim ({existing_active.status}) on this item"
        )

    # Determine default claim_type based on report_type if not explicitly set
    claim_type = payload.claim_type or ("ownership_claim" if report.report_type == "found" else "found_match")

    new_claim = LostFoundClaim(
        report_id=report_id,
        claimant_id=current_student.id,
        claim_type=claim_type,
        proof_details=payload.proof_details.strip() if payload.proof_details else None,
        status="pending"
    )

    try:
        db.add(new_claim)
        db.commit()
        db.refresh(new_claim)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active claim on this report already exists for your account"
        )

    # Re-query with claimant relation loaded
    refreshed_claim = (
        db.query(LostFoundClaim)
        .options(joinedload(LostFoundClaim.claimant))
        .filter(LostFoundClaim.id == new_claim.id)
        .first()
    )

    return refreshed_claim


# ==============================================================================
# 8. RETRIEVE ALL CLAIMS FOR A REPORT (REPORTER ONLY)
# ==============================================================================
@router.get(
    "/{report_id}/claims",
    response_model=List[LostFoundClaimOut],
    status_code=status.HTTP_200_OK,
    summary="Get claims for a report",
    description="Returns all submitted claims for a report. Restricted strictly to the student who reported the item."
)
def get_report_claims(
    report_id: int,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    report = db.query(LostFoundReport).filter(LostFoundReport.id == report_id).first()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report with ID {report_id} was not found"
        )

    if report.student_id != current_student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the student who reported this item can view all claims"
        )

    claims = (
        db.query(LostFoundClaim)
        .options(joinedload(LostFoundClaim.claimant))
        .filter(LostFoundClaim.report_id == report_id)
        .order_by(LostFoundClaim.created_at.desc())
        .all()
    )

    return claims


# ==============================================================================
# 9. REVIEW / UPDATE CLAIM STATUS (REPORTER ONLY)
# ==============================================================================
@router.put(
    "/{report_id}/claims/{claim_id}",
    response_model=LostFoundClaimOut,
    status_code=status.HTTP_200_OK,
    summary="Review claim status (Approve or Reject)",
    description="Approves or rejects a submitted claim. Only the report owner can review claims. Approving updates report status to 'claimed'."
)
def review_claim(
    report_id: int,
    claim_id: int,
    payload: LostFoundClaimReview,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    report = db.query(LostFoundReport).filter(LostFoundReport.id == report_id).first()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report with ID {report_id} was not found"
        )

    # Ownership check
    if report.student_id != current_student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the student who posted this report can review claims"
        )

    claim = (
        db.query(LostFoundClaim)
        .options(joinedload(LostFoundClaim.claimant))
        .filter(
            LostFoundClaim.id == claim_id,
            LostFoundClaim.report_id == report_id
        )
        .first()
    )

    if not claim:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim with ID {claim_id} was not found on this report"
        )

    new_status = payload.status.strip().lower()
    claim.status = new_status

    # If claim approved, update the report status to 'claimed'
    if new_status == "approved":
        report.status = "claimed"

    # Automatically notify claimant of claim review outcome
    status_label = "approved" if new_status == "approved" else "rejected"
    notification = Notification(
        student_id=claim.claimant_id,
        notification_type="claim_update",
        title=f"Claim {status_label}: {report.title}",
        content=f"Your claim on '{report.title}' has been {status_label} by the reporter.",
        lost_found_report_id=report.id,
        is_read=False
    )
    db.add(notification)

    db.commit()
    db.refresh(claim)

    return claim
