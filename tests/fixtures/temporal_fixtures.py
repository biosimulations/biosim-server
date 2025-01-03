from typing import AsyncGenerator

import pytest_asyncio
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from biosim_server.dependencies import get_temporal_client, set_temporal_client


@pytest_asyncio.fixture(scope="session")
async def temporal_env(request) -> AsyncGenerator[WorkflowEnvironment, None]:
    env_type = request.config.getoption("--workflow-environment")
    if env_type == "local":
        env = await WorkflowEnvironment.start_local()
    elif env_type == "time-skipping":
        env = await WorkflowEnvironment.start_time_skipping()
    else:
        env = WorkflowEnvironment.from_client(await Client.connect(env_type))

    yield env

    await env.shutdown()


@pytest_asyncio.fixture
async def temporal_client(temporal_env: WorkflowEnvironment) -> AsyncGenerator[Client, None]:
    saved_client = get_temporal_client()
    set_temporal_client(temporal_env.client)

    yield temporal_env.client

    set_temporal_client(saved_client)
