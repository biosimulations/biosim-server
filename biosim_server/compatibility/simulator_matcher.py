"""Match OMEX requirements against simulator capabilities."""

import logging
from typing import Any

import aiohttp
from aiocache import SimpleMemoryCache, cached  # type: ignore

from biosim_server.biosim_runs import BiosimulatorVersion
from biosim_server.compatibility.models import CompatibleSimulator, OmexContent
from biosim_server.config import get_settings

logger = logging.getLogger(__name__)

# Map OMEX format URIs to biosimulators EDAM format IDs
FORMAT_URI_TO_EDAM = {
    "http://identifiers.org/combine.specifications/sbml": "format_2585",
    "http://purl.org/NET/mediatypes/application/sbml+xml": "format_2585",
    "http://identifiers.org/combine.specifications/cellml": "format_3240",
    "http://identifiers.org/combine.specifications/cellml.1.0": "format_3240",
    "http://identifiers.org/combine.specifications/cellml.1.1": "format_3240",
    "http://identifiers.org/combine.specifications/cellml.2.0": "format_3240",
    "http://identifiers.org/combine.specifications/neuroml": "format_3971",
}

# Map simulation types to biosimulators simulation type names
SIMULATION_TYPE_MAP = {
    "uniformTimeCourse": "SedUniformTimeCourseSimulation",
    "steadyState": "SedSteadyStateSimulation",
    "oneStep": "SedOneStepSimulation",
    "analysis": "SedAnalysis",
}

# Groups of equivalent/related algorithms by category
# These are algorithms that solve similar problems and can often substitute for each other
EQUIVALENT_ALGORITHMS: dict[str, set[str]] = {
    # Deterministic ODE solvers (continuous dynamics)
    "ode_solvers": {
        "KISAO:0000019",  # CVODE
        "KISAO:0000088",  # LSODA
        "KISAO:0000560",  # LSODI
        "KISAO:0000030",  # Euler forward
        "KISAO:0000031",  # Euler backward
        "KISAO:0000032",  # Runge-Kutta 4th order
        "KISAO:0000086",  # Runge-Kutta-Fehlberg
        "KISAO:0000087",  # Dormand-Prince
        "KISAO:0000280",  # Adams-Moulton
        "KISAO:0000288",  # BDF
        "KISAO:0000535",  # VODE
        "KISAO:0000536",  # ZVODE
        "KISAO:0000304",  # RADAU5
        "KISAO:0000094",  # Bulirsch-Stoer
    },
    # Stochastic simulation algorithms
    "stochastic": {
        "KISAO:0000029",  # Gillespie direct
        "KISAO:0000027",  # Gibson-Bruck next reaction
        "KISAO:0000038",  # Tau-leaping
        "KISAO:0000039",  # Adaptive tau-leaping
        "KISAO:0000028",  # Slow-scale SSA
        "KISAO:0000082",  # Binomial tau-leaping
        "KISAO:0000084",  # Multinomial tau-leaping
        "KISAO:0000241",  # Gillespie multi-particle
        "KISAO:0000331",  # Exact R-leaping
        "KISAO:0000333",  # Constant-tau-leaping
        "KISAO:0000323",  # Sorting direct method
        "KISAO:0000324",  # Logarithmic direct method
        "KISAO:0000350",  # Poisson tau-leaping
    },
    # Steady state / root finding
    "steady_state": {
        "KISAO:0000569",  # NLEQ2 / Newton-type
        "KISAO:0000407",  # Steady state method
        "KISAO:0000408",  # Newton's method
        "KISAO:0000282",  # Broyden's method
        "KISAO:0000283",  # Kinsol
        "KISAO:0000437",  # Damped Newton
    },
    # Hybrid methods (stochastic + deterministic)
    "hybrid": {
        "KISAO:0000231",  # Hybrid Gibson-Bruck
        "KISAO:0000563",  # Hybrid adaptive
        "KISAO:0000230",  # Hybrid Runge-Kutta
        "KISAO:0000352",  # Hybrid tau-leaping
    },
    # Flux balance analysis
    "fba": {
        "KISAO:0000437",  # FBA
        "KISAO:0000527",  # parsimonious FBA
        "KISAO:0000528",  # geometric FBA
    },
}


def _normalize_kisao_id(kisao_id: str) -> str:
    """Normalize KiSAO ID to format KISAO:XXXXXXX."""
    # Handle both KISAO_0000019 and KISAO:0000019 formats
    kisao_id = kisao_id.replace("_", ":")
    if not kisao_id.startswith("KISAO:"):
        kisao_id = f"KISAO:{kisao_id}"
    return kisao_id


def _get_algorithm_group(kisao_id: str) -> str | None:
    """Find the group a KiSAO ID belongs to."""
    normalized = _normalize_kisao_id(kisao_id)
    for group_name, group_ids in EQUIVALENT_ALGORITHMS.items():
        if normalized in group_ids:
            return group_name
    return None


