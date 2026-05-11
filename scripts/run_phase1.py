#!/usr/bin/env python3
"""Run Phase 1 ingestion from the command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scientific_data_assistant.ingestion import run_phase1


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse .xy files and create shared hackathon outputs.")
    parser.add_argument("input_dir", type=Path, help="Folder containing messy .xy files")
    parser.add_argument("output_dir", type=Path, help="Folder where contract outputs should be written")
    args = parser.parse_args()

    paths = run_phase1(args.input_dir, args.output_dir)
    print(f"Wrote metadata: {paths.metadata_table}")
    print(f"Wrote parsed traces: {paths.parsed_traces}")
    print(f"Wrote comments table: {paths.comments}")
    print(f"Wrote report: {paths.phase1_report}")


if __name__ == "__main__":
    main()
