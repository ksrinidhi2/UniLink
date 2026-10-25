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

from backend.main import app

# Vercel Serverless Function entry point
# Vercel automatically exposes this 'app' ASGI instance

