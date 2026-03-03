"""Tests for simulator matching logic."""

from pathlib import Path

import pytest

from biosim_server.biosim_runs import BiosimulatorVersion
from biosim_server.compatibility.models import KisaoTerm, OmexContent, ModelFormat, SimulationRequirement
from biosim_server.compatibility.omex_parser import parse_omex_content
from biosim_server.compatibility.simulator_matcher import (
    _normalize_kisao_id,
    _find_equivalence_category,
    _find_most_specific_common_ancestor,
    _get_algorithm_ancestors,
    _get_equivalence_ancestors,
    _get_simulator_spec,
    are_algorithms_equivalent,
    find_compatible_simulators,
    get_kisao_term_name_sync,
)


def test_normalize_kisao_id() -> None:
    """Test KiSAO ID normalization."""
    assert _normalize_kisao_id("KISAO:0000019") == "KISAO:0000019"
    assert _normalize_kisao_id("KISAO_0000019") == "KISAO:0000019"
    assert _normalize_kisao_id("0000019") == "KISAO:0000019"


def test_get_kisao_term_name_sync() -> None:
    """Test synchronous KiSAO term name lookup."""
    # Known terms from KISAO data
    assert get_kisao_term_name_sync("KISAO:0000019") == "CVODE"
    assert get_kisao_term_name_sync("KISAO:0000088") == "LSODA"
    assert get_kisao_term_name_sync("KISAO:0000029") == "Gillespie direct algorithm"

    # Unknown term returns the ID
    assert get_kisao_term_name_sync("KISAO:9999999") == "KISAO:9999999"


def test_get_algorithm_ancestors() -> None:
    """Test ancestor retrieval from KISAO data."""
    # CVODE should have ODE solver (KISAO:0000694) as ancestor
    cvode_ancestors = _get_algorithm_ancestors("KISAO:0000019")
    assert "KISAO:0000694" in cvode_ancestors
    assert "KISAO:0000433" in cvode_ancestors  # CVODE-like method
    assert "KISAO:0000000" in cvode_ancestors  # root

    # LSODA should also have ODE solver as ancestor
    lsoda_ancestors = _get_algorithm_ancestors("KISAO:0000088")
    assert "KISAO:0000694" in lsoda_ancestors
    assert "KISAO:0000094" in lsoda_ancestors  # Livermore solver

    # Gillespie should have Monte Carlo method as ancestor
    gillespie_ancestors = _get_algorithm_ancestors("KISAO:0000029")
    assert "KISAO:0000319" in gillespie_ancestors  # Monte Carlo method
    assert "KISAO:0000241" in gillespie_ancestors  # Gillespie-like method

    # Unknown term returns empty set
    assert _get_algorithm_ancestors("KISAO:9999999") == set()


def test_get_equivalence_ancestors() -> None:
    """Test equivalence category ancestor retrieval."""
    # CVODE should have ODE solver equivalence category
    cvode_eq = _get_equivalence_ancestors("KISAO:0000019")
    assert "KISAO:0000694" in cvode_eq  # ODE solver
    assert "KISAO:0000433" in cvode_eq  # CVODE-like method

    # Gillespie should have Monte Carlo method equivalence category
    gillespie_eq = _get_equivalence_ancestors("KISAO:0000029")
    assert "KISAO:0000319" in gillespie_eq  # Monte Carlo method


def test_are_algorithms_equivalent() -> None:
    """Test algorithm equivalence based on shared ancestors."""
    # Same algorithm is equivalent to itself
    assert are_algorithms_equivalent("KISAO:0000019", "KISAO:0000019")

    # CVODE and LSODA are both ODE solvers (share KISAO:0000694)
    assert are_algorithms_equivalent("KISAO:0000019", "KISAO:0000088")

    # CVODE and Gillespie are NOT equivalent (different categories)
    assert not are_algorithms_equivalent("KISAO:0000019", "KISAO:0000029")

    # Two Gillespie variants should be equivalent (both stochastic)
    # Gibson-Bruck and Gillespie direct both have Monte Carlo ancestor
    assert are_algorithms_equivalent("KISAO:0000027", "KISAO:0000029")

    # Different ODE solvers: Dormand-Prince and CVODE
    assert are_algorithms_equivalent("KISAO:0000087", "KISAO:0000019")


