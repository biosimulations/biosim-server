import asyncio
import logging
from datetime import timedelta
from typing import Any, Coroutine

from pydantic import BaseModel
from temporalio import workflow
from temporalio.exceptions import ChildWorkflowError
from temporalio.workflow import ChildWorkflowHandle

from biosim_server.biosim_omex import OmexFile
from biosim_server.biosim_runs import BiosimulatorVersion, OmexSimWorkflow, OmexSimWorkflowInput, OmexSimWorkflowOutput
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

        child_workflows: list[
            Coroutine[Any, Any, ChildWorkflowHandle[OmexSimWorkflowInput, OmexSimWorkflowOutput]]] = []
        for sim in workflow_input.simulators:
            child_workflows.append(
                workflow.start_child_workflow(
                    OmexSimWorkflow.run,  # type: ignore
                    args=[OmexSimWorkflowInput(
                        omex_file=workflow_input.omex_file,
                        simulator_version=sim,
                        cache_buster=workflow_input.cache_buster,
                    )],
                    result_type=OmexSimWorkflowOutput,
                    task_queue="verification_tasks",
                    execution_timeout=timedelta(minutes=10),
                )
            )

        workflow.logger.info(f"Waiting for {len(child_workflows)} child simulation workflows.")
        child_handles: list[ChildWorkflowHandle[OmexSimWorkflowInput, OmexSimWorkflowOutput]] = await asyncio.gather(
            *child_workflows)

        for job_id, child_handle in zip(workflow_input.job_ids, child_handles):
            try:
                output: OmexSimWorkflowOutput = await child_handle
                if output.workflow_status == "COMPLETED" and output.biosimulator_workflow_run is not None:
                    run = output.biosimulator_workflow_run
                    self.job_statuses[job_id].status = "success"
                    if run.biosim_run is not None:
                        self.job_statuses[job_id].biosimulations_run_id = run.biosim_run.id
                else:
                    self.job_statuses[job_id].status = "failure"
                    self.job_statuses[job_id].error = output.error_message
            except ChildWorkflowError as e:
                self.job_statuses[job_id].status = "failure"
                # Extract root cause from the chain: ChildWorkflowError -> ActivityError -> ApplicationError
                cause: BaseException = e
                while cause.__cause__ is not None:
                    cause = cause.__cause__
                self.job_statuses[job_id].error = str(cause)
            except Exception as e:
                self.job_statuses[job_id].status = "failure"
                self.job_statuses[job_id].error = str(e)

        return self.get_status()
