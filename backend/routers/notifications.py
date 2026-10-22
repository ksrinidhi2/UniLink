"""
notifications.py
================
In-App Notifications API endpoints for UniLink:
- GET /notifications: Retrieve paginated notifications for the authenticated student with optional unread and category filters.
- PUT /notifications/{notification_id}/read: Mark a single notification as read (owned by authenticated student).
- PUT /notifications/read-all: Mark all notifications as read for the authenticated student.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

try:
    from backend.database import get_db
    from backend.models import Notification, Student
    from backend.schemas import (
        NotificationOut,
        NotificationMarkReadResponse,
    )
    from backend.dependencies import get_current_student
except ImportError:
    from database import get_db
    from models import Notification, Student
    from schemas import (
        NotificationOut,
        NotificationMarkReadResponse,
    )
    from dependencies import get_current_student

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# ==============================================================================
# 1. LIST NOTIFICATIONS
# ==============================================================================
@router.get(
    "",
    response_model=List[NotificationOut],
    status_code=status.HTTP_200_OK,
    summary="List student notifications",
    description="Returns notifications belonging strictly to the authenticated student. Supports filtering by unread status, notification type, and pagination."
)
def get_notifications(
    unread_only: bool = Query(False, description="Filter only unread notifications"),
    notification_type: Optional[str] = Query(None, description="Filter by type ('message', 'claim_update', 'borrow_request', 'item_update', 'system')"),
    skip: int = Query(0, ge=0, description="Number of notifications to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum notifications to return"),
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    query = db.query(Notification).filter(Notification.student_id == current_student.id)

    if unread_only:
        query = query.filter(Notification.is_read == False)

    if notification_type:
        query = query.filter(Notification.notification_type == notification_type.strip().lower())

    notifications = (
        query.order_by(desc(Notification.created_at))
        .offset(skip)
        .limit(limit)
        .all()
    )

    return notifications


# ==============================================================================
# 2. MARK ALL NOTIFICATIONS AS READ
# ==============================================================================
@router.put(
    "/read-all",
    response_model=NotificationMarkReadResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark all notifications as read",
    description="Marks all unread notifications belonging to the authenticated student as read."
)
def mark_all_notifications_as_read(
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    try:
        updated_count = (
            db.query(Notification)
            .filter(
                Notification.student_id == current_student.id,
                Notification.is_read == False
            )
            .update({"is_read": True}, synchronize_session=False)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark all notifications as read"
        )

    return NotificationMarkReadResponse(
        message="All notifications marked as read",
        marked_count=updated_count
    )


# ==============================================================================
# 3. MARK SINGLE NOTIFICATION AS READ
# ==============================================================================
@router.put(
    "/{notification_id}/read",
    response_model=NotificationMarkReadResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark single notification as read",
    description="Marks a specific notification as read. Restricted strictly to the student recipient."
)
def mark_notification_as_read(
    notification_id: int,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    notification = db.query(Notification).filter(Notification.id == notification_id).first()

    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification with ID {notification_id} was not found"
        )

    if notification.student_id != current_student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to update this notification"
        )

    notification.is_read = True
    db.commit()

    return NotificationMarkReadResponse(
        message="Notification marked as read",
        id=notification_id,
        marked_count=1
    )
