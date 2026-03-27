import asyncio
import logging
from pathlib import Path

import pytest
from biosim_server.api.main import app
from biosim_server.biosim_omex import OmexDatabaseServiceMongo
from biosim_server.biosim_runs import BiosimServiceRest, DatabaseServiceMongo
from biosim_server.biosim_verify.omex_verify_workflow import OmexVerifyWorkflowInput
from biosim_server.biosim_verify.runs_verify_workflow import RunsVerifyWorkflowInput
from biosim_server.biosim_verify.models import VerifyWorkflowOutput, VerifyWorkflowStatus
from biosim_server.common.storage import FileServiceGCS
from biosim_server.config import get_settings
from biosim_server.version import __version__
from httpx import ASGITransport, AsyncClient
from temporalio.client import Client
from temporalio.worker import Worker
from tests.biosim_verify.test_omex_verify_workflows import assert_omex_verify_results
from tests.biosim_verify.test_runs_verify_workflow import assert_runs_verify_results


@pytest.mark.asyncio
async def test_root() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        response = await test_client.get("/")
        assert response.status_code == 200
        assert response.json() == {'docs': 'https://biosim.biosimulations.org/docs', 'version': __version__ }


@pytest.mark.asyncio
async def test_version() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        response = await test_client.get("/version")
        assert response.status_code == 200
        assert response.json() == __version__


@pytest.mark.asyncio
async def test_get_output_not_found(omex_verify_workflow_input: OmexVerifyWorkflowInput,
                                    omex_verify_workflow_output: VerifyWorkflowOutput) -> None:

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        # test with non-existent verification_id
        response = await test_client.get(f"/verify_omex/non-existent-id")
        assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.skipif(len(get_settings().storage_gcs_credentials_file) == 0,
                    reason="gcs_credentials.json file not supplied")
