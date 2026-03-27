import asyncio
import logging
from datetime import timedelta
from typing import Any, Coroutine

from pydantic import BaseModel
from temporalio import workflow
from temporalio.workflow import ChildWorkflowHandle

from biosim_server.biosim_omex import OmexFile
from biosim_server.biosim_runs import BiosimulatorVersion, OmexSimWorkflow, OmexSimWorkflowInput, OmexSimWorkflowOutput, \
    BiosimulatorWorkflowRun
from biosim_server.biosim_verify import CompareSettings
from biosim_server.biosim_verify.models import VerifyWorkflowStatus, VerifyWorkflowOutput
from biosim_server.biosim_verify.runs_verify_workflow import generate_statistics


class OmexVerifyWorkflowInput(BaseModel):
    omex_file: OmexFile
    requested_simulators: list[BiosimulatorVersion]
    cache_buster: str
    compare_settings: CompareSettings


@workflow.defn
class OmexVerifyWorkflow:
    verify_input: OmexVerifyWorkflowInput
    verify_output: VerifyWorkflowOutput

    @workflow.init
    def __init__(self, verify_input: OmexVerifyWorkflowInput) -> None:
        self.verify_input = verify_input
        # assert verify_input.workflow_id == workflow.info().workflow_id
        self.verify_output = VerifyWorkflowOutput(
            workflow_id=workflow.info().workflow_id,
            compare_settings=verify_input.compare_settings,
            workflow_run_id=workflow.info().run_id,
            workflow_status=VerifyWorkflowStatus.IN_PROGRESS,
            timestamp=str(workflow.now()))

    @workflow.query(name="get_output")
    def get_omex_sim_workflow_output(self) -> VerifyWorkflowOutput:
        return self.verify_output

    @workflow.run
    async def run(self, verify_input: OmexVerifyWorkflowInput) -> VerifyWorkflowOutput:
        workflow.logger.setLevel(level=logging.INFO)
        workflow.logger.info("Main workflow started.")

        # Launch child workflows to run a simulation for each simulator (or retrieve from cache)
        child_workflows: list[
            Coroutine[Any, Any, ChildWorkflowHandle[OmexSimWorkflowInput, OmexSimWorkflowOutput]]] = []
        for simulator_spec in verify_input.requested_simulators:
            child_workflows.append(
                workflow.start_child_workflow(OmexSimWorkflow.run,  # type: ignore
                                              args=[OmexSimWorkflowInput(omex_file=verify_input.omex_file,
                                                                         simulator_version=simulator_spec,
                                                                         cache_buster=verify_input.cache_buster)],
                                              result_type=OmexSimWorkflowOutput,
                                              task_queue="verification_tasks", execution_timeout=timedelta(minutes=10), ))

        workflow.logger.info(f"waiting for {len(child_workflows)} child simulation workflows.")
        # Wait for all child workflows to complete
        child_results: list[ChildWorkflowHandle[OmexSimWorkflowInput, OmexSimWorkflowOutput]] = await asyncio.gather(
            *child_workflows)

        simulator_workflow_runs: list[BiosimulatorWorkflowRun] = []
        for child_result in child_results:
            omex_sim_workflow_output = await child_result
            if not child_result.done():
                raise Exception(
                    "Child workflow did not complete successfully, even after asyncio.gather on all workflows")

            if omex_sim_workflow_output.biosimulator_workflow_run is None:
                continue
            simulator_workflow_runs.append(omex_sim_workflow_output.biosimulator_workflow_run)

        # Generate comparison report within an activity
        workflow.logger.info("calling activity to generate statistics")
        stats = await generate_statistics(sim_workflow_runs=simulator_workflow_runs, compare_settings=self.verify_input.compare_settings)

        self.verify_output.workflow_results = stats
        self.verify_output.workflow_status = VerifyWorkflowStatus.COMPLETED
        return self.verify_output
