"""FastAPI router for OMEX compatibility checking."""

import hashlib
import logging

import aiohttp
from fastapi import APIRouter, File, HTTPException, Query, UploadFile

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
    description="Upload an OMEX archive or provide a URL to find compatible simulators based on model format and algorithm requirements."
)
async def check_compatibility(
    uploaded_file: UploadFile | None = File(None, description="OMEX/COMBINE archive to check for compatibility"),
    archive_url: str | None = Query(None, description="URL to an OMEX/COMBINE archive (alternative to file upload)"),
    verbose: bool = Query(False, description="Include per-version algorithm and ontology details"),
) -> CompatibilityResponse:
    """Check which simulators can run the given OMEX archive.

    Provide either an uploaded file or an archive URL. Analyzes the OMEX
    archive to extract model formats and required simulation algorithms,
    then matches against available biosimulator capabilities.
    """
    # Get file content from upload or URL
    if uploaded_file is not None:
        try:
            file_content = await uploaded_file.read()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {e}")
    elif archive_url is not None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(archive_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        raise HTTPException(status_code=400, detail=f"Failed to download archive from URL: HTTP {resp.status}")
                    file_content = await resp.read()
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=400, detail=f"Failed to download archive from URL: {e}")
    else:
        raise HTTPException(status_code=400, detail="Provide either uploaded_file or archive_url")

    omex_id = hashlib.md5(file_content).hexdigest()

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
    eligible = await find_compatible_simulators(omex_content, simulator_versions, verbose=verbose)

    return CompatibilityResponse(
        omex_id=omex_id,
        omex_content=omex_content,
        eligible_simulators=eligible,
    )
