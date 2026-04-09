"""
Inference Script Example
===================================
MANDATORY
- Before submitting, ensure the following variables are defined in your environment configuration:
    API_BASE_URL   The API endpoint for the LLM.
    MODEL_NAME     The model identifier to use for inference.
    HF_TOKEN       Your Hugging Face / API key.
    LOCAL_IMAGE_NAME The name of the local image to use for the environment if you are using from_docker_image()
                     method

- Defaults are set only for API_BASE_URL and MODEL_NAME 
    (and should reflect your active inference setup):
    API_BASE_URL = os.getenv("API_BASE_URL", "<your-active-endpoint>")
    MODEL_NAME = os.getenv("MODEL_NAME", "<your-active-model>")
    
- The inference script must be named `inference.py` and placed in the root directory of the project
- Participants must use OpenAI Client for all LLM calls using above variables

STDOUT FORMAT
- The script must emit exactly three line types to stdout, in this order:

    [START] task=<task_name> env=<benchmark> model=<model_name>
    [STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
    [END]   success=<true|false> steps=<n> score=<score> rewards=<r1,r2,...,rn>

  Rules:
    - One [START] line at episode begin.
    - One [STEP] line per step, immediately after env.step() returns.
    - One [END] line after env.close(), always emitted (even on exception).
    - reward and rewards are formatted to 2 decimal places.
    - done and success are lowercase booleans: true or false.
    - error is the raw last_action_error string, or null if none.
    - All fields on a single line with no newlines within a line.
    - Each tasks should return score in [0, 1]

  Example:
    [START] task=click-test env=miniwob model=Qwen3-VL-30B
    [STEP] step=1 action=click('123') reward=0.00 done=false error=null
    [STEP] step=2 action=fill('456','text') reward=0.00 done=false error=null
    [STEP] step=3 action=click('789') reward=1.00 done=true error=null
    [END] success=true steps=3 score=1.00 rewards=0.00,0.00,1.00
"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from groq import Groq

from client import SqlSandboxEnv
from models import SqlSandboxAction


# ---------------------------------------------------------------------------
# System prompt shared across all tasks
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are a data engineering assistant working inside a SQLite sandbox.

You can execute two types of actions:
1. {"tool": "sql",    "command": "<SQL query>"}
2. {"tool": "python", "command": "<Python code>"}

Rules:
- Respond with EXACTLY ONE JSON object per turn — no markdown, no explanation.
- In Python code, the variables `conn` (sqlite3.Connection) and `cursor`
  (sqlite3.Cursor) are already available. Do NOT call sqlite3.connect().
- SQLite STRFTIME months are zero-padded: use '01' not '1', or use LIKE '2024-01-%'.
- When you believe the task is fully complete, send:
  {"tool": "sql", "command": "SELECT 'DONE'"}
"""


# ---------------------------------------------------------------------------
# Core agent loop — one task, one WebSocket session
# ---------------------------------------------------------------------------
def _run_task_agent(base_url: str, task_id: str, max_turns: int = 15) -> float:
    """
    Open a fresh WebSocket session, reset the environment to the given task,
    then run an LLM agent loop until done or max_turns is reached.
    Returns the final reward (0.0 – 1.0).
    """
    client_llm = Groq(api_key=os.environ["GROQ_API_KEY"])
    final_reward = 0.0
    rewards = []

    # Each task gets its own WebSocket session to avoid state leakage
    with SqlSandboxEnv(base_url=base_url).sync() as env:
        # reset() with task_id seeds the correct DB table for this task
        reset_resp = env.reset(task_id=task_id)
        task_desc = reset_resp.observation.task_description

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"Task: {task_desc}\n\nBegin."},
        ]

        print(f"[START] task={task_id} env=sql_sandbox model=llama-3.3-70b-versatile")

        step_count = 0
        for turn in range(max_turns):
            # 1. Ask the LLM
            response = client_llm.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.0,
                max_tokens=512,
            )
            assistant_msg = response.choices[0].message.content.strip()

            # 2. Parse action JSON (handle optional markdown fences)
            try:
                raw = assistant_msg
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                action_data = json.loads(raw)
                tool    = action_data["tool"]
                command = action_data["command"]
            except (json.JSONDecodeError, KeyError):
                # Feed parse error back to LLM, do NOT count as a step
                messages.append({"role": "assistant", "content": assistant_msg})
                messages.append({
                    "role": "user",
                    "content": (
                        'Invalid JSON. Reply with exactly one JSON object:\n'
                        '{"tool": "sql" | "python", "command": "..."}'
                    ),
                })
                continue

            # 3. Execute the action via OpenEnv step()
            step_resp = env.step(SqlSandboxAction(tool=tool, command=command))

            reward = step_resp.reward or 0.0
            done   = step_resp.done
            output = step_resp.observation.output or ""
            error  = step_resp.observation.error  or ""

            final_reward = reward
            rewards.append(reward)
            step_count += 1

            action_str = json.dumps({"tool": tool, "command": command})
            error_str = error.replace("\n", " ") if error else "null"
            print(f"[STEP] step={step_count} action={action_str} reward={reward:.2f} done={str(done).lower()} error={error_str}")

            if done:
                break

            # 4. Feed result back to LLM for the next turn
            messages.append({"role": "assistant", "content": assistant_msg})
            feedback = f"Output:\n{output[:1500]}"
            if error:
                feedback += f"\nError:\n{error[:500]}"
            feedback += f"\nReward so far: {reward:.4f}"
            messages.append({"role": "user", "content": feedback})

    raw_score = sum(rewards)
    final_score = max(0.01, min(0.99, float(raw_score)))
    success = str(final_score >= 0.99).lower()
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(f"[END] success={success} steps={step_count} score={final_score:.2f} rewards={rewards_str}", flush=True)

    return final_score


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Groq baseline inference for the SQL/Data Cleaning Sandbox"
    )
    parser.add_argument(
        "--url",
        default="http://localhost:7860",
        help="Base URL of the running environment server (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=15,
        help="Maximum agent turns per task (default: 15)",
    )
    args = parser.parse_args()

    if "GROQ_API_KEY" not in os.environ:
        print("ERROR: GROQ_API_KEY environment variable is not set.")
        sys.exit(1)

    for task in [f"task{i}" for i in range(1, 7)]:
        _run_task_agent(args.url, task, args.max_turns)


if __name__ == "__main__":
    main()
