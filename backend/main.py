import os
import sys
from pathlib import Path

# Ensure both project root and backend directory are in sys.path
_BACKEND_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _BACKEND_DIR.parent

for _p in [str(_ROOT_DIR), str(_BACKEND_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError, OperationalError

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

# Database exception handlers to prevent uncaught connection drops from hanging the server
@app.exception_handler(OperationalError)
async def db_operational_error_handler(request: Request, exc: OperationalError):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": "Database connection failed. Please ensure PostgreSQL is running on port 5432 and accepting connections."
        }
    )

@app.exception_handler(SQLAlchemyError)
async def db_general_error_handler(request: Request, exc: SQLAlchemyError):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "A database error occurred while processing your request. Please check server logs."
        }
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
try:
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
except Exception:
    pass

# Mount static files for application assets (avatars, item thumbnails)
_ASSETS_DIR = _ROOT_DIR / "assets"
if _ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="assets")

# Frontend single-page application and static script paths
_CODE_HTML_PATH = _ROOT_DIR / "code.html"
_TAILWIND_PATH = _ROOT_DIR / "tailwindcss.js"


# Root endpoint: Serves the UniLink frontend single-page application
@app.get("/", response_class=FileResponse)
def read_root():
    if _CODE_HTML_PATH.is_file():
        return FileResponse(str(_CODE_HTML_PATH), media_type="text/html")
    return {"message": "UniLink API is running"}


@app.get("/code.html", response_class=FileResponse)
def read_code_html():
    if _CODE_HTML_PATH.is_file():
        return FileResponse(str(_CODE_HTML_PATH), media_type="text/html")
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@app.get("/index.html", response_class=FileResponse)
def read_index_html():
    if _CODE_HTML_PATH.is_file():
        return FileResponse(str(_CODE_HTML_PATH), media_type="text/html")
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@app.get("/tailwindcss.js", response_class=FileResponse)
def read_tailwind_js():
    if _TAILWIND_PATH.is_file():
        return FileResponse(str(_TAILWIND_PATH), media_type="application/javascript")
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


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