@cached(ttl=3600, cache=SimpleMemoryCache)  # type: ignore
async def _get_simulator_spec(simulator_id: str, version: str) -> dict[str, Any] | None:
    """Fetch full simulator specification from biosimulators API.

    Args:
        simulator_id: Simulator ID (e.g., "tellurium")
        version: Simulator version (e.g., "2.2.8")

    Returns:
        Simulator specification dict or None if not found
    """
    api_base_url = get_settings().biosimulators_api_base_url

    async with aiohttp.ClientSession() as session:
        url = f"{api_base_url}/simulators/{simulator_id}/{version}"
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    result: dict[str, Any] = await resp.json()
                    return result
                else:
                    logger.warning(f"Failed to fetch simulator spec for {simulator_id}:{version}: {resp.status}")
                    return None
        except aiohttp.ClientError as e:
            logger.warning(f"Error fetching simulator spec for {simulator_id}:{version}: {e}")
            return None


async def find_compatible_simulators(
    omex_content: OmexContent,
    simulator_versions: list[BiosimulatorVersion]
) -> tuple[list[CompatibleSimulator], list[CompatibleSimulator]]:
    """Find simulators compatible with the OMEX archive requirements.

    Args:
        omex_content: Parsed OMEX content with requirements
        simulator_versions: Available simulator versions

    Returns:
        Tuple of (exact_matches, equivalent_matches)
    """
    if not omex_content.simulations or not omex_content.model_formats:
        return [], []

    # Get required model formats as EDAM IDs
    required_edam_formats: set[str] = set()
    for model_format in omex_content.model_formats:
        edam_id = FORMAT_URI_TO_EDAM.get(model_format.format_uri)
        if edam_id:
            required_edam_formats.add(edam_id)

    if not required_edam_formats:
        return [], []

    # Get required algorithm KiSAO IDs
    required_algorithms: set[str] = set()
    required_sim_types: set[str] = set()
    for sim in omex_content.simulations:
        required_algorithms.add(_normalize_kisao_id(sim.algorithm_kisao_id))
        biosim_type = SIMULATION_TYPE_MAP.get(sim.simulation_type)
        if biosim_type:
            required_sim_types.add(biosim_type)

    # Find algorithm groups for equivalent matching
    required_groups: set[str] = set()
    for req_alg in required_algorithms:
        group = _get_algorithm_group(req_alg)
        if group:
            required_groups.add(group)

    exact_matches: list[CompatibleSimulator] = []
    equivalent_matches: list[CompatibleSimulator] = []

    # Group simulator versions by ID to get only the latest version
    latest_versions: dict[str, BiosimulatorVersion] = {}
    for sv in simulator_versions:
        if sv.id not in latest_versions:
            latest_versions[sv.id] = sv

    for simulator_version in latest_versions.values():
        spec = await _get_simulator_spec(simulator_version.id, simulator_version.version)
        if not spec:
            continue

        algorithms_raw = spec.get("algorithms", [])
        if not algorithms_raw or not isinstance(algorithms_raw, list):
            continue

        # Check each algorithm in the simulator
        exact_algorithm_matches: list[str] = []
        equivalent_algorithm_matches: list[str] = []

        for alg_raw in algorithms_raw:
            if not isinstance(alg_raw, dict):
                continue
            alg: dict[str, Any] = alg_raw

            kisao_id_obj = alg.get("kisaoId", {})
            if not isinstance(kisao_id_obj, dict):
                continue
            alg_kisao = _normalize_kisao_id(str(kisao_id_obj.get("id", "")))
            if not alg_kisao:
                continue

            # Check model format support
            model_formats_raw = alg.get("modelFormats", [])
            if not isinstance(model_formats_raw, list):
                continue
            supported_formats = {str(mf.get("id", "")) for mf in model_formats_raw if isinstance(mf, dict)}
            if not required_edam_formats.intersection(supported_formats):
                continue

            # Check simulation type support
            # API returns either strings or dicts with "id" key
            sim_types_raw = alg.get("simulationTypes", [])
            if not isinstance(sim_types_raw, list):
                continue
            supported_sim_types: set[str] = set()
            for st in sim_types_raw:
                if isinstance(st, str):
                    supported_sim_types.add(st)
                elif isinstance(st, dict):
                    supported_sim_types.add(str(st.get("id", "")))
            if required_sim_types and not required_sim_types.intersection(supported_sim_types):
                continue

            # Check exact algorithm match
            if alg_kisao in required_algorithms:
                exact_algorithm_matches.append(alg_kisao)
            else:
                # Check equivalent algorithm match
                alg_group = _get_algorithm_group(alg_kisao)
                if alg_group and alg_group in required_groups:
                    equivalent_algorithm_matches.append(alg_kisao)

        if exact_algorithm_matches:
            exact_matches.append(CompatibleSimulator(
                id=simulator_version.id,
                name=simulator_version.name,
                version=simulator_version.version,
                image_url=simulator_version.image_url,
                algorithms=exact_algorithm_matches
            ))
        elif equivalent_algorithm_matches:
            equivalent_matches.append(CompatibleSimulator(
                id=simulator_version.id,
                name=simulator_version.name,
                version=simulator_version.version,
                image_url=simulator_version.image_url,
                algorithms=equivalent_algorithm_matches
            ))

    # Sort by simulator name
    exact_matches.sort(key=lambda s: s.name.lower())
    equivalent_matches.sort(key=lambda s: s.name.lower())

    return exact_matches, equivalent_matches
