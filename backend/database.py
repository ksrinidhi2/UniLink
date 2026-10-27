import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

# Locate the .env file in the backend directory
env_path = Path(__file__).resolve().parent / ".env"

# Load environment variables from .env
if env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path)
    except ImportError:
        # Fallback manual parser if python-dotenv is not installed
        with open(env_path, "r", encoding="utf-8") as f:
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

# Read DATABASE_URL from environment and normalize it
RAW_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not RAW_DATABASE_URL:
    if os.getenv("ENVIRONMENT", "").strip().lower() == "production" or os.getenv("VERCEL") == "1":
        raise RuntimeError(
            "Configuration Error: 'DATABASE_URL' environment variable is required in production but was not set."
        )
    RAW_DATABASE_URL = "postgresql+psycopg://postgres:localhost:5432/unilink_db"

DATABASE_URL = normalize_database_url(RAW_DATABASE_URL)

# 1. SQLAlchemy Engine:
# Detect serverless runtime (e.g. Vercel Functions, AWS Lambda)
IS_SERVERLESS = (
    os.getenv("VERCEL") == "1"
    or os.getenv("SERVERLESS", "").strip().lower() in ("1", "true", "yes")
    or os.getenv("DB_POOL_NULL", "").strip().lower() in ("1", "true", "yes")
)

connect_args = {}
if "psycopg" in DATABASE_URL:
    connect_args["connect_timeout"] = 5  # Psycopg driver connect timeout in seconds

if IS_SERVERLESS:
    # Serverless runtime: Use NullPool to avoid exhausting connections across ephemeral lambdas
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        poolclass=NullPool,
        connect_args=connect_args
    )
else:
    # Dedicated / Local development server: Use persistent connection pool with health checks
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_timeout=5,
        pool_recycle=300,
        connect_args=connect_args
    )

# 2. SessionLocal:
# A factory that creates new Session objects whenever a request comes in.
# A Session represents an ongoing conversation with the database.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 3. Base class:
# Base class used later to define database models (tables) using Python classes.
Base = declarative_base()


# 4. Dependency function (get_db):
# For FastAPI route handlers: provides an independent database session per request
# and automatically closes it when the request completes.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
