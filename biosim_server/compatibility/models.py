from pydantic import BaseModel


class ModelFormat(BaseModel):
    """Represents a model file format found in an OMEX archive."""
    format_uri: str  # e.g., "http://identifiers.org/combine.specifications/sbml"
    language: str | None = None  # e.g., "urn:sedml:language:sbml.level-2.version-4"
    location: str  # File path in archive


class SimulationRequirement(BaseModel):
    """Represents a simulation algorithm requirement from a SED-ML file."""
    algorithm_kisao_id: str  # e.g., "KISAO:0000019"
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
    algorithms: list[str]  # KiSAO IDs that match


class CompatibilityResponse(BaseModel):
    """Response from the compatibility check endpoint."""
    omex_content: OmexContent
    compatible_simulators: list[CompatibleSimulator]  # Exact algorithm matches
    equivalent_simulators: list[CompatibleSimulator]  # Equivalent algorithm matches
