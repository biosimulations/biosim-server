"""Tests for simulator matching logic."""

from pathlib import Path

import pytest

from biosim_server.biosim_runs import BiosimulatorVersion
from biosim_server.compatibility.models import OmexContent, ModelFormat, SimulationRequirement
from biosim_server.compatibility.omex_parser import parse_omex_content
from biosim_server.compatibility.simulator_matcher import (
    _normalize_kisao_id,
    _get_algorithm_group,
    _get_simulator_spec,
    find_compatible_simulators,
)


def test_normalize_kisao_id() -> None:
    """Test KiSAO ID normalization."""
    assert _normalize_kisao_id("KISAO:0000019") == "KISAO:0000019"
    assert _normalize_kisao_id("KISAO_0000019") == "KISAO:0000019"
    assert _normalize_kisao_id("0000019") == "KISAO:0000019"


def test_get_algorithm_group() -> None:
    """Test algorithm group detection."""
    # ODE solvers
    assert _get_algorithm_group("KISAO:0000019") == "ode_solvers"  # CVODE
    assert _get_algorithm_group("KISAO:0000088") == "ode_solvers"  # LSODA
    assert _get_algorithm_group("KISAO:0000030") == "ode_solvers"  # Euler

    # Stochastic
    assert _get_algorithm_group("KISAO:0000029") == "stochastic"  # Gillespie

    # Steady state
    assert _get_algorithm_group("KISAO:0000569") == "steady_state"  # NLEQ2

    # Unknown algorithm
    assert _get_algorithm_group("KISAO:9999999") is None


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
                algorithm_kisao_id="KISAO:0000019",  # CVODE
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

    exact, equivalent = await find_compatible_simulators(empty_content, [])
    assert exact == []
    assert equivalent == []


@pytest.mark.asyncio
async def test_find_compatible_simulators_no_simulators(
    sample_omex_content: OmexContent
) -> None:
    """Test with no available simulators passed in."""
    exact, equivalent = await find_compatible_simulators(sample_omex_content, [])
    assert exact == []
    assert equivalent == []


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

        exact, equivalent = await find_compatible_simulators(
            sample_omex_content,
            sample_simulator_versions[:1]  # Just tellurium
        )

        assert len(exact) == 1
        assert exact[0].id == "tellurium"
        assert "KISAO:0000019" in exact[0].algorithms
        assert len(equivalent) == 0


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

        exact, equivalent = await find_compatible_simulators(
            sample_omex_content,
            sample_simulator_versions[1:2]  # Just copasi
        )

        # LSODA is not an exact match for CVODE, but they're equivalent ODE solvers
        assert len(exact) == 0
        assert len(equivalent) == 1
        assert equivalent[0].id == "copasi"
        assert "KISAO:0000088" in equivalent[0].algorithms


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
                algorithm_kisao_id="KISAO:0000019",
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

        exact, equivalent = await find_compatible_simulators(
            cellml_content,
            sample_simulator_versions[:1]
        )

        # Should not match because format doesn't match
        assert len(exact) == 0
        assert len(equivalent) == 0


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
    exact, equivalent = await find_compatible_simulators(omex_content, simulator_versions)

    # The sample OMEX uses SBML + CVODE, so we expect some matches
    all_compatible = exact + equivalent
    assert len(all_compatible) > 0, "Should find at least one compatible simulator"

    # Tellurium should be in exact matches (it supports CVODE)
    exact_ids = [s.id for s in exact]
    assert "tellurium" in exact_ids, f"Tellurium should be an exact match. Found: {exact_ids}"

    # Print results for debugging (visible with pytest -v)
    print(f"\nExact matches ({len(exact)}): {[s.id for s in exact]}")
    print(f"Equivalent matches ({len(equivalent)}): {[s.id for s in equivalent]}")
