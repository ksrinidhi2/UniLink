"""
dependencies.py
===============
Reusable FastAPI dependencies for authentication and authorization.
Extracts and validates the Bearer JWT from incoming HTTP requests and
resolves the authenticated Student model from the database.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

try:
    from backend.database import get_db
    from backend.models import Student
    from backend.security import decode_access_token
except ImportError:
    from database import get_db
    from models import Student
    from security import decode_access_token

# OAuth2 scheme: expects Authorization header: Bearer <token>
# tokenUrl specifies the login endpoint for Swagger UI's "Authorize" modal
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_student(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Student:
    """
    Dependency that extracts, decodes, and validates the Bearer JWT token.
    - Validates signature and expiration timestamp.
    - Validates that the 'sub' claim parses to a valid positive student ID.
    - Loads the matching active student from PostgreSQL.
    - Rejects invalid or expired tokens with HTTP 401 Unauthorized.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        token_payload = decode_access_token(token)
    except ValueError as exc:
        # Raises HTTP 401 with sanitized error message (e.g. expired or invalid)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )

    student_id = token_payload.get("student_id")
    if not student_id or not isinstance(student_id, int) or student_id <= 0:
        raise credentials_exception

    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Student account not found or has been removed",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Attach session attributes
    student.is_demo_session = bool(token_payload.get("is_demo", False))

    return student


def require_non_demo_mutation(
    current_student: Student = Depends(get_current_student)
) -> Student:
    """
    Dependency guard that blocks destructive and state-altering mutations
    when invoked from a presentation demo session ('is_demo': True).
    Normal logged-in students pass through with zero restriction.
    """
    if getattr(current_student, "is_demo_session", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Modifications and deletions are disabled in Demo Presentation Mode to protect demo records."
        )
    return current_student

