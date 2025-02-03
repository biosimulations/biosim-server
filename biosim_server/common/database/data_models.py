from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, field_validator

ATTRIBUTE_VALUE_TYPE = int | float | str | bool | list[str] | list[int] | list[float] | list[bool]


class HDF5Attribute(BaseModel):
    key: str
    value: ATTRIBUTE_VALUE_TYPE


class HDF5Dataset(BaseModel):
    name: str
    shape: list[int]
    attributes: list[HDF5Attribute]

    @property
    def sedml_labels(self) -> list[str]:
        for attr in self.attributes:
            if attr.key == "sedmlDataSetLabels":
                if isinstance(attr.value, list) and all(isinstance(v, str) for v in attr.value):
                    return attr.value  # type: ignore
        return []


class HDF5Group(BaseModel):
    name: str
    attributes: list[HDF5Attribute]
    datasets: list[HDF5Dataset]


class HDF5File(BaseModel):
    filename: str
    id: str
    uri: str
    groups: list[HDF5Group]

    @property
    def datasets(self) -> dict[str, HDF5Dataset]:
        dataset_dict: dict[str, HDF5Dataset] = {}
        for group in self.groups:
            for dataset in group.datasets:
                dataset_dict[dataset.name] = dataset
        return dataset_dict


class Hdf5DataValues(BaseModel):
    # simulation_run_id: str
    # dataset_name: str
    shape: list[int]
    values: list[float]


class OmexFile(BaseModel):
    file_hash_md5: str
    uploaded_filename: str
    bucket_name: str
    omex_gcs_path: str
    file_size: int
    database_id: Optional[str] = None

    @field_validator('omex_gcs_path')
    def validate_omex_gcs_path(cls, v: str) -> str:
        if v.find("/") == 0:
            raise ValueError("omex_gcs_path must not be an absolute path")
        return v

    @field_validator('uploaded_filename')
    def validate_uploaded_filename(cls, v: str) -> str:
        if v.find("/") >= 0:
            raise ValueError("uploaded_filename must not contain any path separators")
        return v


class BiosimulatorVersion(BaseModel):
    id: str
    name: str
    version: str
    image_url: str
    image_digest: str
    created: str
    updated: str

class BiosimSimulationRunStatus(StrEnum):
    CREATED = 'CREATED'
    QUEUED = 'QUEUED',
    RUNNING = 'RUNNING',
    SKIPPED = 'SKIPPED',
    PROCESSING = 'PROCESSING',
    SUCCEEDED = 'SUCCEEDED',
    FAILED = 'FAILED',
    RUN_ID_NOT_FOUND = 'RUN_ID_NOT_FOUND',
    UNKNOWN = 'UNKNOWN'


class BiosimSimulationRun(BaseModel):
    """ data returned by api.biosimulations.org/runs/{run_id} """
    id: str
    name: str
    simulator_version: BiosimulatorVersion
    status: BiosimSimulationRunStatus
    error_message: str | None = None
    # cpus: Optional[int] = None
    # memory: Optional[int] = None         # (in GB)
    # maxTime: Optional[int] = None        # (in minutes)
    # envVars: Optional[list[str]] = None  # list of environment variables (e.g., ["OMP_NUM_THREADS=4"])
    # purpose: Optional[str] = None        # what does this correspond to?
    # submitted: Optional[str] = None      # datetime string (e.g. 2025-01-10T19:51:11.424Z)
    # updated: Optional[str] = None        # datetime string (e.g. 2025-01-10T19:51:11.424Z)
    # projectSize: Optional[int] = None    # (in bytes)
    # resultsSize: Optional[int] = None    # (in bytes)
    # runtime: Optional[int] = None        # (in milliseconds)
    # email: Optional[str] = None

    @field_validator('id')
    def validate_id(cls, v: str) -> str:
        if v.find("-") >= 0:
            raise ValueError("id must not contain any dashes, looks like a uuid")
        return v


class BiosimulatorWorkflowRun(BaseModel):
    workflow_id: str
    file_hash_md5: str
    image_digest: str
    cache_buster: str
    omex_file: OmexFile
    simulator_version: BiosimulatorVersion
    biosim_run: BiosimSimulationRun | None = None
    hdf5_file: HDF5File | None = None
    database_id: Optional[str] = None


class ComparisonStatistics(BaseModel):
    dataset_name: str
    simulator_version_i: str  # version of simulator used for run i <simulator_name>:<version>
    simulator_version_j: str  # version of simulator used for run j <simulator_name>:<version>
    var_names: list[str]
    score: Optional[list[float]] = None
    is_close: Optional[list[bool]] = None
    error_message: Optional[str] = None


class CompareSettings(BaseModel):
    user_description: str
    include_outputs: bool
    rel_tol: float
    abs_tol_min: float
    abs_tol_scale: float
    observables: Optional[list[str]] = None

# class CompareReport(BaseModel):
#     omex_file: OmexFile
#     simulator1: BiosimulatorVersion
#     simulator2: BiosimulatorVersion
#     stats: ComparisonStatistics
#
# class SimulatorComparison(BaseModel):
#     simRun1: BiosimSimulationRun
#     simRun2: BiosimSimulationRun
#     equivalent: bool
