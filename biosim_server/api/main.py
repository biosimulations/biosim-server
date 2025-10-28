import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, UTC, timedelta
from typing import AsyncGenerator, Optional

import dotenv
import uvicorn
from fastapi import FastAPI, File, UploadFile, Query, APIRouter, Depends, HTTPException
from fastapi.openapi.docs import get_swagger_ui_html
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse

from biosim_server.biosim_omex import OmexFile, get_cached_omex_file_from_upload
from biosim_server.biosim_runs import BiosimulatorVersion
from biosim_server.biosim_verify import CompareSettings
from biosim_server.biosim_verify.models import VerifyWorkflowOutput, VerifyWorkflowStatus
from biosim_server.biosim_verify.omex_verify_workflow import OmexVerifyWorkflow, OmexVerifyWorkflowInput
from biosim_server.biosim_verify.runs_verify_workflow import RunsVerifyWorkflowInput, RunsVerifyWorkflow
from biosim_server.config import get_local_cache_dir
from biosim_server.dependencies import get_file_service, get_temporal_client, init_standalone, shutdown_standalone, \
    get_biosim_service, get_omex_database_service
from biosim_server.log_config import setup_logging
from biosim_server.version import __version__

logger = logging.getLogger(__name__)
setup_logging(logger)

# -- load dev env -- #
REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
DEV_ENV_PATH = os.path.join(REPO_ROOT, 'assets', 'dev', 'config', '.dev_env')
dotenv.load_dotenv(DEV_ENV_PATH)  # NOTE: create an env config at this filepath if dev

# -- constraints -- #
APP_VERSION = __version__
APP_TITLE = "biosim-server"
APP_ORIGINS = [
    'http://127.0.0.1:8000',
    'http://127.0.0.1:4200',
    'http://127.0.0.1:4201',
    'http://127.0.0.1:4202',
    'http://localhost:4200',
    'http://localhost:4201',
    'http://localhost:4202',
    'http://localhost:8000',
    'http://localhost:3001',
    'https://biosimulators.org',
    'https://www.biosimulators.org',
    'https://biosimulators.dev',
    'https://www.biosimulators.dev',
    'https://run.biosimulations.dev',
    'https://run.biosimulations.org',
    'https://biosimulations.dev',
    'https://biosimulations.org',
    'https://bio.libretexts.org',
    'https://biochecknet.biosimulations.org'
]
APP_SERVERS: list[dict[str, str]] = [
    # {
    #     "url": "https://biochecknet.biosimulations.org",
    #     "description": "Production server"
    # },
    # {
    #     "url": "http://localhost:3001",
    #     "description": "Main Development server"
    # },
    # {
    #     "url": "http://localhost:8000",
    #     "description": "Alternate Development server"
    # }
]

# -- app components -- #

router = APIRouter()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    await init_standalone()
    yield
    await shutdown_standalone()


app = FastAPI(openapi_url="/docs", docs_url=None, redoc_url=None, title=APP_TITLE, version=APP_VERSION, servers=APP_SERVERS, lifespan=lifespan)

# add origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=APP_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"])


# -- endpoint logic -- #

@app.get("/")
def root() -> dict[str, str]:
    return {
        'docs': 'https://biosim.biosimulations.org/docs',
        'version': APP_VERSION
    }


@app.get("/version")
def get_version() -> str:
    return APP_VERSION

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html() -> HTMLResponse:
    if app.openapi_url is None:
        raise HTTPException(status_code=404, detail="OpenAPI schema not available")
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        swagger_js_url="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/3.0.21/swagger-ui-bundle.js", # Replace with your CDN URL
        swagger_css_url="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/3.0.21/swagger-ui.css",     # Replace with your CDN URL
    )

@app.post(
    "/verify/omex",
    response_model=VerifyWorkflowOutput,
    operation_id="verify-omex",
    tags=["Verification"],
    dependencies=[Depends(get_temporal_client), Depends(get_file_service), Depends(get_local_cache_dir), Depends(get_omex_database_service)],
    summary="Request verification report for OMEX/COMBINE archive across simulators")
