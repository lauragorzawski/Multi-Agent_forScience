#!/usr/bin/env python3
"""Run the Phase 4 multi-agent discussion from the command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scientific_data_assistant.agents import run_discussion


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the scientific discussion agents a question.")
    parser.add_argument("project_dir", type=Path, help="Folder containing metadata_table.csv, parsed_traces/, comments.csv")
    parser.add_argument("question", help="Question for the agents")
    args = parser.parse_args()

    state = run_discussion(args.project_dir, args.question)
    print(state.get("answer", "No answer produced."))


if __name__ == "__main__":
    main()
