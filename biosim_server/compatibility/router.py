"""FastAPI router for OMEX compatibility checking."""

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from biosim_server.compatibility.models import CompatibilityResponse
from biosim_server.compatibility.omex_parser import parse_omex_content
from biosim_server.compatibility.simulator_matcher import find_compatible_simulators
from biosim_server.dependencies import get_biosim_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compatibility", tags=["Compatibility"])


@router.post(
    "/check",
    response_model=CompatibilityResponse,
    operation_id="check-compatibility",
    summary="Check OMEX archive compatibility with simulators",
    description="Upload an OMEX archive to find compatible simulators based on model format and algorithm requirements."
)
async def check_compatibility(
    uploaded_file: UploadFile = File(..., description="OMEX/COMBINE archive to check for compatibility")
) -> CompatibilityResponse:
    """Check which simulators can run the uploaded OMEX archive.

    Analyzes the OMEX archive to extract:
    - Model formats (SBML, CellML, etc.)
    - Required simulation algorithms (from SED-ML files)

    Then matches against available biosimulator capabilities to find:
    - Exact matches: Simulators supporting the exact requested algorithms
    - Equivalent matches: Simulators supporting equivalent algorithms (e.g., different ODE solvers)
    """
    # Read file content
    try:
        file_content = await uploaded_file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {e}")

    # Parse OMEX content
    try:
        omex_content = parse_omex_content(file_content)
    except Exception as e:
        logger.error(f"Failed to parse OMEX file: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Failed to parse OMEX archive: {e}")

    if not omex_content.sedml_files:
        raise HTTPException(status_code=400, detail="No SED-ML files found in the OMEX archive")

    if not omex_content.simulations:
        raise HTTPException(status_code=400, detail="No simulations found in the SED-ML files")

    # Get available simulators
    biosim_service = get_biosim_service()
    if biosim_service is None:
        raise HTTPException(status_code=503, detail="Biosim service not available")

    try:
        simulator_versions = await biosim_service.get_simulator_versions()
    except Exception as e:
        logger.error(f"Failed to fetch simulator versions: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Failed to fetch simulator information: {e}")

    # Find compatible simulators
    simulators = await find_compatible_simulators(omex_content, simulator_versions)

    return CompatibilityResponse(
        omex_content=omex_content,
        simulators=simulators
    )
