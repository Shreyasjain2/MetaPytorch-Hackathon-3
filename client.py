# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""SQL Sandbox Environment Client."""

from typing import Dict

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State

from models import SqlSandboxAction, SqlSandboxObservation


class SqlSandboxEnv(EnvClient[SqlSandboxAction, SqlSandboxObservation, State]):
    """
    Client for the SQL/Data Cleaning Sandbox.

    Example:
        >>> with SqlSandboxEnv(base_url="http://localhost:8000") as client:
        ...     result = client.reset()
        ...     print(result.observation.task_description)
        ...     result = client.step(SqlSandboxAction(tool="sql", command="SELECT * FROM sales"))
        ...     print(result.observation.output)
    """

    def _step_payload(self, action: SqlSandboxAction) -> Dict:
        return {"tool": action.tool, "command": action.command}

    def _parse_result(self, payload: Dict) -> StepResult[SqlSandboxObservation]:
        obs_data = payload.get("observation", {})
        observation = SqlSandboxObservation(
            output=obs_data.get("output", ""),
            error=obs_data.get("error"),
            current_step=obs_data.get("current_step", 0),
            max_steps=obs_data.get("max_steps", 20),
            task_description=obs_data.get("task_description", ""),
            done=payload.get("done", False),
            reward=payload.get("reward"),
            metadata=obs_data.get("metadata", {}),
        )
        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: Dict) -> State:
        return State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )
