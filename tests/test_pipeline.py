from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scientific_data_assistant.agents import run_discussion
from scientific_data_assistant.api import MetadataAgentTurnRequest, run_metadata_agent_api_turn
from scientific_data_assistant.comments import add_comment
from scientific_data_assistant.contracts import COMMENTS_COLUMNS, METADATA_COLUMNS, TRACE_COLUMNS, ProjectPaths
from scientific_data_assistant.ingestion import extract_metadata, parse_xy_file, run_phase1
from scientific_data_assistant.metadata_agent import run_metadata_agent_turn, validate_generated_code
from scientific_data_assistant.plotting import build_overlay_points, summarize_traces


class PipelineTests(unittest.TestCase):
    def test_parse_xy_skips_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "S01_Fe_2nm_30s_xrd.xy"
            path.write_text("# header\nbad line\n0 1\n1,2\n", encoding="utf-8")
            parsed = parse_xy_file(path)
            self.assertEqual(parsed.status, "warning")
            self.assertEqual(parsed.rows, [(0.0, 1.0), (1.0, 2.0)])

    def test_metadata_from_filename(self) -> None:
        meta = extract_metadata(Path("S01_Fe_2nm_exp30s_xrd.xy"))
        self.assertEqual(meta["material"], "Fe")
        self.assertEqual(meta["thickness_nm"], "2")
        self.assertEqual(meta["exposure_time_s"], "30")
        self.assertEqual(meta["measurement_type"], "xrd")

    def test_full_pipeline_contract_and_agents(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "raw"
            output_dir = root / "out"
            input_dir.mkdir()
            (input_dir / "S01_Fe_2nm_exp30s_xrd.xy").write_text("0 1\n1 3\n2 2\n", encoding="utf-8")
            (input_dir / "S02_Ru_4nm_exp60s_xrd.xy").write_text("# h\n0 2\n1 6\n2 5\n", encoding="utf-8")

            paths = run_phase1(input_dir, output_dir)
            self.assertTrue(paths.metadata_table.exists())
            self.assertTrue(paths.comments.exists())

            with paths.metadata_table.open(newline="", encoding="utf-8") as handle:
                metadata_rows = list(csv.DictReader(handle))
                self.assertEqual(list(metadata_rows[0].keys()), METADATA_COLUMNS)
            with paths.comments.open(newline="", encoding="utf-8") as handle:
                self.assertEqual(csv.DictReader(handle).fieldnames, COMMENTS_COLUMNS)

            trace_path = paths.parsed_traces / f"{metadata_rows[0]['file_id']}.csv"
            with trace_path.open(newline="", encoding="utf-8") as handle:
                self.assertEqual(csv.DictReader(handle).fieldnames, TRACE_COLUMNS)

            add_comment(paths, metadata_rows[0]["file_id"], "higher error because measurement system was damaged")
            points = build_overlay_points(paths)
            self.assertTrue(any("higher error" in point["hover"] for point in points))

            summaries = summarize_traces(paths)
            self.assertEqual(len(summaries), 2)

            with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
                state = run_discussion(output_dir, "Which sample is strongest?")
            self.assertIn("Strongest peak", state["answer"])
            self.assertIn("metadata_table.csv", state["answer"])

    def test_txt_files_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "raw"
            output_dir = root / "out"
            input_dir.mkdir()
            (input_dir / "FGT_1_1_20nm_20250708_0p1.txt").write_text("50.2\t127\n50.8\t125\n", encoding="utf-8")

            paths = run_phase1(input_dir, output_dir)
            with paths.metadata_table.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["material"], "FGT")
            self.assertEqual(rows[0]["thickness_nm"], "20")
            self.assertEqual(rows[0]["parse_status"], "ok")

    def test_phase1_accepts_custom_metadata_extractor_and_extra_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "raw"
            output_dir = root / "out"
            input_dir.mkdir()
            (input_dir / "FGT_1_1_20nm_20250708_0p1.txt").write_text("50.2\t127\n50.8\t125\n", encoding="utf-8")

            def custom_metadata(path: Path) -> dict[str, object]:
                return {
                    "sample_id": path.stem,
                    "material": "FGT",
                    "thickness_nm": "20",
                    "exposure_time_s": "",
                    "measurement_type": "unknown",
                    "measurement_date": "2025-07-08",
                    "notes": "Custom metadata extractor.",
                }

            paths = run_phase1(input_dir, output_dir, metadata_extractor=custom_metadata, extra_metadata_columns=["measurement_date"])
            with paths.metadata_table.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(list(rows[0].keys()), METADATA_COLUMNS + ["measurement_date"])
            self.assertEqual(rows[0]["measurement_date"], "2025-07-08")

    def test_metadata_agent_scans_supported_files_and_previews_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "raw"
            output_dir = root / "out"
            input_dir.mkdir()
            (input_dir / "S01_Fe_2nm_exp30s_xrd.xy").write_text("0 1\n1 2\n", encoding="utf-8")
            (input_dir / "FGT_1_1_20nm_20250708_0p1.txt").write_text("50.2\t127\n50.8\t125\n", encoding="utf-8")
            (input_dir / "ignore.csv").write_text("x,y\n1,2\n", encoding="utf-8")

            state = run_metadata_agent_turn(
                {
                    "input_dir": str(input_dir),
                    "output_dir": str(output_dir),
                    "metadata_pattern": "material_thickness_date_setting",
                    "pattern_example": "FGT_1_1_20nm_20250708_0p1.txt means material, position, thickness, date, setting.",
                },
                "",
            )
            discovered_names = {Path(path).name for path in state["discovered_files"]}

            self.assertEqual(discovered_names, {"FGT_1_1_20nm_20250708_0p1.txt", "S01_Fe_2nm_exp30s_xrd.xy"})
            self.assertIn("measurement_date", state["proposed_columns"])
            self.assertEqual(len(state["preview_rows"]), 2)
            self.assertEqual(len(state["table_overview"]), 2)
            self.assertIn("file", state["table_overview"][0])
            self.assertIn("approve and write outputs", state["suggested_user_messages"])
            self.assertFalse(state["validation_errors"])

    def test_metadata_agent_guides_user_to_provide_filename_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "raw"
            output_dir = root / "out"
            input_dir.mkdir()
            (input_dir / "FGT_1_1_20nm_20250708_0p1.txt").write_text("50.2\t127\n50.8\t125\n", encoding="utf-8")

            state = run_metadata_agent_turn({"input_dir": str(input_dir), "output_dir": str(output_dir)}, "")

            self.assertEqual(state["conversation_stage"], "need_pattern")
            self.assertEqual(state["table_overview"], [])
            self.assertIn("What is the pattern", state["messages"][-1]["content"])

    def test_metadata_agent_code_validation_accepts_safe_and_rejects_unsafe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "raw"
            output_dir = root / "out"
            input_dir.mkdir()
            (input_dir / "S01_Fe_2nm_exp30s_xrd.xy").write_text("0 1\n1 2\n", encoding="utf-8")

            state = run_metadata_agent_turn(
                {
                    "input_dir": str(input_dir),
                    "output_dir": str(output_dir),
                    "metadata_pattern": "material_thickness_measurement",
                    "pattern_example": "S01_Fe_2nm_exp30s_xrd.xy means sample, material, thickness, exposure, measurement.",
                },
                "",
            )
            self.assertEqual(validate_generated_code(state["generated_code"]), [])

            unsafe = "import os\n\ndef extract_metadata_from_filename(path):\n    open('x', 'w')\n    return {}\n"
            errors = validate_generated_code(unsafe)
            self.assertTrue(any("Import is not allowed" in error for error in errors))
            self.assertTrue(any("Call is not allowed" in error for error in errors))

    def test_metadata_agent_approval_writes_phase1_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "raw"
            output_dir = root / "out"
            input_dir.mkdir()
            (input_dir / "FGT_1_1_20nm_20250708_0p1.txt").write_text("50.2\t127\n50.8\t125\n", encoding="utf-8")

            state = run_metadata_agent_turn(
                {
                    "input_dir": str(input_dir),
                    "output_dir": str(output_dir),
                    "metadata_pattern": "material_position_thickness_date_setting",
                    "pattern_example": "FGT_1_1_20nm_20250708_0p1.txt means material, position, thickness, date, setting.",
                },
                "",
            )
            state = run_metadata_agent_turn(state, "approve")

            self.assertTrue((output_dir / "metadata_table.csv").exists())
            self.assertTrue((output_dir / "metadata_agent_extractor.py").exists())
            self.assertTrue(state["approved"])

    def test_metadata_agent_api_turn_previews_and_preserves_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "raw"
            output_dir = root / "out"
            input_dir.mkdir()
            (input_dir / "FGT_1_1_20nm_20250708_0p1.txt").write_text("50.2\t127\n50.8\t125\n", encoding="utf-8")

            response = run_metadata_agent_api_turn(
                {
                    "input_dir": str(input_dir),
                    "output_dir": str(output_dir),
                    "metadata_pattern": "material_position_thickness_date_setting",
                    "pattern_example": "FGT_1_1_20nm_20250708_0p1.txt means material, position, thickness, date, setting.",
                    "user_message": "",
                }
            )
            state = response["state"]
            self.assertEqual(response["table_overview"][0]["file"], "FGT_1_1_20nm_20250708_0p1.txt")
            self.assertEqual(response["table_overview"][0]["position_1"], "1")
            self.assertEqual(response["table_overview"][0]["position_2"], "1")
            self.assertEqual(response["table_overview"][0]["setting_value"], "0.1")
            self.assertIn("unclear_items", response)
            self.assertIn("approve and write outputs", response["suggested_user_messages"])
            self.assertIn("overview table", response["assistant_message"])
            self.assertIn("measurement_date", state["proposed_columns"])
            self.assertEqual(len(state["preview_rows"]), 1)
            self.assertEqual(state["table_overview"][0]["file"], "FGT_1_1_20nm_20250708_0p1.txt")
            self.assertIn("approve and write outputs", state["suggested_user_messages"])

            approval = run_metadata_agent_api_turn(
                MetadataAgentTurnRequest(
                    state=state,
                    user_message="approve and write outputs",
                )
            )
            self.assertTrue(approval["state"]["approved"])
            self.assertTrue((output_dir / "metadata_table.csv").exists())


if __name__ == "__main__":
    unittest.main()
