"""
security.py
===========
Security utilities for UniLink:
1. Direct bcrypt password hashing and constant-time verification (Python 3.14 compatible).
2. JWT access token generation and decoding (uses student ID as string 'sub' claim).
3. Institutional email domain policy verification.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import bcrypt
import jwt

try:
    from backend.config import (
        ensure_secret_key,
        ALGORITHM,
        ACCESS_TOKEN_EXPIRE_MINUTES,
        ALLOWED_EMAIL_DOMAIN,
    )
except ImportError:
    from config import (
        ensure_secret_key,
        ALGORITHM,
        ACCESS_TOKEN_EXPIRE_MINUTES,
        ALLOWED_EMAIL_DOMAIN,
    )


# ==============================================================================
# 1. PASSWORD HASHING & VERIFICATION (Direct Bcrypt)
# ==============================================================================
def get_password_hash(password: str) -> str:
    """
    Hashes a plain-text password using direct bcrypt (salt rounds = 12).
    Compatible with Python 3.12, 3.13, and 3.14 without legacy passlib wrappers.
    Safely validates that UTF-8 byte length does not exceed bcrypt's 72-byte limit.
    """
    pwd_bytes = password.encode("utf-8")
    if len(pwd_bytes) > 72:
        raise ValueError("Password cannot exceed 72 bytes in UTF-8 representation.")

    # Generate a secure salt and hash the password
    salt = bcrypt.gensalt(rounds=12)
    hashed_bytes = bcrypt.hashpw(pwd_bytes, salt)
    return hashed_bytes.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plain password against a stored bcrypt hash using constant-time comparison.
    If the plain password exceeds 72 bytes or the hash is invalid, returns False safely.
    """
    pwd_bytes = plain_password.encode("utf-8")
    if len(pwd_bytes) > 72:
        return False

    try:
        hash_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except Exception:
        # Invalid hash format or corrupted hash string
        return False


# ==============================================================================
# 2. JWT TOKEN GENERATION & DECODING
# ==============================================================================
def create_access_token(
    student_id: int,
    email: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
    is_demo: bool = False
) -> str:
    """
    Generates a short-lived signed JWT access token.
    - Serializes the student's database integer ID as a string in the 'sub' claim.
    - Sets 'iat' (issued at) and 'exp' (expiration) timestamps using UTC timezone.
    - Includes 'is_demo' boolean flag if requested for presentation demo access.
    - Signs with SECRET_KEY using HS256.
    """
    if not isinstance(student_id, int) or student_id <= 0:
        raise ValueError("student_id must be a positive integer.")

    secret_key = ensure_secret_key()
    now = datetime.now(timezone.utc)

    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: Dict[str, Any] = {
        "sub": str(student_id),  # Consistently serialized as a string
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp())
    }

    if email:
        payload["email"] = email.strip().lower()

    if is_demo:
        payload["is_demo"] = True

    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decodes and verifies a JWT token against SECRET_KEY and ALGORITHM.
    - Validates signature and expiration timestamp.
    - Validates that the 'sub' claim exists, is a string, and converts to a valid student ID integer.
    - Returns a dictionary with student_id, email, exp, and iat.
    - Raises ValueError on expired or invalid tokens without exposing internal stack traces.
    """
    secret_key = ensure_secret_key()

    try:
        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired. Please log in again to continue.")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid authentication token.")

    # Validate the 'sub' claim
    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        raise ValueError("Token is missing a valid 'sub' identifier claim.")

    try:
        student_id = int(sub)
        if student_id <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("Token 'sub' claim is not a valid student ID.")

    return {
        "student_id": student_id,
        "email": payload.get("email"),
        "exp": payload.get("exp"),
        "iat": payload.get("iat"),
        "is_demo": bool(payload.get("is_demo", False))
    }


# ==============================================================================
# 3. CAMPUS DOMAIN POLICY VALIDATOR
# ==============================================================================
def validate_campus_email_domain(email: str) -> bool:
    """
    Checks whether an email belongs to an approved institutional domain.

    CRITICAL SECURITY DISTINCTION:
    - This function enforces domain format policy (e.g. rejecting @gmail.com or @yahoo.com).
    - It does NOT verify that the applicant owns, controls, or can receive mail at that address.
    - Therefore, any manual registration passing this check MUST remain is_verified=False
      until an active verification flow (e.g. OTP/link or Google OAuth) confirms ownership.
    """
    if not email or "@" not in email:
        return False

    parts = email.strip().lower().rsplit("@", 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return False

    domain = parts[1].strip()

    allowed_domains = {
        item.strip().lower()
        for item in ALLOWED_EMAIL_DOMAIN.split(",")
        if item.strip()
    }

    return domain in allowed_domains


# ==============================================================================
# 4. GOOGLE ID TOKEN VERIFICATION (Phase 8)
# ==============================================================================
def verify_google_id_token(id_token_str: str) -> Dict[str, Any]:
    """
    Verifies a Google ID token server-side using Google's official oauth2 library:
    - Verifies cryptographic signature using Google's public certs.
    - Validates audience (aud) matches the server-configured GOOGLE_CLIENT_ID.
    - Validates expiration (exp) and issuer (iss: accounts.google.com).
    - Ensures email claim is present and email_verified is True.
    - Returns decoded payload dictionary.
    - Raises ValueError on invalid signature, audience mismatch, expiration, or unverified email.
    """
    try:
        from backend.config import GOOGLE_CLIENT_ID
    except ImportError:
        from config import GOOGLE_CLIENT_ID

    if not GOOGLE_CLIENT_ID:
        raise ValueError("Google Sign-In is not configured on this server (GOOGLE_CLIENT_ID is missing).")

    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
    except ImportError:
        raise RuntimeError("Google authentication library (google-auth) is not installed on server.")

    request = google_requests.Request()
    try:
        payload = id_token.verify_oauth2_token(
            id_token_str,
            request,
            audience=GOOGLE_CLIENT_ID
        )
    except Exception as exc:
        raise ValueError(f"Invalid Google ID token: {str(exc)}")

    # Verify issuer
    issuer = payload.get("iss")
    if issuer not in ("accounts.google.com", "https://accounts.google.com"):
        raise ValueError(f"Invalid Google token issuer: {issuer}")

    # Verify email presence and verification status
    email = payload.get("email")
    if not email:
        raise ValueError("Google ID token is missing the email claim.")

    email_verified = payload.get("email_verified", False)
    if not email_verified:
        raise ValueError("Google account email is not verified by Google.")

    return payload

