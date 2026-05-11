# Hackathon Build Plan: Multi-Agent Scientific Data Workflow

## Goal

Build one connected system in phases, so each teammate can work independently
and still produce compatible results. The project is a multi-agent scientific
data assistant that sorts messy `.xy`/`.txt` measurement files, extracts metadata,
plots trends, adds point-level comments, and supports scientific discussion
through agents.

## Shared Contract

All phases use the same file contract.

### `metadata_table.csv`

Required columns:

- `file_id`: unique ID for each measurement file
- `file_path`: original file location
- `sample_id`: extracted or generated sample name
- `material`: material name, or `missing`
- `thickness_nm`: numeric thickness, or blank
- `exposure_time_s`: numeric exposure time, or blank
- `measurement_type`: e.g. `xrd`, `vsm`, `raman`, `unknown`
- `x_column`: name of x-axis data
- `y_column`: name of y-axis data
- `parse_status`: `ok`, `warning`, or `failed`
- `notes`: human/agent notes

### `parsed_traces/{file_id}.csv`

Required columns:

- `x`
- `y`

### `comments.csv`

Required columns:

- `comment_id`
- `file_id`
- `point_index`
- `comment`
- `comment_type`: `manual`, `agent`, `quality`, or `outlier`
- `created_by`

## Phase Ownership

### Phase 1: Data Sorting and Metadata Extraction

Build the ingestion pipeline.

Responsibilities:

- Scan a messy folder for `.xy` and `.txt` files.
- Parse each measurement file into clean `x,y` numeric data.
- Extract metadata from filenames using transparent rules.
- Write `metadata_table.csv`.
- Write one cleaned trace file per input file in `parsed_traces/`.
- Flag unclear filenames or broken files instead of guessing.

Success output:

- `metadata_table.csv`
- `parsed_traces/*.csv`
- `comments.csv`
- `phase1_report.md`

### Phase 2: Plotting Over Parameters

Build plotting using Phase 1 outputs.

Responsibilities:

- Read `metadata_table.csv` and `parsed_traces/`.
- Let the user choose plotting mode and grouping parameters.
- Plot by material, thickness, exposure time, measurement type, or sample ID.
- Use Plotly so hover text can include comments.
- Do not modify Phase 1 outputs.

Success output:

- Interactive dashboard or reusable plotting module.
- Plots that filter/group by metadata.
- `phase2_report.md`.

### Phase 3: Hover Comments and Data Quality Notes

Build annotation and quality-flag support.

Responsibilities:

- Create and maintain `comments.csv`.
- Link comments to a whole file or a specific point.
- Add hover text to plots using comments.
- Support notes such as “higher error because measurement system was damaged.”
- Add quality flags for missing metadata, failed parses, suspicious outliers,
  and manual warnings.

Success output:

- `comments.csv`
- Plot hover text includes relevant comments.
- `phase3_report.md`.

### Phase 4: Multi-Agent Scientific Discussion

Build the LangGraph agent layer.

Responsibilities:

- Use LangGraph to coordinate agents.
- Read `metadata_table.csv`, `parsed_traces/`, `comments.csv`, and plot summaries.
- Discuss scientific trends, parameter effects, outliers, uncertainty, and next experiments.
- Cite file IDs, metadata rows, or comments used.
- Keep numeric calculations deterministic in Python.

Recommended agents:

- Data Inspector Agent: checks files, metadata completeness, and parse status.
- Trend Analyst Agent: compares materials, thicknesses, and exposure times.
- Quality Critic Agent: highlights unreliable points and missing metadata.
- Discussion Agent: gives final user-facing answers with citations.

Success output:

- Chat interface or command-line demo.
- Answers grounded in project files.
- `phase4_report.md`.

## Integration Plan

- Everyone works against the shared contract.
- Phase 1 must be completed first, or other phases use a fake example dataset
  with the same structure.
- Phase 2 depends on `metadata_table.csv` and `parsed_traces/`.
- Phase 3 depends on Phase 2 plots and adds `comments.csv`.
- Phase 4 depends on all previous outputs.
- Final demo should be one Streamlit app with four tabs:
  - Data Review
  - Plots
  - Comments
  - Agent Discussion

## Validation Criteria

- Every plotted point traces back to an original `.xy` file.
- Metadata extraction shows uncertainty instead of hallucinating.
- Comments appear on hover for the correct point/file.
- Agents cite their evidence.
- The system handles messy, imperfect scientific data gracefully.

## Assumptions

- First version uses `.xy` and simple two-column `.txt` files.
- Metadata comes mainly from filenames.
- Parsing, plotting, and calculations are deterministic.
- LLM agents are used for explanation, discussion, summarization, and scientific reasoning.
- The main story is: “We turn messy lab files into traceable, explainable plots
  and agent-assisted scientific insight.”
