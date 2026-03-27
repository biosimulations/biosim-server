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

The response returns a single list of compatible simulators, each with an `exact_match` flag:

```json
{
  "omex_content": {
    "model_formats": [...],
    "simulations": [...],
    "sedml_files": [...]
  },
  "simulators": [...]
}
```

Each simulator includes:
- `exact_match: true` - Supports the **exact algorithm** requested (e.g., CVODE for CVODE)
- `exact_match: false` - Supports an **equivalent algorithm** from the same category
- `common_ancestor` - (equivalent matches only) The most specific shared ancestor in the KiSAO ontology between the requested and matched algorithms
- `equivalence_category` - (equivalent matches only) The curated category that caused the match (from `equivalence_categories.yaml`)

Algorithm information includes both the KiSAO ID and human-readable name (e.g., `{"id": "KISAO:0000019", "name": "CVODE"}`).

Algorithm categories for equivalent matching include:

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
├── __init__.py                    # Module exports
├── equivalence_categories.yaml    # Curated algorithm equivalence groups
├── kisao_data.py                  # Auto-generated KiSAO ontology data
├── models.py                      # Pydantic models for request/response
├── omex_parser.py                 # ZIP + XML parsing logic
├── simulator_matcher.py           # Algorithm matching and API calls
└── router.py                      # FastAPI endpoint definition
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

Response (abbreviated — a real response includes more simulators):
```json
{
  "omex_content": {
    "model_formats": [
      {
        "format_uri": "http://identifiers.org/combine.specifications/sbml",
        "language": "urn:sedml:language:sbml.level-2.version-4",
        "location": "BIOMD0000000010_url.xml"
      }
    ],
    "simulations": [
      {
        "algorithm": {
          "id": "KISAO:0000019",
          "name": "CVODE"
        },
        "simulation_type": "uniformTimeCourse"
      }
    ],
    "sedml_files": ["BIOMD0000000010_url.sedml"]
  },
  "simulators": [
    {
      "id": "tellurium",
      "name": "tellurium",
      "version": "2.2.1",
      "image_url": "ghcr.io/biosimulators/tellurium:2.2.1",
      "algorithms": [{"id": "KISAO:0000019", "name": "CVODE"}],
      "exact_match": true,
      "common_ancestor": null,
      "equivalence_category": null
    },
    {
      "id": "vcell",
      "name": "Virtual Cell",
      "version": "7.4.0.26",
      "image_url": "ghcr.io/biosimulators/vcell:7.4.0.26",
      "algorithms": [{"id": "KISAO:0000019", "name": "CVODE"}],
      "exact_match": true,
      "common_ancestor": null,
      "equivalence_category": null
    },
    {
      "id": "amici",
      "name": "AMICI",
      "version": "0.11.22",
      "image_url": "ghcr.io/biosimulators/amici:0.11.22",
      "algorithms": [{"id": "KISAO:0000496", "name": "CVODES"}],
      "exact_match": false,
      "common_ancestor": {"id": "KISAO:0000433", "name": "CVODE-like method"},
      "equivalence_category": {"id": "KISAO:0000433", "name": "CVODE-like method"}
    },
    {
      "id": "copasi",
      "name": "COPASI",
      "version": "4.34.251",
      "image_url": "ghcr.io/biosimulators/copasi:4.34.251",
      "algorithms": [
        {"id": "KISAO:0000560", "name": "LSODA/LSODAR hybrid method"},
        {"id": "KISAO:0000304", "name": "Radau method"}
      ],
      "exact_match": false,
      "common_ancestor": {"id": "KISAO:0000694", "name": "ODE solver"},
      "equivalence_category": {"id": "KISAO:0000694", "name": "ODE solver"}
    }
  ]
}
```

In this example (using the `BIOMD0000000010` test fixture):
- The model uses SBML with the CVODE algorithm
- Tellurium and VCell directly support CVODE (`exact_match: true`)
- AMICI supports CVODES, matched via the "CVODE-like method" category — a close relative
- COPASI supports LSODA/LSODAR and Radau, matched via the broader "ODE solver" category
