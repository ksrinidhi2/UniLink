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

def normalize_database_url(url: str) -> str:
    """
    Normalizes database URL for SQLAlchemy 2.0 with modern psycopg v3 driver.
    Converts standard 'postgres://' and 'postgresql://' prefixes to 'postgresql+psycopg://'.
    Strips surrounding quotes and extraneous whitespace.
    """
    if not url:
        return ""
    clean_url = url.strip().strip("'\"")
    if clean_url.startswith("postgres://"):
        return "postgresql+psycopg://" + clean_url[len("postgres://"):]
    if clean_url.startswith("postgresql://") and not clean_url.startswith("postgresql+psycopg://"):
        return "postgresql+psycopg://" + clean_url[len("postgresql://"):]
    return clean_url

# Database configuration
RAW_DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
if not RAW_DATABASE_URL:
    if ENVIRONMENT == "production" or os.getenv("VERCEL") == "1":
        raise RuntimeError(
            "Configuration Error: 'DATABASE_URL' environment variable is required in production but was not set."
        )
    RAW_DATABASE_URL = "postgresql+psycopg://postgres:localhost:5432/unilink_db"

DATABASE_URL: str = normalize_database_url(RAW_DATABASE_URL)

# JWT Security configuration
SECRET_KEY: str = os.getenv("SECRET_KEY", "").strip()
ALGORITHM: str = os.getenv("ALGORITHM", "HS256").strip()

try:
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
except ValueError:
    ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Campus Institutional Domain (supports multiple comma-separated domains)
ALLOWED_EMAIL_DOMAIN: str = os.getenv("ALLOWED_EMAIL_DOMAIN", "vitapstudent.ac.in,vitap.ac.in").strip().lower()

# Environment mode ('development', 'staging', 'production')
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").strip().lower()

# Allowed Origins for CORS (comma-separated list of explicit origins)
ALLOWED_ORIGINS_RAW: str = os.getenv("ALLOWED_ORIGINS", "").strip()

# Google OAuth Client ID
GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "").strip()

# Placeholder constant to detect unconfigured secret keys
PLACEHOLDER_KEY = "CHANGE_THIS_TO_A_SECURE_RANDOM_HEX_KEY"


def get_cors_allowed_origins() -> list[str]:
    """
    Returns the parsed list of allowed CORS origins based on environment settings.
    - Explicit comma-separated origins from ALLOWED_ORIGINS.
    - Filters out permissive wildcard '*' when credentials are used (forbidden by CORS spec).
    - Automatically adds Vercel deployment URL if VERCEL_URL is present.
    - In development mode: includes local ports (3000, 8000, 8001).
    """
    origins: list[str] = []
    raw_origins = os.getenv("ALLOWED_ORIGINS", ALLOWED_ORIGINS_RAW).strip()

    if raw_origins:
        for orig in raw_origins.split(","):
            cleaned = orig.strip().rstrip("/")
            # Disallow wildcard '*' to prevent browser credential rejection
            if cleaned and cleaned != "*" and cleaned not in origins:
                origins.append(cleaned)

    # In Vercel environments, automatically include the preview / production Vercel domain
    vercel_url = os.getenv("VERCEL_URL", "").strip()
    if vercel_url:
        vercel_origin = f"https://{vercel_url}".rstrip("/")
        if vercel_origin not in origins:
            origins.append(vercel_origin)

    if ENVIRONMENT == "production":
        # Production mode strictly requires explicit origins
        if origins:
            return origins
        return ["https://unilink.vitapstudent.ac.in"]

    # Local development origins
    dev_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8001",
        "http://127.0.0.1:8001"
    ]
    for dev_orig in dev_origins:
        if dev_orig not in origins:
            origins.append(dev_orig)

    return origins


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
