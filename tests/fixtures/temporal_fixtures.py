from typing import AsyncGenerator

import pytest
import pytest_asyncio
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from biosim_server.biosim_runs import get_existing_biosim_simulation_run_activity, \
    submit_biosim_simulation_run_activity, OmexSimWorkflow
from biosim_server.biosim_verify.activities import generate_statistics_activity
from biosim_server.biosim_verify.omex_verify_workflow import OmexVerifyWorkflow
from biosim_server.biosim_verify.runs_verify_workflow import RunsVerifyWorkflow
from biosim_server.simulations.workflow import SimulationRunWorkflow
from biosim_server.common.temporal import pydantic_data_converter
from biosim_server.dependencies import get_temporal_client, set_temporal_client


@pytest_asyncio.fixture(scope="session")
async def temporal_env(request: pytest.FixtureRequest) -> AsyncGenerator[WorkflowEnvironment, None]:
    env_type = request.config.getoption("--workflow-environment")
    if env_type == "local":
        env = await WorkflowEnvironment.start_local(ui=True, data_converter=pydantic_data_converter)
    elif env_type == "time-skipping":
        env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    else:
        env = WorkflowEnvironment.from_client(await Client.connect(env_type, data_converter=pydantic_data_converter))

    yield env

    await env.shutdown()


@pytest_asyncio.fixture(scope="function")
async def temporal_client(temporal_env: WorkflowEnvironment) -> AsyncGenerator[Client, None]:
    saved_client = get_temporal_client()
    set_temporal_client(temporal_env.client)

    yield temporal_env.client

    set_temporal_client(saved_client)


@pytest_asyncio.fixture(scope="function")
async def temporal_verify_worker(temporal_client: Client) -> AsyncGenerator[Worker, None]:
    async with Worker(
            temporal_client,
            task_queue="verification_tasks",
            workflows=[OmexVerifyWorkflow, OmexSimWorkflow, RunsVerifyWorkflow, SimulationRunWorkflow],
            activities=[generate_statistics_activity, get_existing_biosim_simulation_run_activity,
                        submit_biosim_simulation_run_activity],
            debug_mode=True,
            workflow_runner=UnsandboxedWorkflowRunner()
    ) as worker:
        yield worker
