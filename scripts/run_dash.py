#!/usr/bin/env python3
"""Run the Dash metadata-agent interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scientific_data_assistant.dash_app import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Dash interface for the metadata agent.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", default=8050, type=int, help="Port to bind")
    parser.add_argument("--debug", action="store_true", help="Enable Dash debug mode")
    args = parser.parse_args()

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
