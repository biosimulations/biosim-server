import logging
from abc import abstractmethod, ABC

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo.results import InsertOneResult
from typing_extensions import override

from biosim_server.config import get_settings
from biosim_server.biosim_omex.models import OmexFile

logger = logging.getLogger(__name__)


class OmexDatabaseService(ABC):
    @abstractmethod
    async def insert_omex_file(self, omex_file: OmexFile) -> OmexFile:
        pass

    @abstractmethod
    async def get_omex_file(self, file_hash_md5: str) -> OmexFile | None:
        pass

    @abstractmethod
    async def delete_omex_file(self, database_id: str) -> None:
        pass

    @abstractmethod
    async def delete_all_omex_files(self) -> None:
        pass

    @abstractmethod
    async def list_omex_files(self) -> list[OmexFile]:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class OmexDatabaseServiceMongo(OmexDatabaseService):
    _db_client: AsyncIOMotorClient
    _omex_file_col: AsyncIOMotorCollection

    def __init__(self, db_client: AsyncIOMotorClient) -> None:
        self._db_client = db_client
        database = self._db_client.get_database(get_settings().mongodb_database)
        self._omex_file_col = database.get_collection(get_settings().mongodb_collection_omex)

    @override
    async def insert_omex_file(self, omex_file: OmexFile) -> OmexFile:
        if omex_file.database_id is not None:
            raise Exception("Cannot insert document that already has a database id")
        logger.info(f"Inserting OMEX file with hash {omex_file.file_hash_md5}")
        result: InsertOneResult = await self._omex_file_col.insert_one(omex_file.model_dump())
        if result.acknowledged:
            inserted_omex_file: OmexFile = omex_file.model_copy(deep=True)
            inserted_omex_file.database_id = str(result.inserted_id)
            return inserted_omex_file
        else:
            raise Exception("Insert failed")

    # @lru_cache
    @override
    async def get_omex_file(self, file_hash_md5: str) -> OmexFile | None:
        logger.info(f"Getting OMEX file with hash {file_hash_md5}")
        document = await self._omex_file_col.find_one({"file_hash_md5": file_hash_md5})
        if document is not None:
            doc_dict = dict(document)
            doc_dict["database_id"] = str(document["_id"])
            del doc_dict["_id"]
            return OmexFile.model_validate(doc_dict)
        else:
            return None

    @override
    async def delete_omex_file(self, database_id: str) -> None:
        logger.info(f"Deleting OMEX file with database_id {database_id}")
        result = await self._omex_file_col.delete_one({"_id": ObjectId(database_id)})
        if result.deleted_count == 1:
            return
        else:
            raise Exception("Delete failed")

    @override
    async def delete_all_omex_files(self) -> None:
        logger.info("Deleting all OMEX file records")
        result = await self._omex_file_col.delete_many({})
        if not result.acknowledged:
            raise Exception("Delete failed")

    @override
    async def list_omex_files(self) -> list[OmexFile]:
        logger.info("listing OMEX files")
        omex_files: list[OmexFile] = []
        for document in await self._omex_file_col.find().to_list(length=100):
            doc_dict = dict(document)
            doc_dict["database_id"] = str(document["_id"])
            del doc_dict["_id"]
            omex_files.append(OmexFile.model_validate(doc_dict))
        return omex_files

    @override
    async def close(self) -> None:
        self._db_client.close()
