# Multi-Agent Scientific Data Assistant

This workspace contains a hackathon prototype for sorting messy scientific `.xy`/`.txt`
measurement files, extracting metadata, plotting parameter trends, adding
point/file-level comments, and discussing the results through a traceable
multi-agent workflow.

The core pipeline is intentionally conservative:

- `.xy`/`.txt` parsing, metadata extraction, summaries, and validation are deterministic by default.
- Optional model assistance can interpret the user's filename pattern and feedback, but final parsing is still validated Python.
- Agents explain and discuss evidence; they do not invent numeric results.
- Every output keeps a link back to the original file through `file_id`.

## Quick Start

Create or activate a Python environment, then install dependencies:

```zsh
source .venv/bin/activate
pip install -r requirements.txt
```

### Guided Metadata Agent

Start the API in one terminal:

```zsh
python scripts/run_api.py --port 8000
```

Start the guided Streamlit interface in a second terminal:

```zsh
streamlit run scientific_data_assistant/streamlit_metadata_app.py --server.port 8501
```

Open `http://127.0.0.1:8501`.

The agent guides the researcher through:

1. Where is your data stored?
2. What is the filename metadata pattern?
3. Give one example and explain what each part means.
4. Review the file/parameter overview table.
5. Send feedback if anything is unclear or wrong.
6. Approve and write the final Phase 1 outputs.

For the included FGT-style data, use:

- Raw data folder: `raw_data/20250708`
- Output folder: `fgt_output_api`
- Pattern: `material_sample_position_thickness_date_setting`
- Example: `FGT_1_1_20nm_20250708_0p1.txt means material FGT, sample position 1_1, thickness 20nm, date 2025-07-08, setting 0.1.`

The Streamlit sidebar includes **Use model assistance for pattern and feedback**.
When enabled, the configured OpenAI model helps interpret the pattern/example
and feedback text. If no key is configured, the system falls back to local
deterministic interpretation.

### API Usage

Preview filename-derived metadata through the API:

```zsh
curl -X POST http://127.0.0.1:8000/metadata-agent/turn \
  -H "Content-Type: application/json" \
  -d '{
    "input_dir": "sample_data",
    "output_dir": "demo_output",
    "metadata_pattern": "sample_material_thickness_exposure_measurement",
    "pattern_example": "S01_Fe_2nm_exp30s_xrd.xy means sample S01, material Fe, thickness 2nm, exposure 30s, measurement xrd.",
    "use_model_agent": false,
    "user_message": ""
  }'
```

Send the returned `state` back with feedback or approval. A message such as
`"approve and write outputs"` runs Phase 1 and writes `metadata_table.csv`,
`parsed_traces/`, `comments.csv`, `phase1_report.md`, and the metadata-agent
report/code artifacts.

The response includes:

- `table_overview`: compact review table with file name and extracted parameters.
- `state.preview_rows`: full dataframe-style rows that will become `metadata_table.csv`.
- `suggested_user_messages`: example feedback or approval messages.
- `model_status`: whether model assistance was used or deterministic fallback was used.

Useful `user_message` examples:

- `Please extract the date from the filename.`
- `Please extract the setting value, for example 0p1 or 1p0, as setting_value.`
- `Please extract replicate numbers from trailing filename suffixes.`
- `Add a column named run_id.`
- `approve and write outputs`

### Other Interfaces

Full multi-tab Streamlit dashboard:

```zsh
streamlit run scientific_data_assistant/dashboard.py
```

Dash table interface:

```zsh
python scripts/run_dash.py --port 8050
```

Open `http://127.0.0.1:8050`, click **Parse and Show Overview**, review the
file/parameter table, send feedback, then click **Approve and Write Outputs**.

Command-line Phase 1 ingestion:

```zsh
python scripts/run_phase1.py sample_data demo_output
```

Command-line discussion agents:

```zsh
python scripts/run_discussion.py demo_output "Which sample has the strongest signal and what should we inspect next?"
```

## Shared Contract

Phase 1 writes:

- `metadata_table.csv`
- `parsed_traces/{file_id}.csv`
- `comments.csv`
- `phase1_report.md`

Later phases read those files and write their own reports/outputs without
changing the Phase 1 contract.

## Teammate Handoff

- Phase 1 owner: guided metadata agent, ingestion, and filename extraction.
- Phase 2 owner: build plots from `metadata_table.csv` and `parsed_traces/`.
- Phase 3 owner: build comments and quality flags through `comments.csv`.
- Phase 4 owner: build LangGraph discussion over the shared outputs.

The current implementation includes a working baseline for all four phases.

## VS Code Setup

This workspace includes `.vscode/settings.json`, so VS Code should select the
local interpreter automatically:

```text
.venv/bin/python
```

The persisted team plan is in `HACKATHON_PLAN.md`.

## API Key Setup

Do not store real API keys in code. To enable optional model assistance in the
metadata agent and optional LLM polishing in the discussion layer, put your key
in the local `.env` file:

```text
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4.1-mini
```

You can also set a separate metadata-agent model:

```text
METADATA_AGENT_MODEL=gpt-4.1-mini
```

LangGraph itself orchestrates the agents; the OpenAI key is only needed for
optional model-assisted interpretation or final discussion polishing.

The `.env` file is ignored by git and loaded automatically by
`scripts/run_discussion.py`.

Check the setup without revealing the key:

```zsh
python scripts/check_api_setup.py
```
