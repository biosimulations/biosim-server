"""Match OMEX requirements against simulator capabilities."""

import logging
from typing import Any

import aiohttp
from aiocache import SimpleMemoryCache, cached  # type: ignore

from biosim_server.biosim_runs import BiosimulatorVersion
from biosim_server.compatibility.kisao_data import EQUIVALENCE_CATEGORIES, KISAO_TERMS
from biosim_server.compatibility.models import EligibleSimulator, KisaoTerm, OmexContent, SimulatorVersionDetail
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


def _normalize_kisao_id(kisao_id: str) -> str:
    """Normalize KiSAO ID to format KISAO:XXXXXXX."""
    # Handle both KISAO_0000019 and KISAO:0000019 formats
    kisao_id = kisao_id.replace("_", ":")
    if not kisao_id.startswith("KISAO:"):
        kisao_id = f"KISAO:{kisao_id}"
    return kisao_id


def get_kisao_term_name_sync(kisao_id: str) -> str:
    """Get the human-readable name for a KiSAO term (synchronous).

    Uses the static KISAO_TERMS data.

    Args:
        kisao_id: Normalized KiSAO ID (e.g., "KISAO:0000019")

    Returns:
        Human-readable name (e.g., "CVODE") or the ID if name not found
    """
    normalized_id = _normalize_kisao_id(kisao_id)
    term_data = KISAO_TERMS.get(normalized_id)
    if term_data:
        return term_data["name"]
    return normalized_id


@cached(ttl=86400, cache=SimpleMemoryCache)  # type: ignore
async def get_kisao_term_name(kisao_id: str) -> str:
    """Get the human-readable name for a KiSAO term.

    Uses static KISAO_TERMS data first, then falls back to OLS API.

    Args:
        kisao_id: Normalized KiSAO ID (e.g., "KISAO:0000019")

    Returns:
        Human-readable name (e.g., "CVODE") or the ID if name not found
    """
    normalized_id = _normalize_kisao_id(kisao_id)

    # Check static data first
    term_data = KISAO_TERMS.get(normalized_id)
    if term_data:
        return term_data["name"]

    # Fall back to OLS API for unknown terms
    try:
        async with aiohttp.ClientSession() as session:
            # OLS uses underscore format: KISAO_0000019
            ols_id = normalized_id.replace(":", "_")
            url = f"https://www.ebi.ac.uk/ols4/api/ontologies/kisao/terms?iri=http://www.biomodels.net/kisao/KISAO%23{ols_id}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    terms = data.get("_embedded", {}).get("terms", [])
                    if terms and "label" in terms[0]:
                        name: str = terms[0]["label"]
                        return name
    except Exception as e:
        logger.debug(f"Failed to fetch KiSAO term name for {normalized_id}: {e}")

    # Return the ID if we couldn't find a name
    return normalized_id


async def create_kisao_term(kisao_id: str) -> KisaoTerm:
    """Create a KisaoTerm with ID and name.

    Args:
        kisao_id: KiSAO ID (will be normalized)

    Returns:
        KisaoTerm with id and name
    """
    normalized_id = _normalize_kisao_id(kisao_id)
    name = await get_kisao_term_name(normalized_id)
    return KisaoTerm(id=normalized_id, name=name)


def _get_algorithm_ancestors(kisao_id: str) -> set[str]:
    """Get all ancestors for a KiSAO algorithm ID.

    Args:
        kisao_id: KiSAO ID (will be normalized)

    Returns:
        Set of ancestor KiSAO IDs, or empty set if not found
    """
    normalized = _normalize_kisao_id(kisao_id)
    term_data = KISAO_TERMS.get(normalized)
    if term_data:
        return set(term_data["ancestors"])
    return set()


def _get_equivalence_ancestors(kisao_id: str) -> set[str]:
    """Get equivalence category ancestors for an algorithm.

    Returns the intersection of the algorithm's ancestors with the
    equivalence categories. These are the meaningful groupings (like
    "ODE solver", "stochastic method") that define equivalence.

    Args:
        kisao_id: KiSAO ID (will be normalized)

    Returns:
        Set of equivalence category IDs that this algorithm belongs to
    """
    ancestors = _get_algorithm_ancestors(kisao_id)
    # Also include the ID itself if it's an equivalence category
    normalized = _normalize_kisao_id(kisao_id)
    all_ids = ancestors | {normalized}
    return all_ids & EQUIVALENCE_CATEGORIES


