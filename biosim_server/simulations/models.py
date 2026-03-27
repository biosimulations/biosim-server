from pydantic import BaseModel


class SimulatorSelection(BaseModel):
    id: str        # e.g., "copasi"
    version: str   # e.g., "4.34.251"


class RunSimulationRequest(BaseModel):
    omex_id: str
    name: str
    simulators: list[SimulatorSelection]
    commercial_acknowledgement: bool = False
    email_address: str
    newsletter_consent: bool = False


class SimulationJobStatus(BaseModel):
    job_id: str                                  # Our generated UUID
    simulator_id: str                            # e.g., "copasi"
    version: str                                 # e.g., "4.34.251"
    status: str                                  # "processing" | "success" | "failure"
    algorithm: str | None = None
    error: str | None = None
    biosimulations_run_id: str | None = None     # External reference


class ConglomerateStatus(BaseModel):
    processing_id: str                           # Temporal parent workflow ID
    jobs: list[SimulationJobStatus]
