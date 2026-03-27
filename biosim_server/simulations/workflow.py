import asyncio
import logging
from datetime import timedelta

from pydantic import BaseModel
from temporalio import workflow
from temporalio.common import RetryPolicy

from biosim_server.biosim_omex import OmexFile
from biosim_server.biosim_runs import BiosimulatorVersion, BiosimSimulationRunStatus
from biosim_server.simulations.activities import (
    SubmitSimulationInput,
    SubmitSimulationOutput,
    submit_simulation_activity,
    PollSimulationInput,
    poll_simulation_activity,
)
from biosim_server.simulations.models import SimulationJobStatus, ConglomerateStatus


class SimulationRunWorkflowInput(BaseModel):
    omex_file: OmexFile
    simulators: list[BiosimulatorVersion]
    job_ids: list[str]
    cache_buster: str


@workflow.defn
class SimulationRunWorkflow:
    workflow_input: SimulationRunWorkflowInput
    job_statuses: dict[str, SimulationJobStatus]

    @workflow.init
    def __init__(self, workflow_input: SimulationRunWorkflowInput) -> None:
        self.workflow_input = workflow_input
        self.job_statuses = {}
        for job_id, sim in zip(workflow_input.job_ids, workflow_input.simulators):
            self.job_statuses[job_id] = SimulationJobStatus(
                job_id=job_id,
                simulator_id=sim.id,
                version=sim.version,
                status="processing",
            )

    @workflow.query(name="get_status")
    def get_status(self) -> ConglomerateStatus:
        return ConglomerateStatus(
            processing_id=workflow.info().workflow_id,
            jobs=list(self.job_statuses.values()),
        )

    @workflow.run
    async def run(self, workflow_input: SimulationRunWorkflowInput) -> ConglomerateStatus:
        workflow.logger.setLevel(level=logging.INFO)
        workflow.logger.info("SimulationRunWorkflow started.")

        # Phase 1: Submit all simulations in parallel, capture run IDs immediately
        submit_tasks = []
        for sim in workflow_input.simulators:
            submit_tasks.append(
                workflow.execute_activity(
                    submit_simulation_activity,
                    args=[SubmitSimulationInput(
                        omex_file=workflow_input.omex_file,
                        simulator_version=sim,
                        cache_buster=workflow_input.cache_buster,
                    )],
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            )

        submit_results: list[SubmitSimulationOutput | BaseException] = await asyncio.gather(
            *submit_tasks, return_exceptions=True)

        # Update job statuses with run IDs from submit phase
        for job_id, sim, result in zip(workflow_input.job_ids, workflow_input.simulators, submit_results):
            if isinstance(result, BaseException):
                self.job_statuses[job_id].status = "failure"
                self.job_statuses[job_id].error = str(result)
            elif result.biosimulations_run_id is not None:
                self.job_statuses[job_id].biosimulations_run_id = result.biosimulations_run_id

        workflow.logger.info("Submit phase complete, starting poll phase.")

        # Phase 2: Poll for completion in parallel (only for successfully submitted jobs)
        poll_tasks = []
        poll_job_ids = []
        for job_id, sim, result in zip(workflow_input.job_ids, workflow_input.simulators, submit_results):
            if isinstance(result, BaseException):
                continue
            if result.biosimulations_run_id is None:
                self.job_statuses[job_id].status = "failure"
                self.job_statuses[job_id].error = "No biosimulations run ID returned"
                continue

            if result.cached:
                # Already completed successfully from cache
                self.job_statuses[job_id].status = "success"
                continue

            poll_job_ids.append(job_id)
            poll_tasks.append(
                workflow.execute_activity(
                    poll_simulation_activity,
                    args=[PollSimulationInput(
                        workflow_id=workflow.info().workflow_id,
                        omex_file=workflow_input.omex_file,
                        simulator_version=sim,
                        cache_buster=workflow_input.cache_buster,
                        biosimulations_run_id=result.biosimulations_run_id,
                    )],
                    start_to_close_timeout=timedelta(minutes=20),
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            )

        if poll_tasks:
            poll_results = await asyncio.gather(*poll_tasks, return_exceptions=True)
            for job_id, poll_result in zip(poll_job_ids, poll_results):
                if isinstance(poll_result, BaseException):
                    self.job_statuses[job_id].status = "failure"
                    self.job_statuses[job_id].error = str(poll_result)
                elif (poll_result.biosim_run is not None
                      and poll_result.biosim_run.status == BiosimSimulationRunStatus.SUCCEEDED):
                    self.job_statuses[job_id].status = "success"
                else:
                    self.job_statuses[job_id].status = "failure"
                    error_msg = poll_result.biosim_run.error_message if poll_result.biosim_run else "Unknown error"
                    self.job_statuses[job_id].error = error_msg

        return self.get_status()