def are_algorithms_equivalent(kisao_id1: str, kisao_id2: str) -> bool:
    """Check if two algorithms are equivalent based on shared ancestors.

    Two algorithms are considered equivalent if they share at least one
    ancestor in the EQUIVALENCE_CATEGORIES set (excluding the root
    KISAO:0000000 which is too broad).

    Args:
        kisao_id1: First KiSAO ID
        kisao_id2: Second KiSAO ID

    Returns:
        True if the algorithms are equivalent
    """
    # Same algorithm is always equivalent
    norm1 = _normalize_kisao_id(kisao_id1)
    norm2 = _normalize_kisao_id(kisao_id2)
    if norm1 == norm2:
        return True

    # Get equivalence ancestors for both
    eq1 = _get_equivalence_ancestors(norm1)
    eq2 = _get_equivalence_ancestors(norm2)

    # Find shared ancestors, excluding the root (too broad)
    shared = eq1 & eq2
    shared.discard("KISAO:0000000")

    return len(shared) > 0


def _ancestor_depth(kisao_id: str) -> int:
    """Return the depth of a term in the ontology (number of its ancestors)."""
    term_data = KISAO_TERMS.get(kisao_id)
    return len(term_data["ancestors"]) if term_data else 0


def _find_most_specific_common_ancestor(kisao_id1: str, kisao_id2: str) -> str | None:
    """Find the most specific shared ancestor in the full ontology.

    Among all shared ancestors (excluding the root), returns the one that
    is deepest in the hierarchy (has the most ancestors itself).

    Args:
        kisao_id1: First KiSAO ID
        kisao_id2: Second KiSAO ID

    Returns:
        KiSAO ID of the most specific common ancestor, or None if none found
    """
    norm1 = _normalize_kisao_id(kisao_id1)
    norm2 = _normalize_kisao_id(kisao_id2)

    ancestors1 = _get_algorithm_ancestors(norm1) | {norm1}
    ancestors2 = _get_algorithm_ancestors(norm2) | {norm2}

    shared = ancestors1 & ancestors2
    shared.discard("KISAO:0000000")
    # Remove the algorithms themselves — we want a true ancestor
    shared.discard(norm1)
    shared.discard(norm2)

    if not shared:
        return None

    return max(shared, key=_ancestor_depth)


def _find_equivalence_category(kisao_id1: str, kisao_id2: str) -> str | None:
    """Find the most specific shared equivalence category ancestor.

    Among the shared equivalence category ancestors (excluding the root),
    returns the one that is deepest in the hierarchy.

    Args:
        kisao_id1: First KiSAO ID
        kisao_id2: Second KiSAO ID

    Returns:
        KiSAO ID of the most specific equivalence category, or None if none found
    """
    norm1 = _normalize_kisao_id(kisao_id1)
    norm2 = _normalize_kisao_id(kisao_id2)

    eq1 = _get_equivalence_ancestors(norm1)
    eq2 = _get_equivalence_ancestors(norm2)

    shared = eq1 & eq2
    shared.discard("KISAO:0000000")

    if not shared:
        return None

    return max(shared, key=_ancestor_depth)


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


