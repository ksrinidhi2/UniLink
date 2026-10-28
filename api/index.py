import sys
from pathlib import Path

# Add project root and backend directory to sys.path
# Supports running both locally and in Vercel Serverless Function environment
_FILE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _FILE_DIR.parent
if (_FILE_DIR / "backend").is_dir():
    _PROJECT_ROOT = _FILE_DIR

_BACKEND_DIR = _PROJECT_ROOT / "backend"

for _p in [str(_PROJECT_ROOT), str(_BACKEND_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backend.main import app as _fastapi_app


class VercelPathCorrectionMiddleware:
    """
    ASGI middleware ensuring that requests rewritten by Vercel retain their
    original path instead of being masked by destination '/api/index.py'.

    Guarantees:
    - Only activates when scope['path'] is the rewritten entrypoint ('/api/index.py', etc.)
    - Reads original path from Vercel edge-injected headers (x-matched-path / x-forwarded-uri)
    - Properly separates query parameters from the path and preserves scope['query_string']
    - Leaves standard direct/local development requests completely unaltered
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            current_path = scope.get("path", "")
            if current_path in ("/api/index.py", "/api/index", "/api", "") or current_path.startswith("/api/index.py/"):
                headers = dict(scope.get("headers", []))
                raw_target = (
                    headers.get(b"x-matched-path")
                    or headers.get(b"x-forwarded-uri")
                    or headers.get(b"x-invoke-path")
                )
                if raw_target:
                    try:
                        target_str = raw_target.decode("utf-8", errors="replace").strip()
                        if "?" in target_str:
                            path_part, qs_part = target_str.split("?", 1)
                            if not scope.get("query_string") and qs_part:
                                scope["query_string"] = qs_part.encode("latin-1")
                        else:
                            path_part = target_str

                        if not path_part.startswith("/"):
                            path_part = "/" + path_part
                        if path_part.startswith("//"):
                            path_part = "/" + path_part.lstrip("/")

                        scope["path"] = path_part
                        scope["raw_path"] = path_part.encode("utf-8")
                    except Exception:
                        pass
        await self.app(scope, receive, send)


# Vercel Serverless Function entry point
app = VercelPathCorrectionMiddleware(_fastapi_app)

