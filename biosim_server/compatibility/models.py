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


class CompatibleSimulator(BaseModel):
    """A simulator that can run the OMEX archive."""
    id: str
    name: str
    version: str
    image_url: str | None = None
    algorithms: list[KisaoTerm]  # KiSAO terms that match
    exact_match: bool  # True if simulator supports exact algorithm, False if equivalent
    common_ancestor: KisaoTerm | None = None  # Most specific shared ontology ancestor (for equivalent matches)
    equivalence_category: KisaoTerm | None = None  # Curated category that caused the match (for equivalent matches)


class CompatibilityResponse(BaseModel):
    """Response from the compatibility check endpoint."""
    omex_content: OmexContent
    simulators: list[CompatibleSimulator]  # All compatible simulators (exact and equivalent)
