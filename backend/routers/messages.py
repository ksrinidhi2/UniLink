"""
messages.py
===========
Direct Messaging API endpoints for UniLink:
- GET /messages/conversations: List all active 1-on-1 conversations for the authenticated student.
- GET /messages/conversations/{other_student_id}: Retrieve paginated chat history with a specific student.
- POST /messages: Send a message to another student (sender derived from Bearer JWT).
- PUT /messages/conversations/{other_student_id}/read: Mark all received messages in a conversation as read.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, desc, func

try:
    from backend.database import get_db
    from backend.models import Message, Student, Listing, Notification
    from backend.schemas import (
        MessageCreate,
        MessageOut,
        ConversationSummary,
        MessageMarkReadResponse,
        StudentBrief,
    )
    from backend.dependencies import get_current_student
except ImportError:
    from database import get_db
    from models import Message, Student, Listing, Notification
    from schemas import (
        MessageCreate,
        MessageOut,
        ConversationSummary,
        MessageMarkReadResponse,
        StudentBrief,
    )
    from dependencies import get_current_student

router = APIRouter(prefix="/messages", tags=["Messaging"])


# ==============================================================================
# 1. LIST CONVERSATIONS (INBOX)
# ==============================================================================
@router.get(
    "/conversations",
    response_model=List[ConversationSummary],
    status_code=status.HTTP_200_OK,
    summary="List student's conversations",
    description="Returns a list of conversation summaries for the authenticated student, including the other student profile, last message, and unread count."
)
def get_conversations(
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    # Find all messages where the current student is either sender or receiver
    messages = (
        db.query(Message)
        .options(
            joinedload(Message.sender),
            joinedload(Message.receiver)
        )
        .filter(
            or_(
                Message.sender_id == current_student.id,
                Message.receiver_id == current_student.id
            )
        )
        .order_by(desc(Message.created_at))
        .all()
    )

    # Group messages by the other participant's ID
    conversations_map = {}
    unread_counts = {}

    for msg in messages:
        # Determine the other participant
        other_id = msg.receiver_id if msg.sender_id == current_student.id else msg.sender_id
        if other_id is None:
            continue

        # Tally unread count: received by current student and unread
        if msg.receiver_id == current_student.id and not msg.is_read:
            unread_counts[other_id] = unread_counts.get(other_id, 0) + 1

        # Track latest message per other student
        if other_id not in conversations_map:
            conversations_map[other_id] = msg

    # Resolve student entities for other participants
    if not conversations_map:
        return []

    other_student_ids = list(conversations_map.keys())
    students_by_id = {
        s.id: s
        for s in db.query(Student).filter(Student.id.in_(other_student_ids)).all()
    }

    result = []
    for other_id, latest_msg in conversations_map.items():
        other_student = students_by_id.get(other_id)
        if not other_student:
            continue

        result.append(
            ConversationSummary(
                other_student=StudentBrief.model_validate(other_student),
                last_message=MessageOut.model_validate(latest_msg),
                unread_count=unread_counts.get(other_id, 0),
                listing_id=latest_msg.listing_id
            )
        )

    # Sort conversations by latest message timestamp descending
    result.sort(key=lambda c: c.last_message.created_at, reverse=True)
    return result


# ==============================================================================
# 2. GET CONVERSATION MESSAGE HISTORY
# ==============================================================================
@router.get(
    "/conversations/{other_student_id}",
    response_model=List[MessageOut],
    status_code=status.HTTP_200_OK,
    summary="Get conversation history",
    description="Returns chronological message history between the authenticated student and the specified student. Supports pagination."
)
def get_conversation_history(
    other_student_id: int,
    skip: int = Query(0, ge=0, description="Number of messages to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum messages to retrieve"),
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    if other_student_id == current_student.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot open a conversation with yourself"
        )

    # Validate that other student exists
    other_student = db.query(Student).filter(Student.id == other_student_id).first()
    if not other_student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {other_student_id} was not found"
        )

    # Query messages between the two participants only
    messages = (
        db.query(Message)
        .options(
            joinedload(Message.sender),
            joinedload(Message.receiver)
        )
        .filter(
            or_(
                and_(Message.sender_id == current_student.id, Message.receiver_id == other_student_id),
                and_(Message.sender_id == other_student_id, Message.receiver_id == current_student.id)
            )
        )
        .order_by(Message.created_at.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return messages


# ==============================================================================
# 3. SEND A MESSAGE
# ==============================================================================
@router.post(
    "",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message",
    description="Sends a direct message to another student. Automatically generates an in-app notification for the recipient."
)
def send_message(
    payload: MessageCreate,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    # Rule 1: Cannot message oneself
    if payload.receiver_id == current_student.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot send a message to yourself"
        )

    # Rule 2: Ensure receiver exists
    receiver = db.query(Student).filter(Student.id == payload.receiver_id).first()
    if not receiver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipient student with ID {payload.receiver_id} was not found"
        )

    # Rule 3: If listing_id is provided, verify listing exists
    if payload.listing_id is not None:
        listing = db.query(Listing).filter(Listing.id == payload.listing_id).first()
        if not listing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Listing with ID {payload.listing_id} was not found"
            )

    try:
        # Create message
        new_msg = Message(
            sender_id=current_student.id,
            receiver_id=payload.receiver_id,
            listing_id=payload.listing_id,
            content=payload.content.strip(),
            is_read=False
        )
        db.add(new_msg)

        # Create automatic in-app notification for the receiver
        notification = Notification(
            student_id=payload.receiver_id,
            notification_type="message",
            title=f"New message from {current_student.full_name}",
            content=payload.content.strip()[:200],
            listing_id=payload.listing_id,
            is_read=False
        )
        db.add(notification)

        db.commit()
        db.refresh(new_msg)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send message"
        )

    # Re-query with sender and receiver loaded
    refreshed = (
        db.query(Message)
        .options(
            joinedload(Message.sender),
            joinedload(Message.receiver)
        )
        .filter(Message.id == new_msg.id)
        .first()
    )

    return refreshed


# ==============================================================================
# 4. MARK CONVERSATION AS READ
# ==============================================================================
@router.put(
    "/conversations/{other_student_id}/read",
    response_model=MessageMarkReadResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark conversation as read",
    description="Marks all unread messages received from the specified student as read for the authenticated student."
)
def mark_conversation_as_read(
    other_student_id: int,
    current_student: Student = Depends(get_current_student),
    db: Session = Depends(get_db)
):
    try:
        updated_count = (
            db.query(Message)
            .filter(
                Message.sender_id == other_student_id,
                Message.receiver_id == current_student.id,
                Message.is_read == False
            )
            .update({"is_read": True}, synchronize_session=False)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark messages as read"
        )

    return MessageMarkReadResponse(
        message="Conversation marked as read",
        marked_count=updated_count
    )
