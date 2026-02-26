"""Tests for OMEX archive parsing."""

import pytest
from pathlib import Path

from biosim_server.compatibility.omex_parser import parse_omex_content


@pytest.fixture
def sample_omex_path() -> Path:
    """Path to sample OMEX file in fixtures."""
    return Path(__file__).parent.parent / "fixtures" / "local_data" / "BIOMD0000000010_tellurium_Negative_feedback_and_ultrasen.omex"


def test_parse_omex_content(sample_omex_path: Path) -> None:
    """Test parsing a real OMEX file."""
    with open(sample_omex_path, "rb") as f:
        file_content = f.read()

    omex_content = parse_omex_content(file_content)

    # Check SED-ML files found
    assert len(omex_content.sedml_files) == 1
    assert "BIOMD0000000010_url.sedml" in omex_content.sedml_files[0]

    # Check model formats found
    assert len(omex_content.model_formats) >= 1
    sbml_formats = [mf for mf in omex_content.model_formats
                    if "sbml" in mf.format_uri.lower()]
    assert len(sbml_formats) >= 1

    # Check simulations found
    assert len(omex_content.simulations) >= 1
    # The sample OMEX uses CVODE (KISAO:0000019)
    kisao_ids = [sim.algorithm_kisao_id for sim in omex_content.simulations]
    assert "KISAO:0000019" in kisao_ids

    # Check simulation types
    sim_types = [sim.simulation_type for sim in omex_content.simulations]
    assert "uniformTimeCourse" in sim_types


def test_parse_omex_model_language(sample_omex_path: Path) -> None:
    """Test that model language is extracted from SED-ML."""
    with open(sample_omex_path, "rb") as f:
        file_content = f.read()

    omex_content = parse_omex_content(file_content)

    # Check that at least one model has language info
    models_with_language = [mf for mf in omex_content.model_formats if mf.language]
    assert len(models_with_language) >= 1

    # The sample uses SBML level 2 version 4
    sbml_models = [mf for mf in models_with_language if mf.language and "sbml" in mf.language.lower()]
    assert len(sbml_models) >= 1


def test_parse_omex_deduplicates_simulations(sample_omex_path: Path) -> None:
    """Test that duplicate simulations are deduplicated."""
    with open(sample_omex_path, "rb") as f:
        file_content = f.read()

    omex_content = parse_omex_content(file_content)

    # Check no duplicate algorithm+type combinations
    seen = set()
    for sim in omex_content.simulations:
        key = (sim.algorithm_kisao_id, sim.simulation_type)
        assert key not in seen, f"Duplicate simulation: {key}"
        seen.add(key)


def test_parse_invalid_omex() -> None:
    """Test handling of invalid OMEX content."""
    with pytest.raises(Exception):
        parse_omex_content(b"not a valid zip file")
