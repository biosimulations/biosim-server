# CLAUDE.md - Biosim-Server Development Guide

## Project Overview

Biosim-Server is a distributed microservices platform for biosimulation verification and comparison. It runs biological simulations across multiple simulators (AMICI, COPASI, PySCES, Tellurium, VCell) and compares outputs to verify model correctness.

**Version:** 0.2.3
**Python:** 3.13
**Production URL:** https://biosim.biosimulations.org/docs

## Quick Commands

```bash
# Install dependencies
poetry install

# Run API server locally
poetry run uvicorn biosim_server.api.main:app --host 0.0.0.0 --port 8000

# Run worker locally
poetry run python -m biosim_server.worker.worker_main

# Run tests
poetry run pytest

# Run tests with coverage
poetry run pytest --cov=biosim_server

# Type checking
poetry run mypy biosim_server

# Single test file
poetry run pytest tests/biosim_runs/test_sim_workflow.py -v
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   REST API (FastAPI)                     │
│                   Port 8000                              │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│          Temporal Workflow Orchestration                 │
│              localhost:7233                              │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│          Worker Processes (Temporal Workers)             │
│              verification_tasks queue                    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│     MongoDB + Google Cloud Storage                       │
└─────────────────────────────────────────────────────────┘
```

## Directory Structure

```
biosim_server/
├── api/                    # FastAPI REST endpoints
│   └── main.py            # App entry, all endpoints
├── biosim_runs/           # Simulation execution
│   ├── activities.py      # Temporal activities (submit, poll, retrieve)
│   ├── biosim_service.py  # HTTP client for biosimulations.org API
│   ├── database.py        # MongoDB operations for sim runs
│   ├── models.py          # Pydantic models (BiosimulatorVersion, etc.)
│   └── workflows.py       # OmexSimWorkflow
├── biosim_verify/         # Verification workflows
│   ├── activities.py      # generate_statistics_activity
│   ├── models.py          # Verification models
│   ├── omex_verify_workflow.py  # Multi-simulator OMEX verification
│   ├── runs_verify_workflow.py  # Compare existing runs
│   └── hdf5_compare.py    # Comparison logic
├── biosim_omex/           # OMEX file handling
│   ├── database.py        # MongoDB for OMEX metadata
│   ├── models.py          # OmexFile model
│   └── omex_storage.py    # Upload/caching logic
├── common/
│   ├── storage/           # GCS file operations
│   ├── temporal/          # Temporal client utilities
│   ├── hpc/               # SLURM integration
│   └── ssh/               # SSH service
├── worker/
│   └── worker_main.py     # Worker entry point
├── config.py              # Pydantic Settings
├── dependencies.py        # Global service instances
└── version.py             # Version string
```

## Key API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/verify/omex` | POST | Verify OMEX file across simulators |
| `/verify/{workflow_id}` | GET | Get verification results |
| `/verify/runs` | POST | Compare existing biosimulation runs |
| `/version` | GET | Get API version |
| `/docs` | GET | Swagger UI |

## Database Collections (MongoDB)

- **BiosimOmex** - OMEX file metadata (file_hash_md5, gcs_path)
- **BiosimSims** - Simulation workflow runs (workflow_id, status, results)
- **BiosimCompare** - Comparison results

## Key Patterns

### Async Everywhere
All I/O is async: FastAPI endpoints, MongoDB (Motor), HTTP (aiohttp), file ops.

### Temporal Workflows
- `OmexSimWorkflow` - Run single simulator on OMEX file
- `OmexVerifyWorkflow` - Orchestrate multiple simulators in parallel
- `RunsVerifyWorkflow` - Compare existing runs

### Caching
- OMEX files cached by MD5 hash in MongoDB + GCS
- Sim results cached by (file_hash_md5, image_digest, cache_buster)
- Simulator versions cached in memory (aiocache, 1hr TTL)

### Dependency Injection
Global services in `dependencies.py`:
```python
get_file_service()          # GCS operations
get_database_service()      # MongoDB for runs
get_omex_database_service() # MongoDB for OMEX
get_biosim_service()        # biosimulations.org API client
get_temporal_client()       # Temporal workflow client
```

## Configuration

Environment variables (see `config.py`):
```
STORAGE_BUCKET=files.biosimulations.dev
TEMPORAL_SERVICE_URL=localhost:7233
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=biosimulations
SIMDATA_API_BASE_URL=https://simdata.api.biosimulations.org
BIOSIMULATIONS_API_BASE_URL=https://api.biosimulations.org
```

## Testing

- **Framework:** pytest with pytest-asyncio
- **MongoDB:** testcontainers for integration tests
- **Temporal:** In-memory test client/worker
- **Fixtures:** `tests/fixtures/` for mocks and test data

```bash
# Run specific test
pytest tests/biosim_verify/test_hdf5_compare.py -v

# Run with specific marker
pytest -m "not integration"
```

## Docker

```bash
# Build API image
docker build -f Dockerfile-api -t biosim-api .

# Build Worker image
docker build -f Dockerfile-worker -t biosim-worker .
```

## Kubernetes

```bash
# Deploy to cluster
cd kustomize
kubectl kustomize overlays/dev | kubectl apply -f -

# Check status
kubectl get pods -n biosim
```

## Important Notes

1. **Temporal Required** - Workers need a running Temporal server at `localhost:7233`
2. **MongoDB Required** - Database must be running for most operations
3. **GCS Credentials** - Set `STORAGE_GCS_CREDENTIALS_FILE` for cloud storage
4. **PyCharm Debug Issue** - See README.md for uvloop debugging workaround
5. **Version Source of Truth** - `biosim_server/version.py`

## External Services

- **biosimulations.org API** - Submit and poll simulation jobs
- **simdata.api.biosimulations.org** - Retrieve HDF5 simulation outputs
- **api.biosimulators.org** - Get simulator version info
- **Google Cloud Storage** - OMEX file storage