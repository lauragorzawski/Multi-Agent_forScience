#!/usr/bin/env python3
"""Run the Scientific Data Assistant API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Scientific Data Assistant API.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", default=8000, type=int, help="Port to bind")
    parser.add_argument("--reload", action="store_true", help="Reload when source files change")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("Uvicorn is not installed. Run `pip install -r requirements.txt`.") from exc

    uvicorn.run("scientific_data_assistant.api:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
