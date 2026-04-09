# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Data models for the SQL/Data Cleaning Sandbox Environment.

Agents interact by sending SQL queries or Python snippets to clean
messy databases and generate reports.
"""

from typing import Literal, Optional

from openenv.core.env_server.types import Action, Observation
from pydantic import Field


class SqlSandboxAction(Action):
    """Action for the SQL Sandbox  run a SQL query or Python snippet."""

    tool: Literal["sql", "python"] = Field(
        ..., description="Tool to use: 'sql' for SQLite queries, 'python' for Python scripts"
    )
    command: str = Field(
        ..., description="The SQL query or Python code to execute"
    )


class SqlSandboxObservation(Observation):
    """Observation returned after each step."""

    output: str = Field(default="", description="stdout / query result")
    error: Optional[str] = Field(default=None, description="stderr or error message")
    current_step: int = Field(default=0, description="Current step number")
    max_steps: int = Field(default=20, description="Maximum allowed steps")
    task_description: str = Field(default="", description="Current task description")
