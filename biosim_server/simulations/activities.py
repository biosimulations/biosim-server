"""Activities for the simulation run workflow.

Split into submit and poll phases so the parent workflow can capture
the biosimulations_run_id immediately after submission.
"""

import asyncio
import logging
import os

from aiohttp import ClientResponseError
from pydantic import BaseModel
from temporalio import activity

from biosim_server.biosim_omex import OmexFile
from biosim_server.biosim_runs.models import (
    BiosimSimulationRun,
    BiosimSimulationRunStatus,
    BiosimulatorVersion,
    BiosimulatorWorkflowRun,
    HDF5File,
)
from biosim_server.common.storage import FileService
from biosim_server.dependencies import get_biosim_service, get_database_service, get_file_service


class SubmitSimulationInput(BaseModel):
    omex_file: OmexFile
    simulator_version: BiosimulatorVersion
    cache_buster: str


class SubmitSimulationOutput(BaseModel):
    biosimulations_run_id: str | None = None
    cached: bool = False
    source: str  # "submitted" or "cached"


@activity.defn
async def submit_simulation_activity(input: SubmitSimulationInput) -> SubmitSimulationOutput:
    """Submit simulation to biosimulations.org and return the run ID immediately."""
    activity.logger.setLevel(logging.INFO)

    # Check cache first
    database_service = get_database_service()
    assert database_service is not None
    cached_runs = await database_service.get_biosimulator_workflow_runs(
        file_hash_md5=input.omex_file.file_hash_md5,
        image_digest=input.simulator_version.image_digest,
        cache_buster=input.cache_buster,
    )
    if (len(cached_runs) > 0 and cached_runs[0].biosim_run is not None
            and cached_runs[0].biosim_run.status == BiosimSimulationRunStatus.SUCCEEDED):
        activity.logger.info(f"Cache hit for {input.simulator_version.id}:{input.simulator_version.version}")
        return SubmitSimulationOutput(
            biosimulations_run_id=cached_runs[0].biosim_run.id,
            cached=True,
            source="cached",
        )

    # Submit to biosimulations.org
    biosim_service = get_biosim_service()
    if biosim_service is None:
        raise Exception("Biosim service is not initialized")
    file_service: FileService | None = get_file_service()
    if file_service is None:
        raise Exception("File service is not initialized")

    (_gcs_path, local_omex_path) = await file_service.download_file(gcs_path=input.omex_file.omex_gcs_path)
    activity.logger.info(f"Downloaded OMEX file to {local_omex_path}")

    simulation_run = await biosim_service.run_biosim_sim(
        local_omex_path=local_omex_path,
        omex_name=input.omex_file.uploaded_filename,
        simulator_version=input.simulator_version,
    )
    os.remove(local_omex_path)

    activity.logger.info(f"Submitted {input.simulator_version.id}:{input.simulator_version.version}, "
                         f"biosimulations_run_id={simulation_run.id}")
    return SubmitSimulationOutput(
        biosimulations_run_id=simulation_run.id,
        cached=False,
        source="submitted",
    )


class PollSimulationInput(BaseModel):
    workflow_id: str
    omex_file: OmexFile
    simulator_version: BiosimulatorVersion
    cache_buster: str
    biosimulations_run_id: str


@activity.defn
async def poll_simulation_activity(input: PollSimulationInput) -> BiosimulatorWorkflowRun:
    """Poll biosimulations.org for completion, fetch HDF5, save to DB."""
    activity.logger.setLevel(logging.INFO)

    biosim_service = get_biosim_service()
    if biosim_service is None:
        raise Exception("Biosim service is not initialized")
    database_service = get_database_service()
    assert database_service is not None

    # Poll until complete
    simulation_run: BiosimSimulationRun = await biosim_service.get_sim_run(input.biosimulations_run_id)
    while simulation_run.status not in [BiosimSimulationRunStatus.SUCCEEDED, BiosimSimulationRunStatus.FAILED,
                                        BiosimSimulationRunStatus.RUN_ID_NOT_FOUND]:
        await asyncio.sleep(3)
        activity.heartbeat("Polling simulation run status")
        simulation_run = await biosim_service.get_sim_run(input.biosimulations_run_id)

    # Fetch HDF5 metadata with retries (simdata API can lag)
    hdf5_file: HDF5File | None = None
    if simulation_run.status == BiosimSimulationRunStatus.SUCCEEDED:
        max_retries = 10
        for attempt in range(max_retries):
            try:
                hdf5_file = await biosim_service.get_hdf5_metadata(simulation_run.id)
                break
            except ClientResponseError as e:
                if e.status == 404 and attempt < max_retries - 1:
                    activity.logger.info(f"HDF5 metadata not yet available for run {simulation_run.id}, "
                                         f"retrying in 10s (attempt {attempt + 1}/{max_retries})")
                    activity.heartbeat("Waiting for HDF5 metadata")
                    await asyncio.sleep(10)
                else:
                    raise e

    # Save to DB
    biosim_workflow_run = BiosimulatorWorkflowRun(
        workflow_id=input.workflow_id,
        file_hash_md5=input.omex_file.file_hash_md5,
        image_digest=input.simulator_version.image_digest,
        cache_buster=input.cache_buster,
        omex_file=input.omex_file,
        simulator_version=input.simulator_version,
        biosim_run=simulation_run,
        hdf5_file=hdf5_file,
    )
    saved = await database_service.insert_biosimulator_workflow_run(sim_workflow_run=biosim_workflow_run)
    activity.logger.info(f"Saved BiosimulatorWorkflowRun _id={saved.database_id}")
    return saved
