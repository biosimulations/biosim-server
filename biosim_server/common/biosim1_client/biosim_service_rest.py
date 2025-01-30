import logging
import os
from pathlib import Path
from typing import AsyncGenerator

import aiofiles
import aiohttp
from aiocache import SimpleMemoryCache, cached  # type: ignore
from aiohttp import FormData
from typing_extensions import override

from biosim_server.common.biosim1_client.biosim_service import BiosimService
from biosim_server.common.biosim1_client.models import BiosimSimulationRun, BiosimSimulationRunApiRequest, HDF5File, \
    Hdf5DataValues, BiosimSimulationRunStatus, BiosimSimulatorSpec
from biosim_server.common.database.data_models import BiosimulatorVersion, DockerContainerInfo
from biosim_server.config import get_settings

logger = logging.getLogger(__name__)


class BiosimServiceRest(BiosimService):
    @override
    async def get_sim_run(self, simulation_run_id: str) -> BiosimSimulationRun:
        """ raises ClientResponseError if the response status is not 2xx """
        api_base_url = os.environ.get('API_BASE_URL') or "https://api.biosimulations.org"
        assert (api_base_url is not None)

        async with aiohttp.ClientSession() as session:
            async with session.get(api_base_url + "/runs/" + simulation_run_id) as resp:
                resp.raise_for_status()
                res = await resp.json()

        sim_run = BiosimSimulationRun(id=res["id"], name=res["name"], simulator=res['simulator'],
                                      simulatorVersion=res['simulatorVersion'], simulatorDigest=res['simulatorDigest'],
                                      status=BiosimSimulationRunStatus(res['status']))

        return sim_run

    @override
    async def run_biosim_sim(self, local_omex_path: str, omex_name: str,
                             simulator_spec: BiosimSimulatorSpec) -> BiosimSimulationRun:
        """
        This function runs the project on biosimulations.
        """
        api_base_url = get_settings().biosimulations_api_base_url

        simulation_run_request = BiosimSimulationRunApiRequest(name=omex_name, simulator=simulator_spec.simulator,
                                                               simulatorVersion=simulator_spec.version or "latest",
                                                               maxTime=600, )

        print(local_omex_path)
        async with aiohttp.ClientSession() as session:
            with Path(local_omex_path).open('rb') as f:
                data = FormData()
                data.add_field(name='file', value=f, filename='omex.omex', content_type='multipart/form-data')
                data.add_field(name='simulationRun', value=simulation_run_request.model_dump_json(),
                               content_type='multipart/form-data')

                async with session.post(url=api_base_url + '/runs', data=data) as resp:
                    resp.raise_for_status()
                    res = await resp.json()

        if simulator_spec.version is None:
            simulator_spec.version = res['simulatorVersion']

        sim_run = BiosimSimulationRun(id=res["id"], name=res["name"], simulator=res['simulator'],
                                      simulatorVersion=res['simulatorVersion'], simulatorDigest=res['simulatorDigest'],
                                      status=BiosimSimulationRunStatus(res['status']))

        # logger.info("Submitted " + omex_name + " on biosimulations with simulation id: " + sim_run.id)
        # logger.info("View:", api_base_url + "/runs/" + sim_run.id)
        return sim_run

    @override
    async def get_hdf5_metadata(self, simulation_run_id: str) -> HDF5File:
        api_base_url = get_settings().simdata_api_base_url
        assert (api_base_url is not None)

        async with aiohttp.ClientSession() as session:
            url = f"{api_base_url}/datasets/{simulation_run_id}/metadata"
            async with session.get(url) as resp:
                resp.raise_for_status()
                hdf5_metadata_json = await resp.text()
                hdf5_file: HDF5File = HDF5File.model_validate_json(hdf5_metadata_json)
                return hdf5_file

    @override
    async def get_hdf5_data(self, simulation_run_id: str, dataset_name: str) -> Hdf5DataValues:
        api_base_url = get_settings().simdata_api_base_url
        assert (api_base_url is not None)

        async with aiohttp.ClientSession() as session:
            url = f"{api_base_url}/datasets/{simulation_run_id}/data"
            async with session.get(url, params={"dataset_name": dataset_name}) as resp:
                resp.raise_for_status()
                hdf5_data_dict = await resp.json()
                logger.info(f"Got data for dataset: {dataset_name}")
                hdf5_data_values = Hdf5DataValues(shape=hdf5_data_dict['shape'], values=hdf5_data_dict['values'])
                return hdf5_data_values

    @override
    @cached(ttl=3600, cache=SimpleMemoryCache)  # type: ignore
    async def get_simulation_versions(self) -> list[BiosimulatorVersion]:
        api_base_url = get_settings().biosimulators_api_base_url
        assert (api_base_url is not None)

        async with aiohttp.ClientSession() as session:
            url = f"{api_base_url}/simulators?includeTests=false"
            async with session.get(url) as resp:
                resp.raise_for_status()
                simulation_versions_dict = await resp.json()
                simulation_versions: list[BiosimulatorVersion] = []
                for sim in simulation_versions_dict:
                    if 'image' in sim and 'url' and sim['image'] and 'url' in sim['image'] and 'digest' in sim['image']:
                        container_info = DockerContainerInfo(url=sim["image"]["url"], digest=sim["image"]["digest"])
                        sim_version = BiosimulatorVersion(id=sim["id"], name=sim["name"], version=sim["version"],
                                                          image=container_info)
                        simulation_versions.append(sim_version)
                return simulation_versions

    @override
    async def close(self) -> None:
        pass


async def file_sender(file_name: str) -> AsyncGenerator[bytes, None]:
    async with aiofiles.open(file_name, 'rb') as f:
        chunk = await f.read(64 * 1024)
        while chunk:
            yield chunk
            chunk = await f.read(64 * 1024)