async def verify_omex(
        uploaded_file: UploadFile = File(..., description="OMEX/COMBINE archive containing a deterministic SBML model"),
        workflow_id_prefix: str = Query(default="omex-verification-", description="Prefix for the workflow id."),
        simulators: list[str] = Query(default=["amici", "copasi", "pysces", "tellurium", "vcell"],
                                      description="List of simulators 'name' or 'name:version' to compare."),
        include_outputs: bool = Query(default=False,
                                      description="Whether to include the output data on which the comparison is based."),
        user_description: str = Query(default="my-omex-compare", description="User description of the verification run."),
        rel_tol: float = Query(default=0.0001, description="Relative tolerance for proximity comparison."),
        abs_tol_min: float = Query(default=0.001, description="Min absolute tolerance, where atol = max(atol_min, max(arr1,arr2)*atol_scale."),
        abs_tol_scale: float = Query(default=0.00001, description="Scale for absolute tolerance, where atol = max(atol_min, max(arr1,arr2)*atol_scale."),
        cache_buster: str = Query(default="0", description="Optional unique id for cache busting (unique string to force new simulation runs)."),
        observables: Optional[list[str]] = Query(default=None,
                                                 description="List of observables to include in the return data.")
) -> VerifyWorkflowOutput:
    # ---- using hash to avoid saving multiple copies, upload to cloud storage if needed ---- #
    file_service = get_file_service()
    assert file_service is not None
    omex_database = get_omex_database_service()
    assert omex_database is not None
    omex_file: OmexFile = await get_cached_omex_file_from_upload(file_service=file_service, omex_database=omex_database,
                                                                 uploaded_file=uploaded_file)

    # ---- create workflow input ---- #
    simulator_versions: list[BiosimulatorVersion] = []
    biosim_service = get_biosim_service()
    assert biosim_service is not None
    all_simulator_versions = await biosim_service.get_simulator_versions()
    for simulator in simulators:
        simulator_version: Optional[BiosimulatorVersion] = None
        if ":" in simulator:
            name, version = simulator.split(":")
            for sv in all_simulator_versions:
                if sv.id == name and sv.version == version:
                    simulator_version = sv
                    break
        else:
            for sv in all_simulator_versions:
                if sv.id == simulator:
                    simulator_version = sv  # don't break, we want the last one in the list
        if simulator_version is not None:
            simulator_versions.append(simulator_version)
        else:
            raise HTTPException(status_code=400, detail=f"Simulator {simulator} not found.")

    workflow_id = f"{workflow_id_prefix}{uuid.uuid4()}"
    compare_settings = CompareSettings(user_description=user_description, include_outputs=include_outputs,
                                       rel_tol=rel_tol, abs_tol_min=abs_tol_min, abs_tol_scale=abs_tol_scale,
                                       observables=observables)
    omex_verify_workflow_input = OmexVerifyWorkflowInput(omex_file=omex_file, requested_simulators=simulator_versions,
                                                         compare_settings=compare_settings, cache_buster=cache_buster)

    # ---- invoke workflow ---- #
    logger.info(f"starting workflow for {omex_file}")
    temporal_client = get_temporal_client()
    assert temporal_client is not None
    workflow_handle = await temporal_client.start_workflow(
        OmexVerifyWorkflow.run,
        args=[omex_verify_workflow_input],
        task_queue="verification_tasks",
        id=workflow_id,
    )
    logger.info(f"started workflow with id {workflow_id}")
    assert workflow_handle.id == workflow_id

    # ---- return initial workflow output ---- #
    omex_verify_workflow_output = VerifyWorkflowOutput(
        compare_settings=compare_settings,
        workflow_status=VerifyWorkflowStatus.PENDING,
        timestamp=str(datetime.now(UTC)),
        workflow_id=workflow_id,
        workflow_run_id=workflow_handle.run_id
    )
    return omex_verify_workflow_output


