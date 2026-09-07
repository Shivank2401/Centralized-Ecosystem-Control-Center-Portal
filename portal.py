"""
Centralized Ecosystem Portal launcher.

Starts the FastAPI backend (Phase 6: outputs / logs / diagnostics explorers).
React UI: cd frontend && npm run dev

Usage:
    python portal.py
    python portal.py --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Centralized Ecosystem Portal")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "uvicorn is required. Install with: pip install -r requirements.txt"
        ) from exc

    print("Centralized Ecosystem Portal — Phase 6")
    print(f"Root: {_PROJECT_ROOT}")
    print(f"API docs: http://{args.host}:{args.port}/docs")
    print("UI: cd frontend && npm run dev -> http://127.0.0.1:5173")
    print("CLI: python run_pipeline.py")
    uvicorn.run("backend.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