def test_find_most_specific_common_ancestor() -> None:
    """Test finding the most specific common ancestor in the full ontology."""
    # CVODE and LSODA - only shared non-root ancestor is ODE solver
    ancestor = _find_most_specific_common_ancestor("KISAO:0000019", "KISAO:0000088")
    assert ancestor is not None
    assert ancestor == "KISAO:0000694"  # ODE solver

    # Gibson-Bruck and Gillespie direct share "Gillespie-like method" (0000241)
    # which is more specific than the equivalence category "Monte Carlo method"
    ancestor = _find_most_specific_common_ancestor("KISAO:0000027", "KISAO:0000029")
    assert ancestor is not None
    assert ancestor == "KISAO:0000241"  # Gillespie-like method

    # Incompatible algorithms (ODE vs stochastic) have no common ancestor
    ancestor = _find_most_specific_common_ancestor("KISAO:0000019", "KISAO:0000029")
    assert ancestor is None

    # Unknown term returns None
    ancestor = _find_most_specific_common_ancestor("KISAO:9999999", "KISAO:0000019")
    assert ancestor is None


def test_find_equivalence_category() -> None:
    """Test finding the most specific shared equivalence category."""
    # CVODE and LSODA share ODE solver equivalence category
    cat = _find_equivalence_category("KISAO:0000019", "KISAO:0000088")
    assert cat is not None
    assert cat == "KISAO:0000694"  # ODE solver

    # Gibson-Bruck and Gillespie direct share Monte Carlo method category
    # (not the more specific "Gillespie-like method" which isn't a curated category)
    cat = _find_equivalence_category("KISAO:0000027", "KISAO:0000029")
    assert cat is not None
    assert cat == "KISAO:0000319"  # Monte Carlo method

    # CVODE and PVODE share CVODE-like method (more specific than ODE solver)
    cat = _find_equivalence_category("KISAO:0000019", "KISAO:0000020")
    assert cat is not None
    assert cat == "KISAO:0000433"  # CVODE-like method

    # Incompatible algorithms have no shared category
    cat = _find_equivalence_category("KISAO:0000019", "KISAO:0000029")
    assert cat is None


def test_are_algorithms_equivalent_unknown_term() -> None:
    """Test that unknown terms are not equivalent to anything (except themselves)."""
    unknown = "KISAO:9999999"

    # Unknown term is equivalent to itself
    assert are_algorithms_equivalent(unknown, unknown)

    # Unknown term is not equivalent to known terms
    assert not are_algorithms_equivalent(unknown, "KISAO:0000019")
    assert not are_algorithms_equivalent("KISAO:0000019", unknown)


@pytest.fixture
def sample_omex_content() -> OmexContent:
    """Create sample OMEX content for testing."""
    return OmexContent(
        model_formats=[
            ModelFormat(
                format_uri="http://identifiers.org/combine.specifications/sbml",
                language="urn:sedml:language:sbml.level-2.version-4",
                location="model.xml"
            )
        ],
        simulations=[
            SimulationRequirement(
                algorithm=KisaoTerm(id="KISAO:0000019", name="CVODE"),
                simulation_type="uniformTimeCourse"
            )
        ],
        sedml_files=["simulation.sedml"]
    )


@pytest.fixture
def sample_simulator_versions() -> list[BiosimulatorVersion]:
    """Create sample simulator versions for testing."""
    return [
        BiosimulatorVersion(
            id="tellurium",
            name="tellurium",
            version="2.2.10",
            image_url="ghcr.io/biosimulators/tellurium:2.2.10",
            image_digest="sha256:0c22827b4682273810d48ea606ef50c7163e5f5289740951c00c64c669409eae",
            created="2024-10-10T22:00:50.110Z",
            updated="2024-10-10T22:00:50.110Z"
        ),
        BiosimulatorVersion(
            id="copasi",
            name="COPASI",
            version="4.45.296",
            image_url="ghcr.io/biosimulators/copasi:4.45.296",
            image_digest="sha256:7c9cd076eeec494a653353777e42561a2ec9be1bfcc647d0ea84d89fe18999df",
            created="2024-11-18T15:34:26.233Z",
            updated="2024-11-18T15:34:26.233Z"
        ),
    ]


@pytest.mark.asyncio
async def test_find_compatible_simulators_empty_content() -> None:
    """Test with empty OMEX content."""
    empty_content = OmexContent(
        model_formats=[],
        simulations=[],
        sedml_files=[]
    )

    simulators = await find_compatible_simulators(empty_content, [])
    assert simulators == []


@pytest.mark.asyncio
async def test_find_compatible_simulators_no_simulators(
    sample_omex_content: OmexContent
) -> None:
    """Test with no available simulators passed in."""
    simulators = await find_compatible_simulators(sample_omex_content, [])
    assert simulators == []


