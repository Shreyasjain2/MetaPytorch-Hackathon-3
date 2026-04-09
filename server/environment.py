# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
SQL/Data Cleaning Sandbox Environment Implementation.

Three tasks (easy  medium  hard) for AI agents:
  1. Data Triage    query revenue from sales data
  2. Data Cleaning  fix duplicates & nulls in a users table
  3. Schema Migration  normalize a flat table into two related tables
"""

import io
import os
import sqlite3
import sys
import tempfile
import traceback
from contextlib import redirect_stderr, redirect_stdout
from uuid import uuid4

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

try:
    from ..models import SqlSandboxAction, SqlSandboxObservation
except ImportError:
    from models import SqlSandboxAction, SqlSandboxObservation

# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------
TASKS = {
    "task1": {
        "id": "task1",
        "description": (
            "Find the total revenue from the 'sales' table for January 2024. "
            "The table has columns: id, product, amount, sale_date (YYYY-MM-DD). "
            "Return the exact total as a single number by running a SQL query. "
            "The expected result should be a SELECT query that returns one number."
        ),
        "max_steps": 10,
    },
    "task2": {
        "id": "task2",
        "description": (
            "The 'users' table has duplicate emails and NULL values in the 'age' column. "
            "Clean the data so that: (1) all emails are lowercase, "
            "(2) duplicate emails are removed (keep the row with the lowest id), "
            "(3) all NULL ages are replaced with 0. "
            "Use SQL or Python to fix the table in-place."
        ),
        "max_steps": 15,
    },
    "task3": {
        "id": "task3",
        "description": (
            "The 'flat_orders' table has columns: order_id, order_date, "
            "customer_name, customer_email, product, quantity, price. "
            "Normalize this into two tables: 'customers' (id INTEGER PRIMARY KEY, "
            "name TEXT, email TEXT UNIQUE) and 'orders' (id INTEGER PRIMARY KEY, "
            "customer_id INTEGER REFERENCES customers(id), order_date TEXT, "
            "product TEXT, quantity INTEGER, price REAL). "
            "Maintain foreign key integrity and migrate all data."
        ),
        "max_steps": 20,
    },
    "task4": {
        "id": "task4",
        "description": (
            "The 'server_logs' table has: id, ip_address, endpoint, status_code. "
            "1. Find the exact IP that accessed '/admin' with a 403 status code the most times.\n"
            "2. Create a new table 'blocked_ips' (id INTEGER PRIMARY KEY, ip_address TEXT).\n"
            "3. Insert that winning IP into 'blocked_ips'.\n"
            "4. Delete all log entries belonging to that IP from 'server_logs'.\n"
            "This task requires multiple steps. You will receive partial rewards for each step completed."
        ),
        "max_steps": 15,
    },
    "task5": {
        "id": "task5",
        "description": (
            "You have 'subscriptions' (id, user_id, plan_id, start_date, end_date_str) and 'plans' (plan_id, monthly_rate). "
            "1. Clean 'subscriptions': Replace any invalid 'end_date_str' (like 'NULL', 'N/A', or '') with '2024-12-31'.\n"
            "2. Create a view 'user_ltv' with columns 'user_id' and 'total_revenue'.\n"
            "3. Calculate 'total_revenue' inside the view as: (julianday(end_date_str) - julianday(start_date)) / 30.0 * monthly_rate.\n"
            "Return exactly one JSON command with DONE when you finish the view creation."
        ),
        "max_steps": 15,
    },
    "task6": {
        "id": "task6",
        "description": (
            "You have 'employees' (id, name, department_id, salary, metadata_json) and 'departments' (id, name). "
            "1. Add a new column 'total_comp REAL' to 'employees'.\n"
            "2. Update 'total_comp' = salary + (salary * json_extract(metadata_json, '$.bonus_pct') / 100.0).\n"
            "3. Create a view 'department_all_stars' with 'department_name' and 'employee_name' containing ONLY the single highest total_comp earner in each department whose json performance field is 'A'.\n"
            "You must complete all schema modifications and data processing steps."
        ),
        "max_steps": 20,
    },
}

# ---------------------------------------------------------------------------
# Seed data generators
# ---------------------------------------------------------------------------

def _seed_easy(conn: sqlite3.Connection):
    """Create sales table with known data."""
    conn.execute("DROP TABLE IF EXISTS sales")
    conn.execute(
        "CREATE TABLE sales (id INTEGER PRIMARY KEY, product TEXT, amount REAL, sale_date TEXT)"
    )
    rows = [
        (1, "Widget A", 150.00, "2024-01-05"),
        (2, "Widget B", 250.50, "2024-01-12"),
        (3, "Widget C", 99.99, "2024-01-20"),
        (4, "Widget A", 150.00, "2024-01-28"),
        (5, "Widget D", 349.51, "2024-01-15"),
        (6, "Widget A", 200.00, "2024-02-03"),
        (7, "Widget B", 75.00, "2023-12-30"),
    ]
    conn.executemany("INSERT INTO sales VALUES (?,?,?,?)", rows)
    conn.commit()


def _seed_medium(conn: sqlite3.Connection):
    """Create users table with messy data."""
    conn.execute("DROP TABLE IF EXISTS users")
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT, age INTEGER)"
    )
    rows = [
        (1, "Alice", "Alice@Example.com", 30),
        (2, "Bob", "bob@example.com", None),
        (3, "Charlie", "charlie@test.com", 25),
        (4, "Alice Dup", "alice@example.com", 28),
        (5, "Dave", "DAVE@Test.COM", None),
        (6, "Eve", "eve@example.com", 35),
        (7, "Dave Dup", "dave@test.com", 40),
        (8, "Frank", "frank@example.com", None),
    ]
    conn.executemany("INSERT INTO users VALUES (?,?,?,?)", rows)
    conn.commit()


def _seed_hard(conn: sqlite3.Connection):
    """Create flat_orders table."""
    conn.execute("DROP TABLE IF EXISTS flat_orders")
    conn.execute("DROP TABLE IF EXISTS customers")
    conn.execute("DROP TABLE IF EXISTS orders")
    conn.execute(
        "CREATE TABLE flat_orders ("
        "order_id INTEGER, order_date TEXT, customer_name TEXT, "
        "customer_email TEXT, product TEXT, quantity INTEGER, price REAL)"
    )
    rows = [
        (1, "2024-01-10", "Alice", "alice@example.com", "Laptop", 1, 999.99),
        (2, "2024-01-11", "Bob", "bob@example.com", "Mouse", 2, 25.50),
        (3, "2024-01-12", "Alice", "alice@example.com", "Keyboard", 1, 75.00),
        (4, "2024-01-13", "Charlie", "charlie@example.com", "Monitor", 1, 300.00),
        (5, "2024-01-14", "Bob", "bob@example.com", "Webcam", 1, 50.00),
        (6, "2024-01-15", "Diana", "diana@example.com", "USB Hub", 3, 15.99),
    ]
    conn.executemany("INSERT INTO flat_orders VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()


def _seed_task4(conn: sqlite3.Connection):
    conn.execute("DROP TABLE IF EXISTS server_logs")
    conn.execute("DROP TABLE IF EXISTS blocked_ips")
    conn.execute("CREATE TABLE server_logs (id INTEGER PRIMARY KEY, ip_address TEXT, endpoint TEXT, status_code INTEGER)")
    rows = [
        (1, "192.168.1.1", "/admin", 403),
        (2, "10.0.0.5", "/login", 200),
        (3, "192.168.1.1", "/admin", 403),
        (4, "172.16.0.2", "/admin", 403),
        (5, "192.168.1.1", "/dashboard", 200),
        (6, "10.0.0.5", "/admin", 403),
        (7, "192.168.1.1", "/admin", 403),
    ]
    conn.executemany("INSERT INTO server_logs VALUES (?,?,?,?)", rows)
    conn.commit()

def _seed_task5(conn: sqlite3.Connection):
    conn.execute("DROP TABLE IF EXISTS subscriptions")
    conn.execute("DROP TABLE IF EXISTS plans")
    conn.execute("CREATE TABLE plans (plan_id INTEGER PRIMARY KEY, monthly_rate REAL)")
    conn.executemany("INSERT INTO plans VALUES (?,?)", [(1, 10.0), (2, 50.0)])
    
    conn.execute("CREATE TABLE subscriptions (id INTEGER PRIMARY KEY, user_id INTEGER, plan_id INTEGER, start_date TEXT, end_date_str TEXT)")
    rows = [
        (1, 101, 1, "2024-11-01", "2024-12-01"),
        (2, 102, 2, "2024-10-02", "NULL"),
        (3, 103, 1, "2024-12-01", ""),
        (4, 101, 2, "2024-12-01", "N/A"),
    ]
    conn.executemany("INSERT INTO subscriptions VALUES (?,?,?,?,?)", rows)
    conn.commit()

def _seed_task6(conn: sqlite3.Connection):
    conn.execute("DROP TABLE IF EXISTS employees")
    conn.execute("DROP TABLE IF EXISTS departments")
    conn.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, department_id INTEGER, salary REAL, metadata_json TEXT)")
    deps = [(1, "Engineering"), (2, "Sales")]
    conn.executemany("INSERT INTO departments VALUES (?,?)", deps)
    emps = [
        (1, "Alice", 1, 120000, '{"bonus_pct": 10, "performance": "A"}'),
        (2, "Bob", 1, 150000, '{"bonus_pct": 5, "performance": "B"}'),
        (3, "Charlie", 1, 100000, '{"bonus_pct": 50, "performance": "A"}'),
        (4, "Dave", 2, 80000, '{"bonus_pct": 20, "performance": "A"}'),
        (5, "Eve", 2, 95000, '{"bonus_pct": 0, "performance": "A"}'),
    ]
    conn.executemany("INSERT INTO employees VALUES (?,?,?,?,?)", emps)
    conn.commit()

SEED_FNS = {
    "task1": _seed_easy, 
    "task2": _seed_medium, 
    "task3": _seed_hard,
    "task4": _seed_task4,
    "task5": _seed_task5,
    "task6": _seed_task6
}

# ---------------------------------------------------------------------------
# Graders
# ---------------------------------------------------------------------------

EASY_EXPECTED = 1000.00  # 150 + 250.5 + 99.99 + 150 + 349.51


def grade_easy(conn: sqlite3.Connection, last_output: str) -> float:
    """Check if agent returned correct total revenue for Jan 2024."""
    if not last_output:
        return 0.0
    
    # We inspect the agent's query execution result to see if 1000.0 is present.
    try:
        # Convert output strings to simple float checks.
        import re
        numbers = re.findall(r"[-+]?\d*\.\d+|\d+", last_output)
        for num in numbers:
            if abs(float(num) - EASY_EXPECTED) < 0.01:
                return 1.0
    except Exception:
        pass
    return 0.0


def grade_medium(conn: sqlite3.Connection, last_output: str) -> float:
    """Check cleaning quality: no duplicates, no nulls, lowercase emails."""
    score = 0.0
    try:
        # Check table exists
        cur = conn.execute("SELECT COUNT(*) FROM users")
        total = cur.fetchone()[0]
        if total == 0:
            return 0.0

        # Check lowercase emails (0.3)
        cur = conn.execute("SELECT COUNT(*) FROM users WHERE email != LOWER(email)")
        upper_count = cur.fetchone()[0]
        if upper_count == 0:
            score += 0.3

        # Check no duplicate emails (0.4)
        cur = conn.execute(
            "SELECT COUNT(*) FROM (SELECT LOWER(email) as e FROM users GROUP BY e HAVING COUNT(*) > 1)"
        )
        dup_count = cur.fetchone()[0]
        if dup_count == 0:
            score += 0.4

        # Check no NULL ages (0.3)
        cur = conn.execute("SELECT COUNT(*) FROM users WHERE age IS NULL")
        null_count = cur.fetchone()[0]
        if null_count == 0:
            score += 0.3
    except Exception:
        pass
    return round(score, 2)


def grade_hard(conn: sqlite3.Connection, last_output: str) -> float:
    """Verify normalized schema and data integrity."""
    score = 0.0
    try:
        # Check 'customers' table exists with correct columns (0.2)
        cur = conn.execute("PRAGMA table_info(customers)")
        cols = {r[1] for r in cur.fetchall()}
        if {"id", "name", "email"}.issubset(cols):
            score += 0.2

        # Check 'orders' table exists with correct columns (0.2)
        cur = conn.execute("PRAGMA table_info(orders)")
        cols = {r[1] for r in cur.fetchall()}
        if {"id", "customer_id", "order_date", "product", "quantity", "price"}.issubset(cols):
            score += 0.2

        # Check customer count = 4 unique customers (0.2)
        cur = conn.execute("SELECT COUNT(*) FROM customers")
        if cur.fetchone()[0] == 4:
            score += 0.2

        # Check orders count = 6 (0.2)
        cur = conn.execute("SELECT COUNT(*) FROM orders")
        if cur.fetchone()[0] == 6:
            score += 0.2

        # Check FK integrity: all customer_ids in orders exist in customers (0.2)
        cur = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE customer_id NOT IN (SELECT id FROM customers)"
        )
        if cur.fetchone()[0] == 0:
            score += 0.2
    except Exception:
        pass
    return round(score, 2)


def grade_task4(conn: sqlite3.Connection, last_output: str) -> float:
    score = 0.0
    try:
        cur = conn.execute("PRAGMA table_info(blocked_ips)")
        if len(cur.fetchall()) >= 2:
            score += 0.2
        
        cur = conn.execute("SELECT ip_address FROM blocked_ips")
        ips = [r[0] for r in cur.fetchall()]
        if "192.168.1.1" in ips:
            score += 0.3
        elif len(ips) > 0:
            score -= 0.1
            
        cur = conn.execute("SELECT COUNT(*) FROM server_logs WHERE ip_address = '192.168.1.1'")
        if cur.fetchone()[0] == 0:
            score += 0.3
            
        cur = conn.execute("SELECT COUNT(*) FROM server_logs WHERE ip_address != '192.168.1.1'")
        if cur.fetchone()[0] == 3:
            score += 0.2
        else:
            score -= 0.2
    except Exception:
        pass
    return round(max(0.0, score), 2)

def grade_task5(conn: sqlite3.Connection, last_output: str) -> float:
    score = 0.0
    try:
        cur = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE end_date_str IN ('NULL', 'N/A', '')")
        if cur.fetchone()[0] == 0:
            score += 0.3
        
        cur = conn.execute("SELECT user_id, total_revenue FROM user_ltv ORDER BY user_id")
        rows = cur.fetchall()
        if len(rows) > 0:
            score += 0.3
            
        actual = {int(r[0]): round(float(r[1]), 0) for r in rows}
        expected = {101: 60, 102: 150, 103: 10}
        
        if actual == expected:
            score += 0.4
        else:
            correct_users = len(set(actual.items()).intersection(set(expected.items())))
            score += (correct_users * 0.1)
            if correct_users == 0 and len(rows) > 0:
                score -= 0.1
                
    except Exception:
        pass
    return round(max(0.0, score), 2)

def grade_task6(conn: sqlite3.Connection, last_output: str) -> float:
    score = 0.0
    try:
        cur = conn.execute("PRAGMA table_info(employees)")
        cols = {r[1] for r in cur.fetchall()}
        if "total_comp" in cols:
            score += 0.2
            
            cur = conn.execute("SELECT name, total_comp FROM employees")
            comps = {r[0]: round(float(r[1]), 0) for r in cur.fetchall() if r[1] is not None}
            if comps.get("Charlie") == 150000 and comps.get("Alice") == 132000:
                score += 0.3
            elif len(comps) > 0:
                score -= 0.1
        
        cur = conn.execute("SELECT department_name, employee_name FROM department_all_stars")
        rows = set(cur.fetchall())
        expected = {("Engineering", "Charlie"), ("Sales", "Dave")}
        if rows == expected:
            score += 0.5
        elif len(rows) > 0:
            correct = len(rows.intersection(expected))
            score += correct * 0.2
            if correct == 0:
                score -= 0.1
                
    except Exception:
        pass
    return round(max(0.0, score), 2)

GRADERS = {
    "task1": grade_easy, 
    "task2": grade_medium, 
    "task3": grade_hard,
    "task4": grade_task4,
    "task5": grade_task5,
    "task6": grade_task6
}

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

class SqlSandboxEnvironment(Environment):
    """
    SQL / Data Cleaning Sandbox  a real-world OpenEnv environment.

    The agent sends SQL or Python commands to clean messy databases.
    Partial progress rewards are given after each step.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self):
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._db_path = os.path.join(tempfile.gettempdir(), f"sqlsandbox_{uuid4().hex[:8]}.db")
        self._conn: sqlite3.Connection | None = None
        self._task_id = os.environ.get("TASK_ID", "task1")
        if self._task_id not in TASKS:
            self._task_id = "task1"
        self._task = TASKS[self._task_id]
        self._max_steps = self._task["max_steps"]
        self._done = False
        self._last_reward = 0.0

    # ---- helpers -----------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def _partial_reward(self, last_output: str) -> float:
        """Run the grader to compute partial progress."""
        return GRADERS[self._task_id](self._get_conn(), last_output)

    def _exec_sql(self, query: str) -> tuple[str, str | None]:
        try:
            conn = self._get_conn()
            cur = conn.execute(query)
            if cur.description:
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                header = " | ".join(cols)
                body = "\n".join(" | ".join(str(c) for c in r) for r in rows)
                output = f"{header}\n{body}" if rows else header + "\n(no rows)"
            else:
                output = f"OK  {conn.total_changes} row(s) affected"
            conn.commit()
            return output, None
        except Exception as e:
            return "", str(e)

    def _exec_python(self, code: str) -> tuple[str, str | None]:
        stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            globs = {
                "__builtins__": __builtins__,
                "sqlite3": sqlite3,
                "DB_PATH": self._db_path,
                "conn": conn,
                "cursor": cursor,
            }
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(code, globs)
            
            # Automatically commit any schema changes the LLM's python code made
            conn.commit()
            
            out = stdout_buf.getvalue()
            err = stderr_buf.getvalue() or None
            return out, err
        except Exception:
            return stdout_buf.getvalue(), traceback.format_exc()

    # ---- OpenEnv interface -------------------------------------------------
    def reset(self, **kwargs) -> SqlSandboxObservation:
        """Resets the environment and forces a task switch if task_id is provided."""
        
        # 1. Close current connection to ensure file handles are released
        if self._conn:
            self._conn.close()
            self._conn = None

        # 2. Update task context from kwargs (primary) or environment (fallback)
        self._task_id = kwargs.get("task_id", os.environ.get("TASK_ID", "task1"))
        if self._task_id not in TASKS:
            self._task_id = "task1"
        self._task = TASKS[self._task_id]
        self._max_steps = self._task["max_steps"]

        # 3. Re-initialize episode state
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._done = False
        self._last_reward = 0.0

        # 4. Open fresh connection and re-seed for the specific task_id
        # Seed functions use 'DROP TABLE IF EXISTS' which handles cleanup.
        conn = self._get_conn()
        SEED_FNS[self._task_id](conn)

        return SqlSandboxObservation(
            output=f"Environment ready. Task: {self._task['description']}",
            error=None,
            current_step=0,
            max_steps=self._max_steps,
            task_description=self._task["description"],
            done=False,
            reward=0.0,
        )
 
    def step(self, action: SqlSandboxAction) -> SqlSandboxObservation:  # type: ignore[override]
        self._state.step_count += 1
        step = self._state.step_count

        if self._done:
            return SqlSandboxObservation(
                output="Episode already finished. Call reset().",
                error=None,
                current_step=step,
                max_steps=self._max_steps,
                task_description=self._task["description"],
                done=True,
                reward=self._last_reward,
            )

        # Execute action
        if action.tool == "sql":
            output, error = self._exec_sql(action.command)
        else:
            output, error = self._exec_python(action.command)

        # Compute partial reward
        reward = self._partial_reward(output)

        # Clamp reward between 0.01 and 0.99
        reward = max(0.01, min(0.99, reward))

        # Check termination
        done = step >= self._max_steps or reward >= 0.99
        if done:
            self._done = True

        self._last_reward = reward

        # Small penalty for errors to discourage random guessing
        if error:
            reward = max(0.01, reward - 0.05)

        return SqlSandboxObservation(
            output=output[:4000],  # cap output size
            error=error[:2000] if error else None,
            current_step=step,
            max_steps=self._max_steps,
            task_description=self._task["description"],
            done=done,
            reward=round(reward, 4),
        )

    @property
    def state(self) -> State:
        return self._state
