"""Tests for the simulations router endpoints."""

from unittest.mock import patch, AsyncMock, MagicMock

from fastapi.testclient import TestClient

from biosim_server.api.main import app
from biosim_server.biosim_omex.models import OmexFile
from biosim_server.biosim_runs import BiosimulatorVersion


MOCK_OMEX_FILE = OmexFile(
    file_hash_md5="abc123def456",
    uploaded_filename="test.omex",
    bucket_name="test-bucket",
    omex_gcs_path="omex/abc123def456/test.omex",
    file_size=1024,
)

MOCK_SIMULATOR_VERSIONS = [
    BiosimulatorVersion(
        id="copasi",
        name="COPASI",
        version="4.34.251",
        image_url="ghcr.io/biosimulators/copasi:4.34.251",
        image_digest="sha256:abc123",
        created="2024-01-01T00:00:00Z",
        updated="2024-01-01T00:00:00Z",
    ),
    BiosimulatorVersion(
        id="tellurium",
        name="tellurium",
        version="2.2.10",
        image_url="ghcr.io/biosimulators/tellurium:2.2.10",
        image_digest="sha256:def456",
        created="2024-01-01T00:00:00Z",
        updated="2024-01-01T00:00:00Z",
    ),
]


def _make_request(
    omex_id: str = "abc123def456",
    simulators: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "omex_id": omex_id,
        "name": "Test Run",
        "simulators": simulators or [{"id": "copasi", "version": "4.34.251"}],
        "email_address": "test@example.com",
    }


@patch("biosim_server.simulations.router.get_temporal_client")
@patch("biosim_server.simulations.router.get_biosim_service")
@patch("biosim_server.simulations.router.get_omex_database_service")
def test_run_simulations_success(
    mock_get_omex_db: MagicMock,
    mock_get_biosim: MagicMock,
    mock_get_temporal: MagicMock,
) -> None:
    """Test successful simulation run request."""
    # Mock omex database
    omex_db = AsyncMock()
    omex_db.get_omex_file.return_value = MOCK_OMEX_FILE
    mock_get_omex_db.return_value = omex_db

    # Mock biosim service
    biosim_service = AsyncMock()
    biosim_service.get_simulator_versions.return_value = MOCK_SIMULATOR_VERSIONS
    mock_get_biosim.return_value = biosim_service

    # Mock temporal client
    temporal_client = AsyncMock()
    workflow_handle = AsyncMock()
    workflow_handle.id = "sim-run-test"
    temporal_client.start_workflow.return_value = workflow_handle
    mock_get_temporal.return_value = temporal_client

    client = TestClient(app)
    response = client.post("/simulations/run", json=_make_request())

    assert response.status_code == 200
    data = response.json()
    assert "processing_id" in data
    assert data["processing_id"].startswith("sim-run-")
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["simulator_id"] == "copasi"
    assert data["jobs"][0]["version"] == "4.34.251"
    assert data["jobs"][0]["status"] == "processing"
    assert len(data["jobs"][0]["job_id"]) == 32  # hex UUID


@patch("biosim_server.simulations.router.get_temporal_client")
@patch("biosim_server.simulations.router.get_biosim_service")
@patch("biosim_server.simulations.router.get_omex_database_service")
def test_run_simulations_multiple_simulators(
    mock_get_omex_db: MagicMock,
    mock_get_biosim: MagicMock,
    mock_get_temporal: MagicMock,
) -> None:
    """Test simulation run with multiple simulators."""
    omex_db = AsyncMock()
    omex_db.get_omex_file.return_value = MOCK_OMEX_FILE
    mock_get_omex_db.return_value = omex_db

    biosim_service = AsyncMock()
    biosim_service.get_simulator_versions.return_value = MOCK_SIMULATOR_VERSIONS
    mock_get_biosim.return_value = biosim_service

    temporal_client = AsyncMock()
    temporal_client.start_workflow.return_value = AsyncMock(id="sim-run-test")
    mock_get_temporal.return_value = temporal_client

    client = TestClient(app)
    request = _make_request(simulators=[
        {"id": "copasi", "version": "4.34.251"},
        {"id": "tellurium", "version": "2.2.10"},
    ])
    response = client.post("/simulations/run", json=request)

    assert response.status_code == 200
    data = response.json()
    assert len(data["jobs"]) == 2
    assert data["jobs"][0]["simulator_id"] == "copasi"
    assert data["jobs"][1]["simulator_id"] == "tellurium"
    # Each job has a unique ID
    assert data["jobs"][0]["job_id"] != data["jobs"][1]["job_id"]


