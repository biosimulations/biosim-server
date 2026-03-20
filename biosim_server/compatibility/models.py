from pydantic import BaseModel


class ModelFormat(BaseModel):
    """Represents a model file format found in an OMEX archive."""
    format_uri: str  # e.g., "http://identifiers.org/combine.specifications/sbml"
    language: str | None = None  # e.g., "urn:sedml:language:sbml.level-2.version-4"
    location: str  # File path in archive


class KisaoTerm(BaseModel):
    """A KiSAO ontology term with ID and human-readable name."""
    id: str  # e.g., "KISAO:0000019"
    name: str  # e.g., "CVODE"


class SimulationRequirement(BaseModel):
    """Represents a simulation algorithm requirement from a SED-ML file."""
    algorithm: KisaoTerm
    simulation_type: str  # e.g., "uniformTimeCourse"


class OmexContent(BaseModel):
    """Parsed content from an OMEX archive."""
    model_formats: list[ModelFormat]
    simulations: list[SimulationRequirement]
    sedml_files: list[str]


class SimulatorVersionDetail(BaseModel):
    """Per-version compatibility details (populated in verbose mode)."""
    version: str
    image_url: str | None = None
    algorithms: list[KisaoTerm] = []
    exact: bool
    common_ancestor: KisaoTerm | None = None
    equivalence_category: KisaoTerm | None = None


class EligibleSimulator(BaseModel):
    """A simulator eligible to run the OMEX archive."""
    id: str
    name: str
    versions: list[str]
    exact: bool  # True if any version is an exact match
    version_details: list[SimulatorVersionDetail] | None = None


class CompatibilityResponse(BaseModel):
    """Response from the compatibility check endpoint."""
    omex_id: str  # MD5 hash of the OMEX file
    omex_content: OmexContent
    eligible_simulators: list[EligibleSimulator]