@pytest.mark.asyncio
async def test_find_compatible_simulators_with_exact_match(
    sample_omex_content: OmexContent,
    sample_simulator_versions: list[BiosimulatorVersion]
) -> None:
    """Test finding simulators with exact algorithm match."""
    from unittest.mock import AsyncMock, patch

    # Mock simulator spec that supports CVODE (KISAO:0000019) with SBML
    tellurium_spec = {
        "id": "tellurium",
        "algorithms": [
            {
                "kisaoId": {"id": "KISAO_0000019"},  # CVODE
                "modelFormats": [{"id": "format_2585"}],  # SBML
                "simulationTypes": [{"id": "SedUniformTimeCourseSimulation"}]
            }
        ]
    }

    with patch(
        "biosim_server.compatibility.simulator_matcher._get_simulator_spec",
        new_callable=AsyncMock
    ) as mock_get_spec:
        mock_get_spec.return_value = tellurium_spec

        simulators = await find_compatible_simulators(
            sample_omex_content,
            sample_simulator_versions[:1]  # Just tellurium
        )

        assert len(simulators) == 1
        assert simulators[0].id == "tellurium"
        assert simulators[0].exact_match is True
        assert simulators[0].common_ancestor is None
        assert simulators[0].equivalence_category is None
        # Check algorithm has both id and name
        alg_ids = [alg.id for alg in simulators[0].algorithms]
        assert "KISAO:0000019" in alg_ids
        assert simulators[0].algorithms[0].name == "CVODE"


@pytest.mark.asyncio
async def test_find_compatible_simulators_with_equivalent_match(
    sample_omex_content: OmexContent,
    sample_simulator_versions: list[BiosimulatorVersion]
) -> None:
    """Test finding simulators with equivalent algorithm (different ODE solver)."""
    from unittest.mock import AsyncMock, patch

    # Mock simulator spec that supports LSODA (equivalent to CVODE) with SBML
    copasi_spec = {
        "id": "copasi",
        "algorithms": [
            {
                "kisaoId": {"id": "KISAO_0000088"},  # LSODA (not CVODE, but same group)
                "modelFormats": [{"id": "format_2585"}],  # SBML
                "simulationTypes": [{"id": "SedUniformTimeCourseSimulation"}]
            }
        ]
    }

    with patch(
        "biosim_server.compatibility.simulator_matcher._get_simulator_spec",
        new_callable=AsyncMock
    ) as mock_get_spec:
        mock_get_spec.return_value = copasi_spec

        simulators = await find_compatible_simulators(
            sample_omex_content,
            sample_simulator_versions[1:2]  # Just copasi
        )

        # LSODA is not an exact match for CVODE, but they're equivalent ODE solvers
        assert len(simulators) == 1
        assert simulators[0].id == "copasi"
        assert simulators[0].exact_match is False
        alg_ids = [alg.id for alg in simulators[0].algorithms]
        assert "KISAO:0000088" in alg_ids
        assert simulators[0].algorithms[0].name == "LSODA"
        # Should have both ancestor fields populated
        assert simulators[0].common_ancestor is not None
        assert simulators[0].common_ancestor.id == "KISAO:0000694"  # ODE solver
        assert simulators[0].common_ancestor.name == "ODE solver"
        assert simulators[0].equivalence_category is not None
        assert simulators[0].equivalence_category.id == "KISAO:0000694"  # ODE solver
        assert simulators[0].equivalence_category.name == "ODE solver"


@pytest.mark.asyncio
async def test_find_compatible_simulators_no_match_wrong_format(
    sample_simulator_versions: list[BiosimulatorVersion]
) -> None:
    """Test that simulators not supporting the model format are excluded."""
    from unittest.mock import AsyncMock, patch

    # OMEX content with CellML (not SBML)
    cellml_content = OmexContent(
        model_formats=[
            ModelFormat(
                format_uri="http://identifiers.org/combine.specifications/cellml",
                language=None,
                location="model.cellml"
            )
        ],
        simulations=[
            SimulationRequirement(
                algorithm=KisaoTerm(id="KISAO:0000019", name="CVODE"),
                simulation_type="uniformTimeCourse"
            )
        ],
        sedml_files=["simulation.sedml"]
    )

    # Simulator only supports SBML, not CellML
    sbml_only_spec = {
        "id": "tellurium",
        "algorithms": [
            {
                "kisaoId": {"id": "KISAO_0000019"},
                "modelFormats": [{"id": "format_2585"}],  # SBML only
                "simulationTypes": [{"id": "SedUniformTimeCourseSimulation"}]
            }
        ]
    }

    with patch(
        "biosim_server.compatibility.simulator_matcher._get_simulator_spec",
        new_callable=AsyncMock
    ) as mock_get_spec:
        mock_get_spec.return_value = sbml_only_spec

        simulators = await find_compatible_simulators(
            cellml_content,
            sample_simulator_versions[:1]
        )

        # Should not match because format doesn't match
        assert len(simulators) == 0


