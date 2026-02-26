# Biosim-Server: Comprehensive Overview

## Executive Summary

Biosim-Server is a distributed microservices platform designed for biosimulation verification and comparison. The system enables researchers to verify OMEX/COMBINE archives across multiple biological simulation engines (AMICI, COPASI, PySCES, Tellurium, VCell) and compare their outputs to ensure consistency and model correctness.

**Key Capabilities:**
- Upload and verify OMEX/COMBINE simulation archives
- Execute simulations across multiple biosimulators in parallel
- Compare simulation outputs with configurable tolerance settings
- Cache results to avoid redundant computations
- Scale horizontally via Kubernetes

---

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Client Applications                          │
│     (Biosimulations.org, BioCheckNet, LibreTexts, etc.)             │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    REST API (FastAPI + Uvicorn)                      │
│                         Port 8000, 3 Replicas                        │
│  Endpoints: /verify/omex, /verify/{id}, /verify/runs, /version      │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌────────────────────────────────┐  ┌────────────────────────────────┐
│       Temporal Server          │  │     Google Cloud Storage        │
│    Workflow Orchestration      │  │     OMEX File Storage           │
│      localhost:7233            │  │   files.biosimulations.dev      │
└────────────────────────────────┘  └────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│               Temporal Workers (3 Replicas)                          │
│                  verification_tasks queue                            │
│  Activities: submit_simulation, poll_status, generate_statistics    │
└─────────────────────────────────────────────────────────────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│    MongoDB       │  │ biosimulations   │  │   simdata API    │
│  biosimulations  │  │    .org API      │  │   HDF5 Data      │
│    database      │  │  Job Submission  │  │   Retrieval      │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

### Component Responsibilities

| Component | Technology | Responsibility |
|-----------|-----------|----------------|
| **REST API** | FastAPI + Uvicorn | Handle HTTP requests, validate input, start workflows |
| **Temporal Server** | Temporal 1.10 | Orchestrate distributed workflows, handle retries |
| **Workers** | Python + Temporal SDK | Execute activities (simulation submission, data retrieval, comparison) |
| **MongoDB** | Motor (async) | Store OMEX metadata, simulation runs, comparison results |
| **GCS** | gcloud-aio-storage | Persist OMEX files |
| **External APIs** | aiohttp | Submit simulations, retrieve HDF5 results |

---

## Data Flow

### OMEX Verification Flow

```
1. User uploads OMEX file + selects simulators
                    │
                    ▼
2. API validates request, computes file hash
                    │
                    ▼
3. Check cache: (file_hash + simulator_digest + cache_buster)
        │                           │
    [CACHE HIT]                 [CACHE MISS]
        │                           │
        ▼                           ▼
4a. Return cached          4b. Upload OMEX to GCS
    results                     Store metadata in MongoDB
                                    │
                                    ▼
                           5. Start OmexVerifyWorkflow
                                    │
                                    ▼
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              OmexSimWorkflow OmexSimWorkflow OmexSimWorkflow
                (AMICI)        (COPASI)        (Tellurium)
                    │               │               │
                    ▼               ▼               ▼
             Submit to          Submit to       Submit to
             biosim API         biosim API      biosim API
                    │               │               │
                    ▼               ▼               ▼
              Poll status       Poll status     Poll status
                    │               │               │
                    ▼               ▼               ▼
              Retrieve HDF5     Retrieve HDF5   Retrieve HDF5
                    │               │               │
                    └───────────────┼───────────────┘
                                    ▼
                    6. generate_statistics_activity
                       Compare outputs pairwise
                                    │
                                    ▼
                    7. Return VerifyWorkflowOutput
```

### Caching Strategy

| Cache Layer | Key | TTL | Purpose |
|-------------|-----|-----|---------|
| **OMEX Files** | MD5 hash | Permanent | Avoid re-uploading identical files |
| **Simulation Runs** | (file_hash, image_digest, cache_buster) | Permanent | Reuse simulation results |
| **Simulator Versions** | simulator_id | 1 hour | Reduce API calls to biosimulators.org |

---

## API Reference

### Endpoints

#### POST /verify/omex
Verify an OMEX archive across multiple simulators.

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| uploaded_file | File | Required | OMEX/COMBINE archive |
| simulators | list[str] | ["amici", "copasi", "pysces", "tellurium", "vcell"] | Simulators to use |
| rel_tol | float | 0.0001 | Relative tolerance for comparison |
| abs_tol_min | float | 0.001 | Minimum absolute tolerance |
| abs_tol_scale | float | 0.00001 | Scale factor for absolute tolerance |
| include_outputs | bool | false | Include raw data in response |
| observables | list[str] | null | Filter specific output variables |
| cache_buster | str | null | Force fresh simulation run |

