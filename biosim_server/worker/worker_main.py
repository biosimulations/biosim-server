import asyncio
import logging
import random

from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from biosim_server.biosim_runs import get_existing_biosim_simulation_run_activity, \
    submit_biosim_simulation_run_activity, OmexSimWorkflow
from biosim_server.biosim_verify.activities import generate_statistics_activity
from biosim_server.biosim_verify.omex_verify_workflow import OmexVerifyWorkflow
from biosim_server.biosim_verify.runs_verify_workflow import RunsVerifyWorkflow
from biosim_server.simulations.workflow import SimulationRunWorkflow
from biosim_server.dependencies import get_temporal_client, init_standalone

interrupt_event = asyncio.Event()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    random.seed(667)

    await init_standalone()

    client = get_temporal_client()
    if client is None:
        raise Exception("Could not connect to Temporal service")

    run_futures = []
    handle = Worker(
        client,
        task_queue="verification_tasks",
        workflows=[OmexVerifyWorkflow, OmexSimWorkflow, RunsVerifyWorkflow, SimulationRunWorkflow],
        activities=[get_existing_biosim_simulation_run_activity, submit_biosim_simulation_run_activity,
                    generate_statistics_activity],
        workflow_runner=UnsandboxedWorkflowRunner(),
    )
    run_futures.append(handle.run())
    print("Started worker for verification_tasks, ctrl+c to exit")

    await asyncio.gather(*run_futures)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        interrupt_event.set()
        loop.run_until_complete(loop.shutdown_asyncgens())
        print("\nShutting down workers")