@pytest.mark.asyncio
async def test_find_compatible_simulators_no_match_incompatible_algorithm(
    sample_simulator_versions: list[BiosimulatorVersion]
) -> None:
    """Test that simulators with incompatible algorithms are excluded."""
    from unittest.mock import AsyncMock, patch

    # OMEX content requesting Gillespie (stochastic)
    stochastic_content = OmexContent(
        model_formats=[
            ModelFormat(
                format_uri="http://identifiers.org/combine.specifications/sbml",
                language=None,
                location="model.xml"
            )
        ],
        simulations=[
            SimulationRequirement(
                algorithm=KisaoTerm(id="KISAO:0000029", name="Gillespie direct algorithm"),
                simulation_type="uniformTimeCourse"
            )
        ],
        sedml_files=["simulation.sedml"]
    )

    # Simulator only supports CVODE (ODE solver, not stochastic)
    ode_only_spec = {
        "id": "tellurium",
        "algorithms": [
            {
                "kisaoId": {"id": "KISAO_0000019"},  # CVODE
                "modelFormats": [{"id": "format_2585"}],
                "simulationTypes": [{"id": "SedUniformTimeCourseSimulation"}]
            }
        ]
    }

    with patch(
        "biosim_server.compatibility.simulator_matcher._get_simulator_spec",
        new_callable=AsyncMock
    ) as mock_get_spec:
        mock_get_spec.return_value = ode_only_spec

        simulators = await find_compatible_simulators(
            stochastic_content,
            sample_simulator_versions[:1]
        )

        # Should not match: Gillespie (stochastic) vs CVODE (ODE) are not equivalent
        assert len(simulators) == 0


# =============================================================================
# Integration tests - call real biosimulators.org API
# Run with: pytest -m integration
# =============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_simulator_spec_real_api() -> None:
    """Integration test: fetch real simulator spec from biosimulators.org."""
    # Fetch tellurium spec from the real API
    spec = await _get_simulator_spec("tellurium", "2.2.10")

    assert spec is not None
    assert spec["id"] == "tellurium"
    assert "algorithms" in spec
    assert len(spec["algorithms"]) > 0

    # Verify tellurium supports CVODE (KISAO:0000019)
    kisao_ids = [
        alg.get("kisaoId", {}).get("id", "")
        for alg in spec["algorithms"]
    ]
    assert any("0000019" in kid for kid in kisao_ids), "Tellurium should support CVODE"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_compatible_simulators_real_api() -> None:
    """Integration test: find compatible simulators using real API."""
    from biosim_server.biosim_runs.biosim_service import BiosimServiceRest

    # Load real OMEX file
    omex_path = Path(__file__).parent.parent / "fixtures" / "local_data" / \
        "BIOMD0000000010_tellurium_Negative_feedback_and_ultrasen.omex"
    with open(omex_path, "rb") as f:
        omex_content = parse_omex_content(f.read())

    # Get real simulator versions from biosimulators.org
    biosim_service = BiosimServiceRest()
    try:
        simulator_versions = await biosim_service.get_simulator_versions()
    finally:
        await biosim_service.close()

    # Find compatible simulators (calls real API for each simulator spec)
    simulators = await find_compatible_simulators(omex_content, simulator_versions)

    # The sample OMEX uses SBML + CVODE, so we expect some matches
    assert len(simulators) > 0, "Should find at least one compatible simulator"

    # Tellurium should be an exact match (it supports CVODE)
    exact_matches = [s for s in simulators if s.exact_match]
    exact_ids = [s.id for s in exact_matches]
    assert "tellurium" in exact_ids, f"Tellurium should be an exact match. Found: {exact_ids}"

    # Check that algorithms have names
    for sim in simulators:
        for alg in sim.algorithms:
            assert alg.name, f"Algorithm {alg.id} should have a name"

    # Print results for debugging (visible with pytest -v)
    equivalent_matches = [s for s in simulators if not s.exact_match]
    print(f"\nExact matches ({len(exact_matches)}): {[s.id for s in exact_matches]}")
    print(f"Equivalent matches ({len(equivalent_matches)}): {[s.id for s in equivalent_matches]}")
