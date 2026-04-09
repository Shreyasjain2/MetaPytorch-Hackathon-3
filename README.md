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
Agents interact using SQL and Python to triage, clean, and normalize a small dataset.

## Motivation

This environment targets data engineering and debugging workflows where an agent must:
- inspect database state,
- correct broken or inconsistent data,
- migrate flat schemas into normalized tables,
- and do so using incremental feedback.

It is designed for benchmarks with partial progress scoring so agents can improve over multiple steps.

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
- `reward`: partial reward for the step

## Tasks

### Task 1 — Data Triage (easy)
- Description: compute total January 2024 revenue from `sales`.
- Expected behavior: run a SQL aggregation that returns the exact total value.
- Reward rule: returns `1.0` when the reported sum matches `1000.00`.

### Task 2 — Data Cleaning (medium)
- Description: clean the `users` table by:
  - lowercasing emails,
  - removing duplicate emails while keeping the smallest `id`,
  - replacing NULL ages with `0`.
- Expected behavior: fix the table in-place using SQL or Python.
- Reward breakdown:
  - `0.3` if all emails are lowercase,
  - `0.4` if no duplicate emails remain,
  - `0.3` if no NULL ages remain.

### Task 3 — Schema Migration (hard)
- Description: normalize `flat_orders` into `customers` and `orders` tables.
- Expected behavior: create:
  - `customers(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE)`,
  - `orders(id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), order_date TEXT, product TEXT, quantity INTEGER, price REAL)`.
- Reward breakdown:
  - `0.2` for correct `customers` schema,
  - `0.2` for correct `orders` schema,
  - `0.2` for 4 unique customers,
  - `0.2` for 6 orders migrated,
  - `0.2` for referential integrity on `customer_id`.

## Reward Mechanism

Each step is scored by the task-specific grader in `server/environment.py`.
- The grader inspects the current database state and latest output.
- Reward is clamped to the range `0.01` to `0.99`.
- Episodes end when the step count reaches `max_steps` or reward reaches `0.99`.
- Errors subtract `0.05` from the step reward, but never drop below `0.01`.


## Local Setup

### Install Python dependencies

This repository is designed to run inside the `FishBiscuits-OpenEnv_SRE_5` project structure.

```bash
cd MetaPytorch-Hackathon-2
pip install -r server/requirements.txt

# Install dependencies
pip install -e .
```

### Run the sandbox server locally

```bash
cd MetaPytorch-Hackathon-2
python -m uvicorn server.app:app --host 0.0.0.0 --port 7860
```


## Run inference and evaluation

### Environment Variables
Ensure the following are set:
```bash
export API_BASE_URL="https://api.openai.com/v1" # or your chosen provider
export MODEL_NAME="gpt-4o"
export OPENAI_API_KEY="your_api_key"
export HF_TOKEN="your_huggingface_token" # Required for HF hosted models
```

### Execute Baseline Agent
```bash
cd MetaPytorch-Hackathon-2
python inference.py
```

## Docker Setup

Docker is recommended for the most reliable sandbox experience.

### Build the Docker image

```bash
cd MetaPytorch-Hackathon-2
docker build -t sql-sanbox .
```

### Run the container

```bash
docker run -p 7860:7860 sql-sandbox
```

### Execute Baseline Agent
```bash
cd MetaPytorch-Hackathon-2
python inference.py
```

### Expected output format

Each episode should log exactly:

- `[START] task=<task_name> env=<benchmark> model=<model_name>`
- `[STEP] step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>`
- `[END] success=<true|false> steps=<n> score=<score> rewards=<r1,r2,...,rn>`

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
