import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

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

# Read DATABASE_URL from environment
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:YOUR_POSTGRES_PASSWORD@localhost:5432/unilink_db"
)

# 1. SQLAlchemy Engine:
# The Engine is the starting point for any SQLAlchemy application.
# It maintains a pool of database connections and knows how to talk to PostgreSQL using the Psycopg driver.
engine = create_engine(
    DATABASE_URL,
    echo=False  # Set to True if you want to see generated SQL statements in the terminal
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
