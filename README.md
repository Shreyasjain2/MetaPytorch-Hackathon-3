---
title: SQL-Agent-RL
emoji: 🐳
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
tag: openenv
---
# SQL / Data Cleaning Sandbox

A FastAPI OpenEnv environment for evaluating AI agents on realistic SQLite data tasks.
Agents interact using SQL and Python to triage, clean, and normalize messy datasets across 6 diverse tasks.

## Motivation

This environment targets data engineering and debugging workflows where an agent must:
- inspect database state,
- correct broken or inconsistent data,
- calculate complex financial or system metrics,
- migrate flat schemas into normalized tables,
- and do so using incremental feedback.

It is designed for benchmarks with partial progress scoring and explicit penalties for destructive actions.

## Action Space

Agents submit actions as JSON objects:
- `tool`: `sql` or `python`
- `command`: the SQL query or Python code to execute

Example:

```json
{
  "tool": "sql",
  "command": "SELECT COUNT(*) FROM users WHERE email IS NULL"
}
```

## Observation Space

Each environment response includes:
- `output`: command output text
- `error`: raw execution error or `null`
- `current_step`: current step index
- `max_steps`: allowed step budget
- `task_description`: active task prompt
- `done`: whether the episode finished
- `reward`: partial reward for the step (includes potential late-task penalties)

## Tasks

The environment provides six progressively difficult tasks, indexed as `task1` through `task6`.

### task1 — Data Triage (Easy)
- **Description**: Compute total January 2024 revenue from the `sales` table.
- **Goal**: Run a SQL aggregation that returns the exact total value.
- **Success Criteria**: Reward `1.0` if the result matches `1000.00`.

### task2 — Data Cleaning (Medium)
- **Description**: Clean the `users` table:
  - Lowercase all emails.
  - Remove duplicate emails (retain lowest `id`).
  - Replace NULL ages with `0`.
- **Reward Breakdown**: `0.3` for Lowercase, `0.4` for No Duplicates, `0.3` for No NULLs.

### task3 — Schema Migration (Hard)
- **Description**: Normalize `flat_orders` into separate `customers` and `orders` tables.
- **Reward Breakdown**:
  - `0.2` for correct `customers` schema.
  - `0.2` for correct `orders` schema.
  - `0.6` for accurate data migration and referential integrity.

### task4 — Incident Response (Advanced)
- **Description**: Identify an IP address spamming 403 errors:
  - Create a `blocked_ips` table.
  - Move the offending IP into the blocklist.
  - Prune the offending records from the master `server_logs`.
- **Reward Breakdown**: `0.2` for table creation, `0.3` for correct IP identification, `0.5` for successful log pruning.
- **Penalty**: Deductions occur if legitimate traffic logs are accidentally deleted.

### task5 — Data Imputation & Revenue View (Advanced)
- **Description**: Standardize corrupted date strings and calculate Life Time Value:
  - Find and replace "NULL", "N/A", or empty strings in `end_date_str` with "2024-12-31".
  - Create a view `user_ltv` calculating revenue using `julianday()` arithmetic.
- **Reward Breakdown**: `0.3` for data cleaning, `0.3` for view creation, `0.4` for calculation accuracy.

### task6 — JSON Analysis & Ranking (Expert)
- **Description**: Extract nested JSON data and rank performance:
  - Add a `total_comp` column to `employees`.
  - Extract `bonus_pct` from a nested JSON string to compute total compensation.
  - Create a view `department_all_stars` showing the top earner in each department with performance rating "A".
- **Reward Breakdown**: `0.2` for schema mutation, `0.3` for JSON extraction accuracy, `0.5` for correct ranking logic.

## Reward Mechanism

Each step is scored by the task-specific grader in `server/environment.py`.
- The grader inspects the current database state and latest output.
- Reward is clamped to the range `0.01` to `0.99`.
- Episodes end when the step count reaches `max_steps` or reward reaches `0.99`.
- Errors subtract `0.05` from the step reward.
- Destructive or incorrect data modifications in advanced tasks result in score penalties.

## Baseline Scores

Recent reference runs using robust capable LLMs (e.g., `llama-3.3-70b-versatile` via Groq) indicate the environment is reliably solvable but effectively differentiates between model reasoning capabilities on the later multi-step tasks.

| Model | Task 1 (Easy) | Task 2 (Medium) | Task 3 (Hard) | Task 4 (Advanced) | Task 5 (Advanced) | Task 6 (Expert) |
|---|---|---|---|---|---|---|
| Llama-3.3-70B | ~1.00 | ~1.00 | ~1.00 | ~0.99 | ~0.90 | ~0.99 |
| Llama-3.1-8B | ~0.99 | ~0.60 | ~0.40 | ~0.30 | ~0.10 | ~0.00 |

*Note: Scores represent typical final-step partial-progress rewards. Simpler models often struggle to complete Schema Migration (Task 3) or JSON extraction windowing (Task 6), while advanced models can typically achieve near-perfect rewards within 3 to 6 execution steps per task.*

## Local Setup

### Install Python dependencies

```bash
cd MetaPytorch-Hackathon-3
pip install -r server/requirements.txt
pip install -e .
```

### Run the sandbox server locally

```bash
python -m uvicorn server.app:app --host 0.0.0.0 --port 7860
```

## Run inference and evaluation

Ensure `API_BASE_URL`, `MODEL_NAME`, and `HF_TOKEN` (or `OPENAI_API_KEY`) are set.

```bash
cd MetaPytorch-Hackathon-3
python inference.py
```

## Docker Setup

```bash
cd MetaPytorch-Hackathon-3

docker build -t sql-sandbox .
docker run -p 7860:7860 sql-sandbox
```

## Project structure

- `client.py` — OpenEnv client wrapper
- `models.py` — action and observation models
- `openenv.yaml` — environment manifest
- `inference.py` — OpenAI baseline runner
- `inference_groq.py` — Groq baseline runner
- `server/app.py` — FastAPI app entrypoint
- `server/environment.py` — task logic, grading, and reward mechanics

## License

BSD-3-Clause