**Response:**
```json
{
  "workflow_id": "omex-verification-abc123",
  "workflow_status": "PENDING|IN_PROGRESS|COMPLETED|FAILED",
  "compare_settings": {...},
  "timestamp": "2024-01-15T10:30:00Z",
  "workflow_results": {
    "comparison_statistics": [...]
  }
}
```

#### GET /verify/{workflow_id}
Get verification results for a workflow.

#### POST /verify/runs
Compare existing biosimulation runs by their IDs.

---

## Data Models

### Core Models

```python
# OMEX File metadata
OmexFile:
  file_hash_md5: str           # Unique identifier
  uploaded_filename: str       # Original name
  bucket_name: str             # GCS bucket
  omex_gcs_path: str          # Path in GCS
  file_size: int

# Simulator information
BiosimulatorVersion:
  id: str                      # e.g., "amici"
  name: str                    # e.g., "AMICI"
  version: str                 # e.g., "0.26.1"
  image_url: str               # Docker image URL
  image_digest: str            # Container digest

# Simulation run status
BiosimSimulationRun:
  id: str                      # Run ID from biosimulations.org
  name: str
  status: CREATED|QUEUED|RUNNING|SUCCEEDED|FAILED|RUN_ID_NOT_FOUND
  error_message: Optional[str]

# Comparison result
ComparisonStatistics:
  dataset_name: str
  simulator_version_i: str     # e.g., "amici:0.26.1"
  simulator_version_j: str     # e.g., "copasi:4.42"
  var_names: list[str]         # Variable names
  score: list[float]           # Tolerance score per variable
  is_close: list[bool]         # Within tolerance per variable
```

### MongoDB Collections

| Collection | Purpose | Key Fields |
|------------|---------|------------|
| BiosimOmex | OMEX file metadata | file_hash_md5, omex_gcs_path |
| BiosimSims | Simulation workflow runs | workflow_id, status, hdf5_file |
| BiosimCompare | Comparison results | (future use) |

---

## Workflow System

### Temporal Workflows

| Workflow | Purpose | Child Workflows |
|----------|---------|-----------------|
| **OmexVerifyWorkflow** | Orchestrate multi-simulator verification | OmexSimWorkflow (parallel) |
| **RunsVerifyWorkflow** | Compare existing simulation runs | None |
| **OmexSimWorkflow** | Execute single simulator run | None |

### Activities

| Activity | Purpose | Retryable |
|----------|---------|-----------|
| submit_biosim_simulation_run_activity | Submit job to biosimulations.org API | Yes |
| get_existing_biosim_simulation_run_activity | Retrieve cached simulation | Yes |
| generate_statistics_activity | Compare HDF5 outputs | Yes |

### Error Handling

- **Temporal Retries:** Automatic retry with exponential backoff
- **Heartbeats:** Long-running activities send heartbeats to prevent timeouts
- **Status Tracking:** Workflow state machine (PENDING → IN_PROGRESS → COMPLETED/FAILED)

---

## Comparison Algorithm

The system compares simulation outputs using a tolerance-based approach:

```python
# For each variable at each time point:
atol = max(atol_min, max(abs(arr1), abs(arr2)) * atol_scale)
diff = abs(arr1 - arr2)
score = max(diff / (atol + rel_tol * abs(arr2)))
is_close = score < 1.0
```

**Default Tolerances:**
- Relative tolerance (rel_tol): 0.0001 (0.01%)
- Absolute tolerance minimum (atol_min): 0.001
- Absolute tolerance scale (atol_scale): 0.00001

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| STORAGE_BUCKET | files.biosimulations.dev | GCS bucket for OMEX files |
| STORAGE_GCS_CREDENTIALS_FILE | "" | Path to GCS credentials JSON |
| TEMPORAL_SERVICE_URL | localhost:7233 | Temporal server address |
| MONGODB_URI | mongodb://localhost:27017 | MongoDB connection string |
| MONGODB_DATABASE | biosimulations | Database name |
| SIMDATA_API_BASE_URL | https://simdata.api.biosimulations.org | HDF5 data API |
| BIOSIMULATORS_API_BASE_URL | https://api.biosimulators.org | Simulator info API |
| BIOSIMULATIONS_API_BASE_URL | https://api.biosimulations.org | Job submission API |

### Local Development

