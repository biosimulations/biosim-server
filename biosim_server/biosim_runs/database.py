import logging
from abc import abstractmethod, ABC

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo.results import InsertOneResult
from typing_extensions import override

from biosim_server.biosim_runs.models import BiosimulatorWorkflowRun
from biosim_server.config import get_settings

logger = logging.getLogger(__name__)




class DocumentNotFoundError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class DatabaseService(ABC):

    @abstractmethod
    async def insert_biosimulator_workflow_run(self, sim_workflow_run: BiosimulatorWorkflowRun) -> BiosimulatorWorkflowRun:
        pass

    @abstractmethod
    async def get_biosimulator_workflow_runs(self, file_hash_md5: str, image_digest: str, cache_buster: str) \
            -> list[BiosimulatorWorkflowRun]:
        pass

    @abstractmethod
    async def get_biosimulator_workflow_runs_by_biosim_runid(self, biosim_run_id: str) -> list[BiosimulatorWorkflowRun]:
        pass

    @abstractmethod
    async def delete_biosimulator_workflow_run(self, database_id: str) -> None:
        pass

    @abstractmethod
    async def delete_all_biosimulator_workflow_runs(self) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class DatabaseServiceMongo(DatabaseService):
    _db_client: AsyncIOMotorClient
    _sim_output_col: AsyncIOMotorCollection

    def __init__(self, db_client: AsyncIOMotorClient) -> None:
        self._db_client = db_client
        database = self._db_client.get_database(get_settings().mongodb_database)
        self._sim_output_col = database.get_collection(get_settings().mongodb_collection_sims)

    @override
    async def insert_biosimulator_workflow_run(self, sim_workflow_run: BiosimulatorWorkflowRun) -> BiosimulatorWorkflowRun:
        if sim_workflow_run.database_id is not None:
            raise Exception("Cannot insert document that already has a database id")
        sim_ver_str = f"{sim_workflow_run.simulator_version.id}:{sim_workflow_run.simulator_version.version}"
        logger.info(f"Inserting OMEX sim output for {sim_ver_str} with OMEX hash {sim_workflow_run.file_hash_md5}")
        result: InsertOneResult = await self._sim_output_col.insert_one(sim_workflow_run.model_dump())
        if result.acknowledged:
            inserted_sim_output: BiosimulatorWorkflowRun = sim_workflow_run.model_copy(deep=True)
            inserted_sim_output.database_id = str(result.inserted_id)
            return inserted_sim_output
        else:
            raise Exception("Insert failed")

    @override
    async def get_biosimulator_workflow_runs(self, file_hash_md5: str, image_digest: str, cache_buster: str) \
            -> list[BiosimulatorWorkflowRun]:
        logger.info(f"Getting OMEX sim workflow output with file hash {file_hash_md5} and sim digest {image_digest} and cache buster {cache_buster}")
        query = dict(file_hash_md5=file_hash_md5, image_digest=image_digest, cache_buster=cache_buster)
        document = await self._sim_output_col.find(query).to_list(length=100)
        workflow_runs: list[BiosimulatorWorkflowRun] = []
        if document is not None and type(document) is list:
            for doc in document:
                doc_dict = dict(doc)
                doc_dict["database_id"] = str(doc["_id"])
                del doc_dict["_id"]
                workflow_runs.append(BiosimulatorWorkflowRun.model_validate(doc_dict))
            return workflow_runs
        else:
            return []

    @override
    async def get_biosimulator_workflow_runs_by_biosim_runid(self, biosim_run_id: str) -> list[BiosimulatorWorkflowRun]:
        logger.info(f"Getting OMEX sim workflow output with biosim run id {biosim_run_id}")
        document = await self._sim_output_col.find({"biosim_run.id": biosim_run_id}).to_list(length=100)
        workflow_runs: list[BiosimulatorWorkflowRun] = []
        if document is not None and type(document) is list:
            for doc in document:
                doc_dict = dict(doc)
                doc_dict["database_id"] = str(doc["_id"])
                del doc_dict["_id"]
                workflow_runs.append(BiosimulatorWorkflowRun.model_validate(doc_dict))
            return workflow_runs
        else:
            return []

    @override
    async def delete_biosimulator_workflow_run(self, database_id: str) -> None:
        logger.info(f"Deleting OMEX sim workflow output with database_id {database_id}")
        result = await self._sim_output_col.delete_one({"_id": ObjectId(database_id)})
        if result.deleted_count == 1:
            return
        else:
            raise Exception("Delete failed")

    @override
    async def delete_all_biosimulator_workflow_runs(self) -> None:
        logger.info("Deleting all OMEX file records")
        result = await self._sim_output_col.delete_many({})
        if not result.acknowledged:
            raise Exception("Delete failed")


    @override
    async def close(self) -> None:
        self._db_client.close()