@patch("biosim_server.simulations.router.get_omex_database_service")
def test_run_simulations_omex_not_found(mock_get_omex_db: MagicMock) -> None:
    """Test 404 when OMEX file not found."""
    omex_db = AsyncMock()
    omex_db.get_omex_file.return_value = None
    mock_get_omex_db.return_value = omex_db

    client = TestClient(app)
    response = client.post("/simulations/run", json=_make_request(omex_id="nonexistent"))

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@patch("biosim_server.simulations.router.get_biosim_service")
@patch("biosim_server.simulations.router.get_omex_database_service")
def test_run_simulations_simulator_not_found(
    mock_get_omex_db: MagicMock,
    mock_get_biosim: MagicMock,
) -> None:
    """Test 400 when requested simulator version not found."""
    omex_db = AsyncMock()
    omex_db.get_omex_file.return_value = MOCK_OMEX_FILE
    mock_get_omex_db.return_value = omex_db

    biosim_service = AsyncMock()
    biosim_service.get_simulator_versions.return_value = MOCK_SIMULATOR_VERSIONS
    mock_get_biosim.return_value = biosim_service

    client = TestClient(app)
    request = _make_request(simulators=[{"id": "nonexistent", "version": "1.0.0"}])
    response = client.post("/simulations/run", json=request)

    assert response.status_code == 400
    assert "not found" in response.json()["detail"]


@patch("biosim_server.simulations.router.get_temporal_client")
def test_get_simulation_status_success(mock_get_temporal: MagicMock) -> None:
    """Test successful status query."""
    from biosim_server.simulations.models import ConglomerateStatus, SimulationJobStatus

    expected = ConglomerateStatus(
        processing_id="sim-run-test",
        jobs=[
            SimulationJobStatus(
                job_id="abc123",
                simulator_id="copasi",
                version="4.34.251",
                status="success",
                biosimulations_run_id="ext-123",
            )
        ],
    )

    temporal_client = MagicMock()
    workflow_handle = AsyncMock()
    workflow_handle.query.return_value = expected
    temporal_client.get_workflow_handle.return_value = workflow_handle
    mock_get_temporal.return_value = temporal_client

    client = TestClient(app)
    response = client.get("/simulations/sim-run-test")

    assert response.status_code == 200
    data = response.json()
    assert data["processing_id"] == "sim-run-test"
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["status"] == "success"
    assert data["jobs"][0]["biosimulations_run_id"] == "ext-123"


@patch("biosim_server.simulations.router.get_temporal_client")
def test_get_simulation_status_not_found(mock_get_temporal: MagicMock) -> None:
    """Test 404 when workflow not found."""
    temporal_client = MagicMock()
    workflow_handle = AsyncMock()
    workflow_handle.query.side_effect = Exception("Workflow not found")
    temporal_client.get_workflow_handle.return_value = workflow_handle
    mock_get_temporal.return_value = temporal_client

    client = TestClient(app)
    response = client.get("/simulations/nonexistent")

    assert response.status_code == 404


def test_run_simulations_missing_fields() -> None:
    """Test validation error for missing required fields."""
    client = TestClient(app)
    response = client.post("/simulations/run", json={"omex_id": "abc"})
    assert response.status_code == 422
