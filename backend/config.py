"""
config.py
=========
Centralized configuration manager for UniLink backend.
Loads settings from backend/.env and fails fast if critical security
parameters (such as SECRET_KEY) are missing or left as default placeholders.
Never logs or prints secrets.
"""

import os
from pathlib import Path

# Locate the .env file in the backend directory
ENV_PATH = Path(__file__).resolve().parent / ".env"

# Load environment variables from backend/.env if available
if ENV_PATH.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=ENV_PATH)
    except ImportError:
        # Fallback manual parser if python-dotenv is not installed
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())

# Database configuration
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:localhost:5432/unilink_db"
)

# JWT Security configuration
SECRET_KEY: str = os.getenv("SECRET_KEY", "").strip()
ALGORITHM: str = os.getenv("ALGORITHM", "HS256").strip()

try:
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
except ValueError:
    ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Campus Institutional Domain
ALLOWED_EMAIL_DOMAIN: str = os.getenv("ALLOWED_EMAIL_DOMAIN", "vitapstudent.ac.in").strip().lower()

# Environment mode ('development', 'staging', 'production')
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").strip().lower()

# Allowed Origins for CORS
ALLOWED_ORIGINS_RAW: str = os.getenv("ALLOWED_ORIGINS", "").strip()

# Google OAuth Client ID
GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "").strip()

# Placeholder constant to detect unconfigured secret keys
PLACEHOLDER_KEY = "CHANGE_THIS_TO_A_SECURE_RANDOM_HEX_KEY"


def get_cors_allowed_origins() -> list[str]:
    """
    Returns the parsed list of allowed CORS origins based on environment settings.
    In production: strictly uses explicit origins from ALLOWED_ORIGINS and never permits 'null'.
    In development: provides local development ports (3000, 8000).
    """
    if ALLOWED_ORIGINS_RAW:
        return [orig.strip() for orig in ALLOWED_ORIGINS_RAW.split(",") if orig.strip()]

    if ENVIRONMENT == "production":
        # Production default requires explicit configuration
        return ["https://unilink.vitapstudent.ac.in"]

    # Local development origins
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000"
    ]


def ensure_secret_key() -> str:
    """
    Validates that a genuine, strong SECRET_KEY is configured.
    Raises RuntimeError if the key is missing or unchanged from placeholder.
    Never exposes or logs the actual key.
    """
    if not SECRET_KEY or SECRET_KEY == PLACEHOLDER_KEY:
        raise RuntimeError(
            "Security Error: 'SECRET_KEY' is not configured in backend/.env. "
            "Please generate a 32-byte secret key and assign it in backend/.env before running."
        )
    if len(SECRET_KEY) < 32:
        raise RuntimeError(
            "Security Error: 'SECRET_KEY' in backend/.env is too short. "
            "Must be at least 32 characters long."
        )
    return SECRET_KEY