async def _check_version_compatibility(
    simulator_version: BiosimulatorVersion,
    required_edam_formats: set[str],
    required_algorithms: set[str],
    required_sim_types: set[str],
) -> SimulatorVersionDetail | None:
    """Check a single simulator version against OMEX requirements.

    Returns a SimulatorVersionDetail if compatible, None otherwise.
    """
    spec = await _get_simulator_spec(simulator_version.id, simulator_version.version)
    if not spec:
        return None

    algorithms_raw = spec.get("algorithms", [])
    if not algorithms_raw or not isinstance(algorithms_raw, list):
        return None

    exact_algorithm_matches: list[str] = []
    equivalent_algorithm_matches: list[tuple[str, str]] = []  # (sim_alg, req_alg)

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
            for req_alg in required_algorithms:
                if are_algorithms_equivalent(alg_kisao, req_alg):
                    equivalent_algorithm_matches.append((alg_kisao, req_alg))
                    break

    # Prefer exact matches; if none, use equivalent matches
    if exact_algorithm_matches:
        algorithm_terms = [await create_kisao_term(alg_id) for alg_id in exact_algorithm_matches]
        return SimulatorVersionDetail(
            version=simulator_version.version,
            image_url=simulator_version.image_url,
            algorithms=algorithm_terms,
            exact=True,
        )
    elif equivalent_algorithm_matches:
        algorithm_terms = [await create_kisao_term(sim_alg) for sim_alg, _ in equivalent_algorithm_matches]

        best_ancestor_id: str | None = None
        best_ancestor_depth = -1
        best_category_id: str | None = None
        best_category_depth = -1
        for sim_alg, req_alg in equivalent_algorithm_matches:
            ancestor_id = _find_most_specific_common_ancestor(sim_alg, req_alg)
            if ancestor_id:
                depth = _ancestor_depth(ancestor_id)
                if depth > best_ancestor_depth:
                    best_ancestor_depth = depth
                    best_ancestor_id = ancestor_id

            category_id = _find_equivalence_category(sim_alg, req_alg)
            if category_id:
                depth = _ancestor_depth(category_id)
                if depth > best_category_depth:
                    best_category_depth = depth
                    best_category_id = category_id

        common_ancestor = await create_kisao_term(best_ancestor_id) if best_ancestor_id else None
        equivalence_category = await create_kisao_term(best_category_id) if best_category_id else None

        return SimulatorVersionDetail(
            version=simulator_version.version,
            image_url=simulator_version.image_url,
            algorithms=algorithm_terms,
            exact=False,
            common_ancestor=common_ancestor,
            equivalence_category=equivalence_category,
        )

    return None


async def find_compatible_simulators(
    omex_content: OmexContent,
    simulator_versions: list[BiosimulatorVersion],
    verbose: bool = False,
) -> list[EligibleSimulator]:
    """Find simulators compatible with the OMEX archive requirements.

    Checks all versions of each simulator for compatibility and groups
    results by simulator id.

    Args:
        omex_content: Parsed OMEX content with requirements
        simulator_versions: Available simulator versions
        verbose: If True, include per-version detail (algorithms, ancestry)

    Returns:
        List of eligible simulators sorted by exact match then name
    """
    if not omex_content.simulations or not omex_content.model_formats:
        return []

    # Get required model formats as EDAM IDs
    required_edam_formats: set[str] = set()
    for model_format in omex_content.model_formats:
        edam_id = FORMAT_URI_TO_EDAM.get(model_format.format_uri)
        if edam_id:
            required_edam_formats.add(edam_id)

    if not required_edam_formats:
        return []

    # Get required algorithm KiSAO IDs
    required_algorithms: set[str] = set()
    required_sim_types: set[str] = set()
    for sim in omex_content.simulations:
        required_algorithms.add(_normalize_kisao_id(sim.algorithm.id))
        biosim_type = SIMULATION_TYPE_MAP.get(sim.simulation_type)
        if biosim_type:
            required_sim_types.add(biosim_type)

    # Check all versions in parallel
    import asyncio
    tasks = [
        _check_version_compatibility(sv, required_edam_formats, required_algorithms, required_sim_types)
        for sv in simulator_versions
    ]
    results = await asyncio.gather(*tasks)

    # Group compatible version details by simulator id
    # Preserve simulator name from the version entries
    simulator_names: dict[str, str] = {}
    version_details_by_sim: dict[str, list[SimulatorVersionDetail]] = {}
    for sv, detail in zip(simulator_versions, results):
        if detail is None:
            continue
        if sv.id not in version_details_by_sim:
            version_details_by_sim[sv.id] = []
            simulator_names[sv.id] = sv.name
        version_details_by_sim[sv.id].append(detail)

    # Build EligibleSimulator list
    eligible: list[EligibleSimulator] = []
    for sim_id, details in version_details_by_sim.items():
        any_exact = any(d.exact for d in details)
        versions = [d.version for d in details]
        eligible.append(EligibleSimulator(
            id=sim_id,
            name=simulator_names[sim_id],
            versions=versions,
            exact=any_exact,
            version_details=details if verbose else None,
        ))

    # Sort by exact (True first), then by name
    eligible.sort(key=lambda s: (not s.exact, s.name.lower()))

    return eligible
