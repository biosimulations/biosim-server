import logging
import uuid
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from biosim_server.biosim_runs import BiosimulatorVersion
from biosim_server.dependencies import get_temporal_client, get_biosim_service, get_omex_database_service
from biosim_server.simulations.models import RunSimulationRequest, ConglomerateStatus, SimulationJobStatus
from biosim_server.simulations.workflow import SimulationRunWorkflow, SimulationRunWorkflowInput

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/simulations", tags=["Simulations"])


@router.post(
    "/run",
    response_model=ConglomerateStatus,
    operation_id="run-simulations",
    dependencies=[Depends(get_temporal_client), Depends(get_biosim_service), Depends(get_omex_database_service)],
    summary="Run simulations for an OMEX archive across selected simulators",
)
async def run_simulations(request: RunSimulationRequest) -> ConglomerateStatus:
    # Look up OMEX file by omex_id (which is the file_hash_md5)
    omex_database = get_omex_database_service()
    if omex_database is None:
        raise HTTPException(status_code=503, detail="OMEX database service not available")
    omex_file = await omex_database.get_omex_file(file_hash_md5=request.omex_id)
    if omex_file is None:
        raise HTTPException(status_code=404, detail=f"OMEX file not found for omex_id: {request.omex_id}")

    # Resolve each SimulatorSelection to a BiosimulatorVersion
    biosim_service = get_biosim_service()
    if biosim_service is None:
        raise HTTPException(status_code=503, detail="Biosim service not available")
    all_simulator_versions = await biosim_service.get_simulator_versions()

    simulator_versions: list[BiosimulatorVersion] = []
    for selection in request.simulators:
        matched: Optional[BiosimulatorVersion] = None
        for sv in all_simulator_versions:
            if sv.id == selection.id and sv.version == selection.version:
                matched = sv
                break
        if matched is None:
            raise HTTPException(
                status_code=400,
                detail=f"Simulator {selection.id}:{selection.version} not found.",
            )
        simulator_versions.append(matched)

    # Generate job IDs and workflow ID
    job_ids = [uuid.uuid4().hex for _ in simulator_versions]
    workflow_id = f"sim-run-{uuid.uuid4()}"

    workflow_input = SimulationRunWorkflowInput(
        omex_file=omex_file,
        simulators=simulator_versions,
        job_ids=job_ids,
        cache_buster="0",
    )

    # Start Temporal workflow
    temporal_client = get_temporal_client()
    if temporal_client is None:
        raise HTTPException(status_code=503, detail="Temporal service not available")

    await temporal_client.start_workflow(
        SimulationRunWorkflow.run,
        args=[workflow_input],
        task_queue="verification_tasks",
        id=workflow_id,
    )
    logger.info(f"Started SimulationRunWorkflow with id {workflow_id}")

    # Return initial status with all jobs as "processing"
    jobs = [
        SimulationJobStatus(
            job_id=job_id,
            simulator_id=sim.id,
            version=sim.version,
            status="processing",
        )
        for job_id, sim in zip(job_ids, simulator_versions)
    ]
    return ConglomerateStatus(processing_id=workflow_id, jobs=jobs)


@router.get(
    "/{processing_id}",
    response_model=ConglomerateStatus,
    operation_id="get-simulation-status",
    dependencies=[Depends(get_temporal_client)],
    summary="Get status of a simulation run",
)
async def get_simulation_status(processing_id: str) -> ConglomerateStatus:
    temporal_client = get_temporal_client()
    if temporal_client is None:
        raise HTTPException(status_code=503, detail="Temporal service not available")

    try:
        workflow_handle = temporal_client.get_workflow_handle(
            workflow_id=processing_id,
            result_type=ConglomerateStatus,
        )
        status: ConglomerateStatus = await workflow_handle.query(
            "get_status",
            result_type=ConglomerateStatus,
            rpc_timeout=timedelta(seconds=60),
        )
        return status
    except Exception as e:
        msg = f"Error retrieving simulation status for id: {processing_id}: {e}"
        logger.error(msg, exc_info=e)
        raise HTTPException(status_code=404, detail=msg)
