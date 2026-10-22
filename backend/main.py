import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

# Import database engine and routers
try:
    from backend.database import engine
    from backend.routers.auth import router as auth_router
    from backend.routers.listings import router as listings_router
    from backend.routers.borrow import router as borrow_router
    from backend.routers.lost_found import router as lost_found_router
    from backend.routers.messages import router as messages_router
    from backend.routers.notifications import router as notifications_router
    from backend.routers.saved_items import router as saved_items_router
    from backend.routers.uploads import router as uploads_router
except ImportError:
    from database import engine
    from routers.auth import router as auth_router
    from routers.listings import router as listings_router
    from routers.borrow import router as borrow_router
    from routers.lost_found import router as lost_found_router
    from routers.messages import router as messages_router
    from routers.notifications import router as notifications_router
    from routers.saved_items import router as saved_items_router
    from routers.uploads import router as uploads_router

# Create the FastAPI application instance
app = FastAPI(
    title="UniLink API",
    description="Backend API for UniLink campus platform",
    version="0.1.0"
)

try:
    from backend.config import get_cors_allowed_origins
except ImportError:
    from config import get_cors_allowed_origins

# Configure CORS using environment-aware origins
ALLOWED_ORIGINS = get_cors_allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
)

# Mount routers
app.include_router(auth_router)
app.include_router(listings_router)
app.include_router(borrow_router)
app.include_router(saved_items_router)
app.include_router(lost_found_router)
app.include_router(messages_router)
app.include_router(notifications_router)
app.include_router(uploads_router)

# Mount static files for uploaded assets after API routers
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


# Root endpoint: Welcomes visitors / confirms API is up
@app.get("/")
def read_root():
    return {"message": "UniLink API is running"}


# Health check endpoint: Used to monitor server health
@app.get("/health")
def health_check():
    return {"status": "ok"}


# Temporary database connectivity check endpoint
@app.get("/db-check")
def test_db_connection():
    """
    Attempts to connect to PostgreSQL and execute a lightweight test query ('SELECT 1;').
    Returns connection status without crashing the server if the credentials are not set yet.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1;"))
        return {
            "database": "connected",
            "message": "Successfully connected to PostgreSQL database (unilink_db)!"
        }
    except Exception as exc:
        return {
            "database": "disconnected",
            "error": str(exc),
            "hint": "Make sure PostgreSQL is running and update YOUR_POSTGRES_PASSWORD in backend/.env"
        }

