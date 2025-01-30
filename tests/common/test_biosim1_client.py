import pytest

from biosim_server.common.biosim1_client import BiosimServiceRest
from biosim_server.common.database.data_models import BiosimulatorVersion
from tests.fixtures.biosim_service_mock import BiosimServiceMock


@pytest.mark.asyncio
async def test_get_simulation_versions_rest(biosim_service_rest: BiosimServiceRest) -> None:
    sim_versions: list[BiosimulatorVersion] = await biosim_service_rest.get_simulation_versions()
    vcell_versions = [v for v in sim_versions if v.id == "vcell"]
    assert(len(vcell_versions) > 0)

    assert await biosim_service_rest.get_simulation_versions() == sim_versions
    assert await biosim_service_rest.get_simulation_versions() == sim_versions
    assert await biosim_service_rest.get_simulation_versions() == sim_versions


@pytest.mark.asyncio
async def test_get_simulation_versions_mock(biosim_service_mock: BiosimServiceMock) -> None:
    sim_versions: list[BiosimulatorVersion] = await biosim_service_mock.get_simulation_versions()
    vcell_versions = [v for v in sim_versions if v.id == "vcell"]
    assert(len(vcell_versions) > 0)

    assert await biosim_service_mock.get_simulation_versions() == sim_versions
    assert await biosim_service_mock.get_simulation_versions() == sim_versions
    assert await biosim_service_mock.get_simulation_versions() == sim_versions
