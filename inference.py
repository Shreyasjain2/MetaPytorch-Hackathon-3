import argparse
import json
import os
import sys
import textwrap
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI

from client import SqlSandboxEnv
from models import SqlSandboxAction

# ---------------------------------------------------------------------------
# Ensure required env vars have fallbacks so OpenAI client never gets None
# ---------------------------------------------------------------------------
API_BASE_URL = os.getenv("API_BASE_URL") or "https://router.huggingface.co/v1"
API_KEY = os.getenv("HF_TOKEN") or os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME") or "gpt-4o-mini"
BENCHMARK = "sql_sandbox"

SYSTEM_PROMPT = textwrap.dedent("""
You are a data engineering assistant working inside a SQLite sandbox.

You can execute two types of actions:
1. {"tool": "sql",    "command": "<SQL query>"}
2. {"tool": "python", "command": "<Python code>"}

Rules:
1 Respond with EXACTLY ONE JSON object per turn  no markdown, no explanation.
2 In Python code, the variables `conn` (sqlite3.Connection) and `cursor`
  (sqlite3.Cursor) are already available. Do NOT call sqlite3.connect().
3 SQLite STRFTIME months are zero-padded: use '01' not '1', or use LIKE '2024-01-%'.
4 When you believe the task is fully complete, send:
  {"tool": "sql", "command": "SELECT 'DONE'"}
""").strip()


def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    error_val = error.replace("\n", " ") if error else "null"
    done_val = str(done).lower()
    print(
        f"[STEP] step={step} action={action} reward={reward:.2f} done={done_val} error={error_val}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(f"[END] success={str(success).lower()} steps={steps} score={score:.2f} rewards={rewards_str}", flush=True)


def _run_task_agent(client_llm: OpenAI, base_url: str, task_id: str, max_turns: int = 15) -> float:
    rewards: List[float] = []
    step_count = 0
    final_score = 0.0

    # Fallback response for API failures
    fallback_action = '{"tool": "sql", "command": "SELECT \'DONE\'"}'

    with SqlSandboxEnv(base_url=base_url).sync() as env:
        try:
            reset_resp = env.reset(task_id=task_id)
            task_desc = reset_resp.observation.task_description
        except Exception as e:
            print(f"[DEBUG] env.reset() error for task {task_id}: {e}", flush=True)
            return 0.0

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"Task: {task_desc}\n\nBegin."},
        ]

        log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)

        for turn in range(1, max_turns + 1):
            # 1. Ask the LLM, wrapped in try...except
            try:
                response = client_llm.chat.completions.create(
                    model=MODEL_NAME,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=512,
                )
                assistant_msg = response.choices[0].message.content.strip()
            except Exception as exc:
                print(f"[DEBUG] Model request failed: {exc}", flush=True)
                assistant_msg = fallback_action

            # 2. Parse action JSON
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

            # 3. Execute the action
            try:
                step_resp = env.step(SqlSandboxAction(tool=tool, command=command))
            except Exception as exc:
                print(f"[DEBUG] env.step() error: {exc}", flush=True)
                break

            reward = step_resp.reward or 0.0
            done   = step_resp.done
            output = step_resp.observation.output or ""
            error  = step_resp.observation.error  or ""

            rewards.append(reward)
            step_count += 1

            action_str = json.dumps({"tool": tool, "command": command})
            log_step(step=step_count, action=action_str, reward=reward, done=done, error=error)

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
        success = final_score >= 0.99

        log_end(success=success, steps=step_count, score=final_score, rewards=rewards)
        return final_score


def main():
    parser = argparse.ArgumentParser(
        description="OpenAI baseline inference for the SQL/Data Cleaning Sandbox"
    )
    parser.add_argument(
        "--url",
        default="http://localhost:7860",
        help="Base URL of the running environment server",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=15,
        help="Maximum agent turns per task (default: 15)",
    )
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: HF_TOKEN (or OPENAI_API_KEY) environment variable is not set.", flush=True)

    client_llm = OpenAI(
        api_key=API_KEY or "dummy_key",
        base_url=API_BASE_URL,
    )

    for task in ["easy", "medium", "hard"]:
        _run_task_agent(client_llm, args.url, task, args.max_turns)


if __name__ == "__main__":
    main()