@app.get(
    "/verify/{workflow_id}",
    response_model=VerifyWorkflowOutput,
    operation_id='get-verify-output',
    name="Retrieve verification report",
    tags=["Verification"],
    dependencies=[Depends(get_temporal_client)],
    summary='Retrieve verification report for OMEX/COMBINE archive')
async def get_verify_output(workflow_id: str) -> VerifyWorkflowOutput:
    logger.info(f"in get /verify/{workflow_id}")

    try:
        # query temporal for the workflow output
        temporal_client = get_temporal_client()
        assert temporal_client is not None
        workflow_handle = temporal_client.get_workflow_handle(workflow_id=workflow_id,
                                                              result_type=VerifyWorkflowOutput)
        workflow_output: VerifyWorkflowOutput = await workflow_handle.query("get_output",
                                                                                result_type=VerifyWorkflowOutput,
                                                                                rpc_timeout=timedelta(seconds=60))
        return workflow_output
    except Exception as e2:
        exc_message = str(e2)
        msg = f"error retrieving verification job output with id: {workflow_id}: {exc_message}"
        logger.error(msg, exc_info=e2)
        raise HTTPException(status_code=404, detail=msg)


@app.post(
    "/verify/runs",
    response_model=VerifyWorkflowOutput,
    operation_id="verify-runs",
    tags=["Verification"],
    dependencies=[Depends(get_temporal_client)],
    summary="Request verification report for biosimulation runs by run IDs")
async def verify_runs(
        workflow_id_prefix: str = Query(default="runs-verification-", description="Prefix for the workflow id."),
        biosimulations_run_ids: list[str] = Query(default=["67817a2e1f52f47f628af971","67817a2eba5a3f02b9f2938d"],
                                                  description="List of biosimulations run IDs to compare."),
        include_outputs: bool = Query(default=False,
                                      description="Whether to include the output data on which the comparison is based."),
        user_description: str = Query(default="my-verify-job", description="User description of the verification run."),
        rel_tol: float = Query(default=0.0001, description="Relative tolerance for proximity comparison."),
        abs_tol_min: float = Query(default=0.001, description="Min absolute tolerance, where atol = max(atol_min, max(arr1,arr2)*atol_scale."),
        abs_tol_scale: float = Query(default=0.00001, description="Scale for absolute tolerance, where atol = max(atol_min, max(arr1,arr2)*atol_scale."),
        observables: Optional[list[str]] = Query(default=None,
                                                 description="List of observables to include in the return data.")
) -> VerifyWorkflowOutput:

    # ---- create workflow input ---- #
    workflow_id = f"{workflow_id_prefix}{uuid.uuid4()}"
    compare_settings = CompareSettings(user_description=user_description, include_outputs=include_outputs,
                                       rel_tol=rel_tol, abs_tol_min=abs_tol_min, abs_tol_scale=abs_tol_scale,
                                       observables=observables)
    runs_verify_workflow_input = RunsVerifyWorkflowInput(biosimulations_run_ids=biosimulations_run_ids,
                                                         compare_settings=compare_settings)

    # ---- invoke workflow ---- #
    logger.info(f"starting verify workflow for biosim run IDs {biosimulations_run_ids}")
    temporal_client = get_temporal_client()
    assert temporal_client is not None
    workflow_handle = await temporal_client.start_workflow(
        RunsVerifyWorkflow.run,
        args=[runs_verify_workflow_input],
        task_queue="verification_tasks",
        id=workflow_id,
    )
    logger.info(f"started workflow with id {workflow_id}")
    assert workflow_handle.id == workflow_id

    # ---- return initial workflow output ---- #
    runs_verify_workflow_output = VerifyWorkflowOutput(
        compare_settings=compare_settings,
        workflow_status=VerifyWorkflowStatus.PENDING,
        timestamp=str(datetime.now(UTC)),
        workflow_id=workflow_id,
        workflow_run_id=workflow_handle.run_id
    )
    return runs_verify_workflow_output


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
    logger.info("Server started")
