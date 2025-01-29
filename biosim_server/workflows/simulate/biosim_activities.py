import logging
import os
from typing import Optional

from aiohttp import ClientResponseError
from pydantic import BaseModel
from temporalio import activity

from biosim_server.common.biosim1_client import BiosimService, BiosimServiceRest, SourceOmex, BiosimSimulatorSpec, \
    BiosimSimulationRun, BiosimSimulationRunStatus, HDF5File, Hdf5DataValues
from biosim_server.common.storage import FileService
from biosim_server.dependencies import get_file_service, get_biosim_service


class GetSimRunInput(BaseModel):
    biosim_run_id: str
    abort_on_not_found: Optional[bool] = False


@activity.defn
async def get_sim_run(get_sim_run_input: GetSimRunInput) -> BiosimSimulationRun:
    activity.logger.setLevel(logging.INFO)
    biosim_service = BiosimServiceRest()
    try:
        biosim_sim_run: BiosimSimulationRun = await biosim_service.get_sim_run(get_sim_run_input.biosim_run_id)
        return biosim_sim_run
    except ClientResponseError as e:
        if e.status == 404:
            activity.logger.warn(f"Simulation run with id {get_sim_run_input.biosim_run_id} not found.", exc_info=e)
            if get_sim_run_input.abort_on_not_found:
                # return a failed simulation run rather than raising an exception to avoid retrying the activity
                return BiosimSimulationRun(
                    id=get_sim_run_input.biosim_run_id,
                    name="",
                    simulator="",
                    simulatorVersion="",
                    status=BiosimSimulationRunStatus.RUN_ID_NOT_FOUND
                )
        raise e


class SubmitBiosimSimInput(BaseModel):
    source_omex: SourceOmex
    simulator_spec: BiosimSimulatorSpec


@activity.defn
async def submit_biosim_sim(input: SubmitBiosimSimInput) -> BiosimSimulationRun:
    activity.logger.setLevel(logging.INFO)
    biosim_service: BiosimService | None = get_biosim_service()
    if biosim_service is None:
        raise Exception("Biosim service is not initialized")
    file_service: FileService | None = get_file_service()
    if file_service is None:
        raise Exception("File service is not initialized")
    (_, local_omex_path) = await file_service.download_file(input.source_omex.omex_s3_file)
    simulation_run = await biosim_service.run_biosim_sim(local_omex_path, input.source_omex.name,
                                                         input.simulator_spec)
    os.remove(local_omex_path)
    return simulation_run


class GetHdf5MetadataInput(BaseModel):
    simulation_run_id: str


@activity.defn
async def get_hdf5_metadata(input: GetHdf5MetadataInput) -> HDF5File:
    activity.logger.setLevel(logging.INFO)
    biosim_service = BiosimServiceRest()
    hdf5_file: HDF5File = await biosim_service.get_hdf5_metadata(input.simulation_run_id)
    return hdf5_file


class GetHdf5DataInput(BaseModel):
    simulation_run_id: str
    dataset_name: str


@activity.defn
async def get_hdf5_data(get_input: GetHdf5DataInput) -> Hdf5DataValues:
    activity.logger.setLevel(logging.INFO)
    biosim_service = BiosimServiceRest()
    hdf5_data_values: Hdf5DataValues = await biosim_service.get_hdf5_data(simulation_run_id=get_input.simulation_run_id,
                                                                          dataset_name=get_input.dataset_name)
    return hdf5_data_values
