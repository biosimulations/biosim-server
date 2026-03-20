"""Tests for the compatibility router endpoint."""

import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from biosim_server.api.main import app
from biosim_server.biosim_runs import BiosimulatorVersion


@pytest.fixture
def sample_omex_path() -> Path:
    """Path to sample OMEX file in fixtures."""
    return Path(__file__).parent.parent / "fixtures" / "local_data" / "BIOMD0000000010_tellurium_Negative_feedback_and_ultrasen.omex"


@pytest.fixture
def mock_biosim_service() -> AsyncMock:
    """Mock biosim service with simulator versions."""
    service = AsyncMock()
    service.get_simulator_versions.return_value = [
        BiosimulatorVersion(
            id="tellurium",
            name="tellurium",
            version="2.2.10",
            image_url="ghcr.io/biosimulators/tellurium:2.2.10",
            image_digest="sha256:0c22827b4682273810d48ea606ef50c7163e5f5289740951c00c64c669409eae",
            created="2024-10-10T22:00:50.110Z",
            updated="2024-10-10T22:00:50.110Z"
        ),
    ]
    return service


def test_check_compatibility_no_input() -> None:
    """Test that endpoint requires either file or URL."""
    client = TestClient(app)
    response = client.post("/compatibility/check")
    # Should get 400 because neither uploaded_file nor archive_url provided
    assert response.status_code == 400
    assert "Provide either" in response.json()["detail"]


def test_check_compatibility_invalid_file() -> None:
    """Test with an invalid file."""
    client = TestClient(app)
    response = client.post(
        "/compatibility/check",
        files={"uploaded_file": ("test.omex", b"not a valid zip", "application/octet-stream")}
    )
    assert response.status_code == 400
    assert "Failed to parse OMEX" in response.json()["detail"]


@patch("biosim_server.compatibility.router.get_biosim_service")
def test_check_compatibility_service_unavailable(
    mock_get_service: AsyncMock
) -> None:
    """Test when biosim service is unavailable."""
    mock_get_service.return_value = None

    client = TestClient(app)
    # Create a minimal valid OMEX (just a zip with manifest)
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        manifest = '''<?xml version="1.0" encoding="UTF-8"?>
<omexManifest xmlns="http://identifiers.org/combine.specifications/omex-manifest">
</omexManifest>'''
        zf.writestr("manifest.xml", manifest)
    buf.seek(0)

    response = client.post(
        "/compatibility/check",
        files={"uploaded_file": ("test.omex", buf.getvalue(), "application/octet-stream")}
    )
    # Should fail because no SED-ML files
    assert response.status_code == 400
    assert "No SED-ML files" in response.json()["detail"]


@patch("biosim_server.compatibility.router.get_biosim_service")
@patch("biosim_server.compatibility.simulator_matcher._get_simulator_spec")
def test_check_compatibility_success(
    mock_get_spec: AsyncMock,
    mock_get_service: AsyncMock,
    sample_omex_path: Path,
    mock_biosim_service: AsyncMock
) -> None:
    """Test successful compatibility check."""
    mock_get_service.return_value = mock_biosim_service

    # Mock the simulator spec response
    mock_get_spec.return_value = {
        "id": "tellurium",
        "name": "tellurium",
        "version": "2.2.10",
        "algorithms": [
            {
                "kisaoId": {"id": "KISAO_0000019"},
                "modelFormats": [{"id": "format_2585"}],  # SBML
                "simulationTypes": [{"id": "SedUniformTimeCourseSimulation"}]
            }
        ]
    }

    client = TestClient(app)
    with open(sample_omex_path, "rb") as f:
        response = client.post(
            "/compatibility/check",
            files={"uploaded_file": ("test.omex", f, "application/octet-stream")}
        )

    assert response.status_code == 200
    data = response.json()

    # Check response structure
    assert "omex_id" in data
    assert "omex_content" in data
    assert "eligible_simulators" in data

    # Check omex_id is an MD5 hex string
    assert len(data["omex_id"]) == 32

    # Check OMEX content was parsed
    assert len(data["omex_content"]["sedml_files"]) >= 1
    assert len(data["omex_content"]["simulations"]) >= 1

    # Check simulations have algorithm with id and name
    for sim in data["omex_content"]["simulations"]:
        assert "algorithm" in sim
        assert "id" in sim["algorithm"]
        assert "name" in sim["algorithm"]

    # Check at least tellurium is compatible (it supports CVODE)
    simulator_ids = [s["id"] for s in data["eligible_simulators"]]
    assert "tellurium" in simulator_ids

    # Check simulator has correct shape
    tellurium = next(s for s in data["eligible_simulators"] if s["id"] == "tellurium")
    assert tellurium["exact"] is True
    assert isinstance(tellurium["versions"], list)
    assert "2.2.10" in tellurium["versions"]
    # version_details not populated in default (non-verbose) mode
    assert tellurium["version_details"] is None