@pytest.mark.asyncio
async def test_omex_verify_and_get_output(omex_verify_workflow_input: OmexVerifyWorkflowInput,
                                         omex_verify_workflow_output: VerifyWorkflowOutput,
                                         omex_test_file: Path,
                                         database_service_mongo: DatabaseServiceMongo,
                                         omex_database_service_mongo: OmexDatabaseServiceMongo,
                                         file_service_gcs: FileServiceGCS,
                                         temporal_client: Client,
                                         temporal_verify_worker: Worker,
                                         biosim_service_rest: BiosimServiceRest) -> None:
    assert omex_verify_workflow_input.compare_settings.observables is not None
    query_params: dict[str, float | str | list[str]] = {
        "workflow_id_prefix": "verification-",
        "simulators": [f"{sim.id}:{sim.version}" for sim in omex_verify_workflow_input.requested_simulators],
        "include_outputs": omex_verify_workflow_input.compare_settings.include_outputs,
        "user_description": omex_verify_workflow_input.compare_settings.user_description,
        "observables": omex_verify_workflow_input.compare_settings.observables,
        "rel_tol": omex_verify_workflow_input.compare_settings.rel_tol,
        "abs_tol_min": omex_verify_workflow_input.compare_settings.abs_tol_min,
        "abs_tol_scale": omex_verify_workflow_input.compare_settings.abs_tol_scale
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        with open(omex_test_file, "rb") as file:
            upload_filename = omex_test_file.name
            files = {"uploaded_file": (upload_filename, file, "application/zip")}
            response = await test_client.post("/verify/omex", files=files, params=query_params)
            assert response.status_code == 200

        output = VerifyWorkflowOutput.model_validate(response.json())

        # poll api until job is completed
        while output.workflow_status != VerifyWorkflowStatus.COMPLETED:
            await asyncio.sleep(5)
            response = await test_client.get(f"/verify/{output.workflow_id}")
            if response.status_code == 200:
                output = VerifyWorkflowOutput.model_validate(response.json())
                logging.info(f"polling, job status is: {output.workflow_status}")

        assert_omex_verify_results(observed_results=output, expected_results_template=omex_verify_workflow_output)


@pytest.mark.skipif(len(get_settings().storage_gcs_credentials_file) == 0,
                    reason="gcs_credentials.json file not supplied")
@pytest.mark.asyncio
async def test_runs_verify_and_get_output(runs_verify_workflow_input: RunsVerifyWorkflowInput,
                                         runs_verify_workflow_output: VerifyWorkflowOutput,
                                         omex_test_file: Path,
                                         file_service_gcs: FileServiceGCS,
                                         database_service_mongo: DatabaseServiceMongo,
                                         omex_database_service_mongo: OmexDatabaseServiceMongo,
                                         temporal_client: Client,
                                         temporal_verify_worker: Worker,
                                         biosim_service_rest: BiosimServiceRest) -> None:
    assert runs_verify_workflow_input.compare_settings.observables is not None
    query_params: dict[str, float | str | list[str]] = {
        "workflow_id_prefix": "verification-",
        "biosimulations_run_ids": runs_verify_workflow_input.biosimulations_run_ids,
        "include_outputs": runs_verify_workflow_input.compare_settings.include_outputs,
        "user_description": runs_verify_workflow_input.compare_settings.user_description,
        "observables": runs_verify_workflow_input.compare_settings.observables,
        "rel_tol": runs_verify_workflow_input.compare_settings.rel_tol,
        "abs_tol_min": runs_verify_workflow_input.compare_settings.abs_tol_min,
        "abs_tol_scale": runs_verify_workflow_input.compare_settings.abs_tol_scale
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        with open(omex_test_file, "rb") as file:
            response = await test_client.post("/verify/runs", params=query_params)
            assert response.status_code == 200

        output = VerifyWorkflowOutput.model_validate(response.json())

        # poll api until job is completed
        while output.workflow_status != VerifyWorkflowStatus.COMPLETED:
            await asyncio.sleep(5)
            response = await test_client.get(f"/verify/{output.workflow_id}")
            if response.status_code == 200:
                output = VerifyWorkflowOutput.model_validate(response.json())
                logging.info(f"polling workflow_id {output.workflow_id}, workflow status is: {output.workflow_status}")

        assert_runs_verify_results(observed_results=output, expected_results_template=runs_verify_workflow_output)


@pytest.mark.skipif(len(get_settings().storage_gcs_credentials_file) == 0,
                    reason="gcs_credentials.json file not supplied")
@pytest.mark.asyncio
async def test_runs_verify_not_found(runs_verify_workflow_input: RunsVerifyWorkflowInput,
                                         runs_verify_workflow_output: VerifyWorkflowOutput,
                                         omex_test_file: Path,
                                         file_service_gcs: FileServiceGCS,
                                         database_service_mongo: DatabaseServiceMongo,
                                         temporal_client: Client,
                                         temporal_verify_worker: Worker,
                                         biosim_service_rest: BiosimServiceRest) -> None:
    assert runs_verify_workflow_input.compare_settings.observables is not None
    query_params: dict[str, float | str | list[str]] = {
        "workflow_id_prefix": "verification-",
        "biosimulations_run_ids": ["bad_run_id_1", "bad_run_id_2"],
        "include_outputs": runs_verify_workflow_input.compare_settings.include_outputs,
        "user_description": runs_verify_workflow_input.compare_settings.user_description,
        "observables": runs_verify_workflow_input.compare_settings.observables,
        "rel_tol": runs_verify_workflow_input.compare_settings.rel_tol,
        "abs_tol_min": runs_verify_workflow_input.compare_settings.abs_tol_min,
        "abs_tol_scale": runs_verify_workflow_input.compare_settings.abs_tol_scale
    }

    async with (AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client):
        with open(omex_test_file, "rb") as file:
            response = await test_client.post("/verify/runs", params=query_params)
            assert response.status_code == 200

        output = VerifyWorkflowOutput.model_validate(response.json())

        # poll api until job is completed
        while not output.workflow_status.is_done:
            await asyncio.sleep(5)
            response = await test_client.get(f"/verify/{output.workflow_id}")
            if response.status_code == 200:
                output = VerifyWorkflowOutput.model_validate(response.json())
                logging.info(f"polling, job status is: {output.workflow_status}")

        assert output.workflow_status == VerifyWorkflowStatus.RUN_ID_NOT_FOUND
        assert output.workflow_error in [ "Simulation run with id bad_run_id_1 not found.",
                                          "Simulation run with id bad_run_id_2 not found."]
