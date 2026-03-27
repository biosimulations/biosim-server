import asyncio
import logging
import os
from typing import Optional

from aiohttp import ClientResponseError
from pydantic import BaseModel
from temporalio import activity

from biosim_server.biosim_omex import OmexFile, get_cached_omex_file_from_raw
from biosim_server.biosim_runs.biosim_service import BiosimService, BiosimServiceRest
from biosim_server.biosim_runs.models import BiosimSimulationRun, BiosimulatorVersion, BiosimSimulationRunStatus, \
    BiosimulatorWorkflowRun, HDF5File
from biosim_server.common.storage import FileService
from biosim_server.dependencies import get_file_service, get_biosim_service, get_database_service, \
    get_omex_database_service


class GetExistingBiosimSimulationRunActivityInput(BaseModel):
    workflow_id: str
    biosim_run_id: str
    abort_on_not_found: Optional[bool] = False


class GetExistingBiosimSimulationRunActivityOutput(BaseModel):
    status: BiosimSimulationRunStatus
    biosim_workflow_run: Optional[BiosimulatorWorkflowRun] = None
    error_message: Optional[str] = None


@activity.defn
async def get_existing_biosim_simulation_run_activity(input: GetExistingBiosimSimulationRunActivityInput) -> GetExistingBiosimSimulationRunActivityOutput:
    try:
        activity.logger.setLevel(logging.INFO)

        # if already saved in the database, return the biosimulator workflow run
        database_service = get_database_service()
        assert database_service is not None
        biosim_workflow_runs: list[BiosimulatorWorkflowRun] = await database_service.get_biosimulator_workflow_runs_by_biosim_runid(biosim_run_id=input.biosim_run_id)
        if len(biosim_workflow_runs) > 0 and biosim_workflow_runs[0].biosim_run is not None:
            activity.logger.info(f"returning cached BiosimulatorWorkflowRun _id={biosim_workflow_runs[0].database_id}")
            return GetExistingBiosimSimulationRunActivityOutput(
                status=biosim_workflow_runs[0].biosim_run.status,
                biosim_workflow_run=biosim_workflow_runs[0])

        # not found in database, retrieve the simulation run from biosimulations.org
        biosim_service = get_biosim_service()
        if biosim_service is None:
            raise Exception("Biosim service is not initialized")

        try:
            simulation_run: BiosimSimulationRun = await biosim_service.get_sim_run(input.biosim_run_id)
        except ClientResponseError as e:
            if e.status == 404:
                activity.logger.warn(f"Simulation run with id {input.biosim_run_id} not found.", exc_info=e)
                if input.abort_on_not_found:
                    # return a failed simulation run rather than raising an exception to avoid retrying the activity
                    return GetExistingBiosimSimulationRunActivityOutput(
                        error_message=f"Simulation run with run_id {input.biosim_run_id} not found.",
                        status=BiosimSimulationRunStatus.RUN_ID_NOT_FOUND,
                        biosim_workflow_run=None)
            raise e

        #
        # create the OmexFile locally (with hash) and save it to the database
        #
        file_service = get_file_service()
        if file_service is None:
            raise Exception("File service is not initialized")
        omex_database_service = get_omex_database_service()
        if omex_database_service is None:
            raise Exception("Omex database service is not initialized")
        biosimulations_omex_path = f"simulations/{simulation_run.id}/archive.omex"
        content: bytes | None = await file_service.get_file_contents(biosimulations_omex_path)
        if content is None:
            raise FileNotFoundError(f"Could not find file for run_id {simulation_run.id}")
        omex_file = await get_cached_omex_file_from_raw(file_service=file_service, omex_database=omex_database_service,
                                                        omex_file_contents=content,
                                                        filename=biosimulations_omex_path.replace("/", "_"))


        # retrieve the HDF5File from the completed run
        biosim_service = BiosimServiceRest()
        hdf5_file: HDF5File = await biosim_service.get_hdf5_metadata(simulation_run.id)

        # save the simulation run in the database
        cache_buster = f"imported biosimulations run_id {simulation_run.id}"
        biosim_workflow_run = BiosimulatorWorkflowRun(
            workflow_id=input.workflow_id,
            file_hash_md5=omex_file.file_hash_md5,
            image_digest=simulation_run.simulator_version.image_digest,
            cache_buster=cache_buster,
            omex_file=omex_file,
            simulator_version=simulation_run.simulator_version,
            biosim_run=simulation_run,
            hdf5_file=hdf5_file)

        save_biosimulator_workflow_run = await database_service.insert_biosimulator_workflow_run(sim_workflow_run=biosim_workflow_run)
        activity.logger.info(f"returning newly saved BiosimulatorWorkflowRun _id={save_biosimulator_workflow_run.database_id}")
        return GetExistingBiosimSimulationRunActivityOutput(biosim_workflow_run=save_biosimulator_workflow_run,
                                                            status=simulation_run.status, error_message=None)
    except Exception as e:
        activity.logger.exception(f"Failed to get existing biosim simulation run: {str(e)}", exc_info=e)
        raise e


