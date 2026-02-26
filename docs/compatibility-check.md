# OMEX Compatibility Check Endpoint

## Goal

The `/compatibility/check` endpoint allows users to upload an OMEX/COMBINE archive and discover which biosimulators can execute it. This helps users:

1. **Select the right simulator** before submitting a simulation job
2. **Understand model requirements** by seeing what algorithms and formats are needed
3. **Find alternatives** when their preferred simulator isn't available

## How It Works

### Input

The endpoint accepts a single OMEX file upload via multipart form data.

### Processing Pipeline

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Parse OMEX     │ --> │  Extract        │ --> │  Match Against  │
│  Archive        │     │  Requirements   │     │  Simulators     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

#### Step 1: Parse OMEX Archive

The OMEX file is a ZIP archive containing:
- `manifest.xml` - Lists all files and their formats
- SED-ML files (`.sedml`) - Define simulations to run
- Model files (`.xml`, etc.) - The actual models (SBML, CellML, etc.)

We extract:
- **Model formats** from `manifest.xml` (e.g., SBML, CellML)
- **SED-ML file locations** to parse for simulation details

#### Step 2: Extract Requirements

From each SED-ML file, we extract:
- **Algorithm KiSAO IDs** - Standardized identifiers for simulation algorithms (e.g., `KISAO:0000019` for CVODE)
- **Simulation types** - uniformTimeCourse, steadyState, oneStep, etc.
- **Model language** - More specific than format (e.g., `urn:sedml:language:sbml.level-2.version-4`)

Example SED-ML snippet:
```xml
<uniformTimeCourse id="sim0" initialTime="0" outputEndTime="100">
  <algorithm kisaoID="KISAO:0000019"/>  <!-- CVODE solver -->
</uniformTimeCourse>
```

#### Step 3: Match Against Simulators

For each available simulator, we fetch its specification from `api.biosimulators.org` and check:

1. **Model format support** - Does the simulator support SBML/CellML/etc.?
2. **Simulation type support** - Can it run time courses, steady states, etc.?
3. **Algorithm support** - Does it implement the requested algorithm?

### Output

The response categorizes simulators into two groups:

```json
{
  "omex_content": {
    "model_formats": [...],
    "simulations": [...],
    "sedml_files": [...]
  },
  "compatible_simulators": [...],
  "equivalent_simulators": [...]
}
```

#### Exact Matches (`compatible_simulators`)

Simulators that support the **exact algorithm** requested. For example, if the SED-ML specifies CVODE (`KISAO:0000019`), these simulators explicitly support CVODE.

#### Equivalent Matches (`equivalent_simulators`)

Simulators that support an **equivalent algorithm** from the same category. Algorithm categories include:

| Category | Example Algorithms |
|----------|-------------------|
| ODE Solvers | CVODE, LSODA, Euler, Runge-Kutta 4, BDF |
| Stochastic | Gillespie, Gibson-Bruck, Tau-leaping |
| Steady State | NLEQ2, Newton's method, Kinsol |
| Hybrid | Hybrid Gibson-Bruck, Hybrid Runge-Kutta |

This allows users to find simulators that can solve the same type of problem even if they use a different specific algorithm.

## Implementation Details

### Module Structure

```
biosim_server/compatibility/
├── __init__.py           # Module exports
├── models.py             # Pydantic models for request/response
├── omex_parser.py        # ZIP + XML parsing logic
├── simulator_matcher.py  # Algorithm matching and API calls
└── router.py             # FastAPI endpoint definition
```

### Key Design Decisions

1. **Standard library only for parsing** - Uses `zipfile` and `xml.etree.ElementTree` to avoid external dependencies for OMEX parsing.

2. **Cached simulator specs** - Simulator specifications are cached for 1 hour using `aiocache` to reduce API calls to biosimulators.org.

3. **Latest versions only** - Only the latest version of each simulator is checked, avoiding duplicate results.

4. **Graceful degradation** - If a simulator spec can't be fetched, it's skipped rather than failing the entire request.

### Format Mappings

OMEX format URIs are mapped to EDAM format IDs used by biosimulators:

| OMEX Format URI | EDAM ID | Format |
|-----------------|---------|--------|
| `http://identifiers.org/combine.specifications/sbml` | `format_2585` | SBML |
| `http://identifiers.org/combine.specifications/cellml` | `format_3240` | CellML |
| `http://identifiers.org/combine.specifications/neuroml` | `format_3971` | NeuroML |

### Error Handling

| Condition | HTTP Status | Message |
|-----------|-------------|---------|
| Invalid ZIP file | 400 | "Failed to parse OMEX archive" |
| No SED-ML files | 400 | "No SED-ML files found in the OMEX archive" |
| No simulations defined | 400 | "No simulations found in the SED-ML files" |
| Biosim service unavailable | 503 | "Biosim service not available" |

## Usage Example

```bash
curl -X POST "http://localhost:8000/compatibility/check" \
  -F "uploaded_file=@model.omex"
```

Response:
```json
{
  "omex_content": {
    "model_formats": [
      {
        "format_uri": "http://identifiers.org/combine.specifications/sbml",
        "language": "urn:sedml:language:sbml.level-2.version-4",
        "location": "model.xml"
      }
    ],
    "simulations": [
      {
        "algorithm_kisao_id": "KISAO:0000019",
        "simulation_type": "uniformTimeCourse"
      }
    ],
    "sedml_files": ["simulation.sedml"]
  },
  "compatible_simulators": [
    {
      "id": "tellurium",
      "name": "tellurium",
      "version": "2.2.10",
      "image_url": "ghcr.io/biosimulators/tellurium:2.2.10",
      "algorithms": ["KISAO:0000019"]
    },
    {
      "id": "copasi",
      "name": "COPASI",
      "version": "4.45.296",
      "image_url": "ghcr.io/biosimulators/copasi:4.45.296",
      "algorithms": ["KISAO:0000019"]
    }
  ],
  "equivalent_simulators": [
    {
      "id": "vcell",
      "name": "Virtual Cell",
      "version": "7.7.0.13",
      "image_url": "ghcr.io/biosimulators/vcell:7.7.0.13",
      "algorithms": ["KISAO:0000088"]
    }
  ]
}
```

In this example:
- The model uses SBML with the CVODE algorithm
- Tellurium and COPASI directly support CVODE (exact matches)
- VCell supports LSODA, an equivalent ODE solver (equivalent match)
