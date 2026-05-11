# Multi-Agent Scientific Data Assistant

This workspace contains a hackathon prototype for sorting messy scientific `.xy`/`.txt`
measurement files, extracting metadata, plotting parameter trends, adding
point/file-level comments, and discussing the results through a traceable
multi-agent workflow.

The core pipeline is intentionally conservative:

- `.xy` parsing, metadata extraction, summaries, and validation are deterministic.
- Agents explain and discuss evidence; they do not invent numeric results.
- Every output keeps a link back to the original file through `file_id`.

## Quick Start

Use the local Python environment already created in this folder:

```zsh
source .venv/bin/activate
```

Run Phase 1 on the included sample data:

```zsh
python scripts/run_phase1.py sample_data demo_output
```

Run Phase 1 on Laura's copied July 2025 FGT text files:

```zsh
python scripts/run_phase1.py raw_data/20250708 fgt_output
```

Ask the multi-agent discussion layer a question:

```zsh
python scripts/run_discussion.py demo_output "Which sample has the strongest signal and what should we inspect next?"
```

If you install the optional dashboard dependencies, run:

```zsh
pip install -r requirements.txt
streamlit run scientific_data_assistant/dashboard.py
```

Run the API for the same conversational metadata builder:

```zsh
pip install -r requirements.txt
python scripts/run_api.py --port 8000
```

Preview filename-derived metadata through the API:

```zsh
curl -X POST http://127.0.0.1:8000/metadata-agent/turn \
  -H "Content-Type: application/json" \
  -d '{
    "input_dir": "sample_data",
    "output_dir": "demo_output",
    "user_message": ""
  }'
```

Send the returned `state` back with feedback or approval. A message such as
`"approve and write outputs"` runs Phase 1 and writes `metadata_table.csv`,
`parsed_traces/`, `comments.csv`, `phase1_report.md`, and the metadata-agent
report/code artifacts.

The response includes:

- `state.table_overview`: compact review table with file name and extracted parameters.
- `state.preview_rows`: full dataframe-style rows that will become `metadata_table.csv`.
- `state.suggested_user_messages`: example feedback or approval messages.

Useful `user_message` examples:

- `Please extract the date from the filename.`
- `Please extract the setting value, for example 0p1 or 1p0, as setting_value.`
- `Please extract replicate numbers from trailing filename suffixes.`
- `Add a column named run_id.`
- `approve and write outputs`

For a friendlier table interface, keep the API running and start Dash in a
second terminal:

```zsh
python scripts/run_dash.py --port 8050
```

Open `http://127.0.0.1:8050`, click **Scan and Preview**, review the
file/parameter table, send feedback, then click **Approve and Write Outputs**.

The same guided workflow is available as a Streamlit app:

```zsh
python scripts/run_api.py --port 8000
streamlit run scientific_data_assistant/streamlit_metadata_app.py --server.port 8501
```

Open `http://127.0.0.1:8501`, answer the agent's folder and filename-pattern
questions, review the overview table, send feedback if needed, then approve.

## Shared Contract

Phase 1 writes:

- `metadata_table.csv`
- `parsed_traces/{file_id}.csv`
- `comments.csv`
- `phase1_report.md`

Later phases read those files and write their own reports/outputs without
changing the Phase 1 contract.

## Teammate Handoff

- Phase 1 owner: implement/improve ingestion and metadata extraction.
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

Do not store real API keys in code. To enable optional LLM polishing in the
discussion layer, put your key in the local `.env` file:

```text
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4.1-mini
```

LangGraph itself orchestrates the agents; the OpenAI key is only needed if you
install `langchain-openai` and want the final discussion answer to be polished by
an LLM.

The `.env` file is ignored by git and loaded automatically by
`scripts/run_discussion.py`.

Check the setup without revealing the key:

```zsh
python scripts/check_api_setup.py
```
