"""
auth.py
=======
Authentication endpoints for UniLink:
- POST /auth/register: Student registration with domain validation & bcrypt hashing.
- POST /auth/login: Student authentication returning JWT access token & profile.
- GET /auth/me: Protected endpoint returning authenticated student profile.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

try:
    from backend.database import get_db
    from backend.models import Student
    from backend.schemas import (
        StudentRegister,
        StudentLogin,
        GoogleLoginRequest,
        TokenResponse,
        StudentOut,
        StudentUpdate,
    )
    from backend.security import (
        get_password_hash,
        verify_password,
        create_access_token,
        validate_campus_email_domain,
        verify_google_id_token,
    )
    from backend.dependencies import get_current_student, require_non_demo_mutation
except ImportError:
    from database import get_db
    from models import Student
    from schemas import (
        StudentRegister,
        StudentLogin,
        GoogleLoginRequest,
        TokenResponse,
        StudentOut,
        StudentUpdate,
    )
    from security import (
        get_password_hash,
        verify_password,
        create_access_token,
        validate_campus_email_domain,
        verify_google_id_token,
    )
    from dependencies import get_current_student, require_non_demo_mutation

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ==============================================================================
# 0. PUBLIC AUTH CONFIGURATION
# ==============================================================================
@router.get(
    "/config",
    summary="Get public authentication settings",
    description="Returns public non-sensitive authentication settings such as Google Client ID and allowed email domain."
)
def get_auth_config():
    try:
        from backend.config import GOOGLE_CLIENT_ID, ALLOWED_EMAIL_DOMAIN
    except ImportError:
        from config import GOOGLE_CLIENT_ID, ALLOWED_EMAIL_DOMAIN

    return {
        "google_client_id": GOOGLE_CLIENT_ID or "",
        "allowed_email_domain": ALLOWED_EMAIL_DOMAIN,
        "google_auth_enabled": bool(GOOGLE_CLIENT_ID)
    }


# ==============================================================================
# 1. REGISTER ENDPOINT
# ==============================================================================
@router.post(
    "/register",
    response_model=StudentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new student account",
    description="Registers a new verified-format student account. Enforces @vitapstudent.ac.in domain, hashes password, sets is_verified=False, and rejects duplicates with HTTP 409."
)
def register_student(payload: StudentRegister, db: Session = Depends(get_db)):
    # 1. Enforce campus domain policy check
    clean_email = payload.email.strip().lower()
    if not validate_campus_email_domain(clean_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration is restricted to official campus emails (@vitapstudent.ac.in, @vitap.ac.in)."
        )

    # 2. Check for duplicate email
    existing_email = db.query(Student).filter(Student.email == clean_email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this campus email already exists. Please log in instead."
        )

    # 3. Check for duplicate registration number if provided
    clean_reg_no = payload.reg_no.strip() if payload.reg_no else None
    if clean_reg_no:
        existing_reg = db.query(Student).filter(Student.reg_no == clean_reg_no).first()
        if existing_reg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this registration number already exists."
            )

    # 4. Hash the password safely using bcrypt
    try:
        hashed_pwd = get_password_hash(payload.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        )

    # 5. Create the Student record (is_verified is strictly False for manual signups)
    new_student = Student(
        full_name=payload.full_name.strip(),
        email=clean_email,
        hashed_password=hashed_pwd,
        reg_no=clean_reg_no,
        program=payload.program.strip() if payload.program else "B.Tech",
        year_of_study=payload.year_of_study.strip() if payload.year_of_study else "1st Year",
        avatar_index=payload.avatar_index,
        is_verified=False  # Security rule: Never trust client verification input
    )

    try:
        db.add(new_student)
        db.commit()
        db.refresh(new_student)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email or registration number already exists."
        )

    return new_student


# ==============================================================================
# 2. LOGIN ENDPOINT
# ==============================================================================
@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate student and obtain JWT",
    description="Authenticates student credentials. Returns a signed JWT access token and safe student profile on success, or generic HTTP 401 on failure."
)
def login_student(payload: StudentLogin, db: Session = Depends(get_db)):
    clean_email = payload.email.strip().lower()

    # Look up student by email
    student = db.query(Student).filter(Student.email == clean_email).first()

    # Constant-time password verification; generic error prevents account enumeration
    if not student or not verify_password(payload.password, student.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Generate short-lived signed JWT access token
    try:
        access_token = create_access_token(student_id=student.id, email=student.email)
    except RuntimeError as exc:
        # Catches unconfigured SECRET_KEY
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication configuration error. Please contact server administrator."
        )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        student=StudentOut.model_validate(student)
    )


# ==============================================================================
# 2.5. DEMO PRESENTATION ACCESS ENDPOINT
# ==============================================================================
@router.post(
    "/demo-session",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Access designated demo presentation account",
    description="Securely issues a signed JWT access token for Varshitha's demo account for presentation and evaluation purposes with is_demo protection."
)
def create_demo_session(db: Session = Depends(get_db)):
    """
    Presentation demo authentication endpoint:
    - Never trusts client-supplied student ID, email, or credentials.
    - Strictly resolves the fixed Varshitha demo account only.
    - Generates an authentic JWT signed with the server's internal SECRET_KEY.
    - Embeds 'is_demo': True in JWT claims to protect records from destructive modifications.
    """
    DEMO_EMAIL = "varshitha.25bca1234@vitapstudent.ac.in"
    student = db.query(Student).filter(Student.email == DEMO_EMAIL).first()

    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The demo presentation account has not been initialized in the database yet. Please ensure the production seeder has been executed."
        )

    try:
        access_token = create_access_token(
            student_id=student.id,
            email=student.email,
            is_demo=True
        )
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication configuration error. Please contact server administrator."
        )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        student=StudentOut.model_validate(student)
    )


# ==============================================================================
# 3. GOOGLE SIGN-IN ENDPOINT (Phase 8)
# ==============================================================================
@router.post(
    "/google",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate student using Google Identity Services ID token",
    description="Validates Google ID token cryptographically, verifies campus email policy (@vitapstudent.ac.in), creates account if not exists, and issues a UniLink JWT access token."
)
def google_sign_in(payload: GoogleLoginRequest, db: Session = Depends(get_db)):
    """
    Handles Google OAuth ID token verification and student login/creation:
    - Never trusts client-supplied email or verification flags.
    - Verifies token signature, aud, iss, exp, email, and email_verified via Google.
    - Enforces institutional domain policy (@vitapstudent.ac.in).
    - If student exists: signs in directly, sets is_verified=True (proven by Google login).
    - If student does not exist: creates new verified student record with random unusable password hash.
    - Returns UniLink JWT Bearer access token and safe student profile.
    """
    raw_token = payload.id_token.strip()
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google ID token is required."
        )

    # 1. Server-side verification using Google's official oauth2 library
    try:
        google_claims = verify_google_id_token(raw_token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc)
        )

    verified_email = google_claims["email"].strip().lower()
    full_name = google_claims.get("name") or google_claims.get("given_name") or "VIT-AP Student"

    # 2. Strict campus institutional domain enforcement
    if not validate_campus_email_domain(verified_email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted: Google account must belong to the approved campus domain (@vitapstudent.ac.in, @vitap.ac.in)."
        )

    # 3. Locate existing student by verified email
    student = db.query(Student).filter(Student.email == verified_email).first()

    if student:
        # Existing student: safely sign in and mark verified since proven by Google OAuth
        if not student.is_verified:
            student.is_verified = True
            db.commit()
            db.refresh(student)
    else:
        # New student account creation
        # Extract probable registration number if email follows pattern (e.g. name.25bca1234@...)
        extracted_reg_no = None
        try:
            local_part = verified_email.split("@")[0]
            if "." in local_part:
                candidate = local_part.split(".")[-1]
                if len(candidate) >= 5 and any(c.isdigit() for c in candidate):
                    extracted_reg_no = candidate
        except Exception:
            extracted_reg_no = None

        # Check if extracted_reg_no collides
        if extracted_reg_no:
            colliding = db.query(Student).filter(Student.reg_no == extracted_reg_no).first()
            if colliding:
                extracted_reg_no = None

        import secrets
        # Random unusable password hash so the student can only sign in via Google unless they set a password
        random_secret = secrets.token_urlsafe(32)
        hashed_pwd = get_password_hash(random_secret)

        student = Student(
            full_name=full_name.strip()[:100],
            email=verified_email,
            hashed_password=hashed_pwd,
            reg_no=extracted_reg_no,
            program="B.Tech",
            year_of_study="1st Year",
            avatar_index=0,
            is_verified=True  # Verified by Google OAuth
        )

        try:
            db.add(student)
            db.commit()
            db.refresh(student)
        except IntegrityError:
            db.rollback()
            # If a race condition occurred, re-query
            student = db.query(Student).filter(Student.email == verified_email).first()
            if not student:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Database conflict while creating student account."
                )

    # 4. Generate signed UniLink JWT token
    try:
        access_token = create_access_token(student_id=student.id, email=student.email)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication configuration error. Please contact server administrator."
        )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        student=StudentOut.model_validate(student)
    )


# ==============================================================================
# 4. GET CURRENT STUDENT (PROTECTED)
# ==============================================================================
@router.get(
    "/me",
    response_model=StudentOut,
    status_code=status.HTTP_200_OK,
    summary="Get current authenticated student profile",
    description="Requires a valid Bearer JWT. Decodes student ID, validates it against PostgreSQL, and returns safe student profile."
)
def get_current_student_profile(current_student: Student = Depends(get_current_student)):
    return current_student


# ==============================================================================
# 5. UPDATE CURRENT STUDENT PROFILE (PROTECTED)
# ==============================================================================
@router.put(
    "/me",
    response_model=StudentOut,
    status_code=status.HTTP_200_OK,
    summary="Update current authenticated student profile",
    description="Updates permitted profile fields (avatar_index, full_name, program, year_of_study, reg_no) for the currently authenticated student."
)
def update_current_student_profile(
    payload: StudentUpdate,
    current_student: Student = Depends(require_non_demo_mutation),
    db: Session = Depends(get_db)
):
    require_non_demo_mutation(current_student)
    if payload.avatar_index is not None:
        if not (0 <= payload.avatar_index <= 19):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="avatar_index must be between 0 and 19 (available non-human mascots)"
            )
        current_student.avatar_index = payload.avatar_index

    if payload.full_name is not None and payload.full_name.strip():
        current_student.full_name = payload.full_name.strip()

    if payload.program is not None and payload.program.strip():
        current_student.program = payload.program.strip()

    if payload.year_of_study is not None and payload.year_of_study.strip():
        current_student.year_of_study = payload.year_of_study.strip()

    if payload.reg_no is not None and payload.reg_no.strip():
        current_student.reg_no = payload.reg_no.strip()

    db.commit()
    db.refresh(current_student)
    return current_student