class SubmitBiosimSimulationRunActivityInput(BaseModel):
    workflow_id: str
    omex_file: OmexFile
    simulator_version: BiosimulatorVersion
    cache_buster: str


@activity.defn
async def submit_biosim_simulation_run_activity(input: SubmitBiosimSimulationRunActivityInput) -> BiosimulatorWorkflowRun:
    try:
        activity.logger.setLevel(logging.INFO)

        # if already saved in the database, return the biosimulator workflow run
        database_service = get_database_service()
        assert database_service is not None
        biosim_workflow_runs: list[BiosimulatorWorkflowRun] = await database_service.get_biosimulator_workflow_runs(
            file_hash_md5=input.omex_file.file_hash_md5, image_digest=input.simulator_version.image_digest,
            cache_buster=input.cache_buster)
        if (len(biosim_workflow_runs) > 0 and biosim_workflow_runs[0].biosim_run is not None
                and biosim_workflow_runs[0].biosim_run.status == BiosimSimulationRunStatus.SUCCEEDED):
            activity.logger.info(f"returning cached BiosimulatorWorkflowRun _id={biosim_workflow_runs[0].database_id}")
            return biosim_workflow_runs[0]

        # not found in database, submit the simulation to biosimulations.org
        biosim_service: BiosimService | None = get_biosim_service()
        if biosim_service is None:
            raise Exception("Biosim service is not initialized")
        file_service: FileService | None = get_file_service()
        if file_service is None:
            raise Exception("File service is not initialized")
        (_gcs_path, local_omex_path) = await file_service.download_file(gcs_path=input.omex_file.omex_gcs_path)
        activity.logger.info(f"Downloaded OMEX file from gcs_path {input.omex_file.omex_gcs_path} to local path {local_omex_path}")
        simulation_run = await biosim_service.run_biosim_sim(local_omex_path=local_omex_path, omex_name=input.omex_file.uploaded_filename,
                                                             simulator_version=input.simulator_version)
        os.remove(local_omex_path)
        activity.logger.info(f"Deleted local OMEX file at {local_omex_path}")

        # poll for the simulation run status until complete
        while simulation_run.status not in [BiosimSimulationRunStatus.SUCCEEDED, BiosimSimulationRunStatus.FAILED,
                                            BiosimSimulationRunStatus.RUN_ID_NOT_FOUND]:
            await asyncio.sleep(3)
            activity.heartbeat("Polling simulation run status")
            simulation_run = await biosim_service.get_sim_run(simulation_run.id)

        # retrieve the HDF5File from the completed run
        # simdata API may lag behind the run status, so retry on 404
        hdf5_file: HDF5File | None = None
        max_hdf5_retries = 10
        for attempt in range(max_hdf5_retries):
            try:
                hdf5_file = await biosim_service.get_hdf5_metadata(simulation_run.id)
                break
            except ClientResponseError as e:
                if e.status == 404 and attempt < max_hdf5_retries - 1:
                    activity.logger.info(f"HDF5 metadata not yet available for run {simulation_run.id}, "
                                         f"retrying in 10s (attempt {attempt + 1}/{max_hdf5_retries})")
                    activity.heartbeat("Waiting for HDF5 metadata")
                    await asyncio.sleep(10)
                else:
                    raise e

        # save the simulation run in the database
        biosim_workflow_run = BiosimulatorWorkflowRun(
            workflow_id=input.workflow_id,
            file_hash_md5=input.omex_file.file_hash_md5,
            image_digest=input.simulator_version.image_digest,
            cache_buster=input.cache_buster,
            omex_file=input.omex_file,
            simulator_version=input.simulator_version,
            biosim_run=simulation_run,
            hdf5_file=hdf5_file)

        save_biosimulator_workflow_run = await database_service.insert_biosimulator_workflow_run(sim_workflow_run=biosim_workflow_run)
        activity.logger.info(f"returning newly saved BiosimulatorWorkflowRun _id={save_biosimulator_workflow_run.database_id}")
        return save_biosimulator_workflow_run
    except Exception as e:
        activity.logger.exception(f"Failed to submit biosim simulation run: {str(e)}", exc_info=e)
        raise e