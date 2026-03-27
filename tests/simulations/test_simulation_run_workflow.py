"""Integration test for SimulationRunWorkflow — actually calls biosimulations.org."""

import logging
import uuid
from pathlib import Path

import pytest
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import Worker

from biosim_server.biosim_omex import get_cached_omex_file_from_local, OmexDatabaseService
from biosim_server.biosim_runs import BiosimServiceRest, BiosimulatorVersion, DatabaseService
from biosim_server.common.storage import FileServiceGCS
from biosim_server.config import get_settings
from biosim_server.simulations.models import ConglomerateStatus
from biosim_server.simulations.workflow import SimulationRunWorkflow, SimulationRunWorkflowInput


@pytest.mark.integration
@pytest.mark.skipif(len(get_settings().storage_gcs_credentials_file) == 0,
                    reason="gcs_credentials.json file not supplied")
@pytest.mark.asyncio
async def test_simulation_run_workflow(
    temporal_client: Client,
    temporal_verify_worker: Worker,
    biosim_service_rest: BiosimServiceRest,
    file_service_gcs: FileServiceGCS,
    database_service_mongo: DatabaseService,
    omex_database_service_mongo: OmexDatabaseService,
    omex_test_file: Path,
    simulator_version_copasi: BiosimulatorVersion,
    simulator_version_tellurium: BiosimulatorVersion,
) -> None:
    """Run SimulationRunWorkflow with real biosimulations.org calls.

    Uploads the test OMEX to GCS, starts a SimulationRunWorkflow with
    copasi and tellurium, and verifies the conglomerate status.
    """
    # Upload OMEX file to GCS and register in database
    omex_file = await get_cached_omex_file_from_local(
        file_service=file_service_gcs,
        omex_database=omex_database_service_mongo,
        omex_file=omex_test_file,
        filename=omex_test_file.name,
    )
    await file_service_gcs.upload_file(file_path=omex_test_file, gcs_path=omex_file.omex_gcs_path)
    logging.info(f"Stored test omex file at {omex_file.omex_gcs_path}")

    simulators = [simulator_version_copasi, simulator_version_tellurium]
    job_ids = [uuid.uuid4().hex for _ in simulators]
    workflow_id = f"sim-run-test-{uuid.uuid4().hex}"

    workflow_input = SimulationRunWorkflowInput(
        omex_file=omex_file,
        simulators=simulators,
        job_ids=job_ids,
        cache_buster=uuid.uuid4().hex,  # unique to avoid hitting cache
    )

    # Execute the workflow (blocks until complete)
    result: ConglomerateStatus = await temporal_client.execute_workflow(
        SimulationRunWorkflow.run,
        args=[workflow_input],
        id=workflow_id,
        task_queue="verification_tasks",
        retry_policy=RetryPolicy(maximum_attempts=1),
    )

    assert result is not None
    assert result.processing_id == workflow_id
    assert len(result.jobs) == 2

    for job in result.jobs:
        logging.info(f"Job {job.job_id}: simulator={job.simulator_id}:{job.version} "
                     f"status={job.status} error={job.error} "
                     f"biosim_run_id={job.biosimulations_run_id}")
        assert job.status in ("success", "failure")
        if job.status == "success":
            assert job.biosimulations_run_id is not None
        if job.status == "failure":
            assert job.error is not None

    # At least one simulator should succeed
    successful_jobs = [j for j in result.jobs if j.status == "success"]
    assert len(successful_jobs) >= 1, (
        f"Expected at least one successful job, got: "
        f"{[(j.simulator_id, j.status, j.error) for j in result.jobs]}"
    )