```bash
# Required services
- MongoDB at localhost:27017
- Temporal at localhost:7233

# Optional
- GCS credentials for cloud storage
- Or use local file service for development
```

---

## Deployment

### Docker Images

| Image | Entry Point | Purpose |
|-------|-------------|---------|
| biosim-api | `uvicorn biosim_server.api.main:app` | REST API server |
| biosim-worker | `python -m biosim_server.worker.worker_main` | Temporal worker |

### Kubernetes Resources

```
kustomize/
├── base/
│   ├── api.yaml              # API Deployment (3 replicas)
│   ├── worker.yaml           # Worker Deployment (3 replicas)
│   ├── mongodb.yaml          # MongoDB StatefulSet
│   ├── configmap.yaml        # Environment configuration
│   └── secrets.yaml          # Sensitive configuration
└── overlays/
    ├── dev/                  # Development overrides
    └── prod/                 # Production overrides
```

### Deployment Commands

```bash
# Deploy Temporal (separate namespace)
kubectl create namespace temporal
cd kustomize/cluster
kubectl kustomize overlays/minikube | kubectl apply -n temporal -f -

# Deploy biosim-server
cd kustomize
kubectl kustomize overlays/dev | kubectl apply -f -
```

---

## Testing

### Test Structure

```
tests/
├── conftest.py               # Shared fixtures
├── api/                      # API endpoint tests
├── biosim_runs/              # Workflow and service tests
├── biosim_verify/            # Verification logic tests
├── common/                   # Utility tests
└── fixtures/                 # Mock data and services
```

### Running Tests

```bash
# All tests
poetry run pytest

# With coverage
poetry run pytest --cov=biosim_server --cov-report=html

# Specific test file
poetry run pytest tests/biosim_verify/test_hdf5_compare.py -v

# Skip integration tests
poetry run pytest -m "not integration"
```

### Test Infrastructure

| Component | Technology | Purpose |
|-----------|-----------|---------|
| MongoDB | testcontainers | Containerized MongoDB for integration tests |
| Temporal | In-memory client | Fast workflow testing without server |
| HTTP | httpx + mocks | Mock external API responses |

---

## External Integrations

### biosimulations.org API

**Base URL:** https://api.biosimulations.org

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Submit simulation | /runs | POST |
| Get run status | /runs/{id} | GET |
| Get simulators | /simulators | GET |

### simdata.api.biosimulations.org

**Base URL:** https://simdata.api.biosimulations.org

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Get HDF5 data | /runs/{run_id}/data | GET |
| Get HDF5 metadata | /runs/{run_id}/metadata | GET |

### biosimulators.org API

**Base URL:** https://api.biosimulators.org

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Get simulator versions | /simulators/{id} | GET |
| List all simulators | /simulators | GET |

---

## Development Workflow

### Adding a New Endpoint

1. Define Pydantic models in `biosim_server/*/models.py`
2. Add endpoint in `biosim_server/api/main.py`
3. Implement business logic in appropriate module
4. Add tests in `tests/`
5. Run type checking: `poetry run mypy biosim_server`

### Adding a New Workflow

1. Define workflow class in `biosim_server/*/workflows.py`
2. Define activities in `biosim_server/*/activities.py`
3. Register with worker in `biosim_server/worker/worker_main.py`
4. Add workflow tests with Temporal test utilities

### Code Conventions

- **Async/Await:** All I/O operations must be async
- **Type Hints:** Full type annotations required (mypy strict)
- **Pydantic:** Use Pydantic models for all data structures
- **Testing:** Unit tests for logic, integration tests for workflows

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Temporal connection refused | Temporal not running | Start Temporal server at localhost:7233 |
| MongoDB connection error | MongoDB not running | Start MongoDB at localhost:27017 |
| GCS permission denied | Missing credentials | Set STORAGE_GCS_CREDENTIALS_FILE |
| PyCharm debug fails | uvloop incompatibility | See README.md for workaround |

### Logs

- API logs: stdout from uvicorn
- Worker logs: stdout from worker process
- Temporal logs: Temporal server logs

---

## Version History

| Version | Changes |
|---------|---------|
| 0.2.3 | Updated pull secrets, Swagger CDN fix |
| 0.2.2 | Nginx ingress proxy-body-size increase |
| 0.2.1 | Initial public release |

---

## License and Contributing

- **Repository:** https://github.com/biosimulations/biosim-server
- **CI:** GitHub Actions (integrate.yml, deploy.yml)
- **Issues:** GitHub Issues

For development questions, refer to the team or open a GitHub issue.
