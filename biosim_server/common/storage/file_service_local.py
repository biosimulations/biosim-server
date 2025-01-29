import logging
import shutil
import uuid
from temporalio import workflow
with workflow.unsafe.imports_passed_through():
    from datetime import datetime
from pathlib import Path
from typing import List, Optional

import aiofiles
from typing_extensions import override

from biosim_server.common.storage.file_service import FileService, ListingItem


def generate_fake_etag(file_path: Path) -> str:
    return file_path.absolute().as_uri()


class FileServiceLocal(FileService):
    # temporary base directory for the mock GCS file store
    BASE_DIR_PARENT = Path(__file__).parent.parent.parent / "local_data"
    BASE_DIR = BASE_DIR_PARENT / ("gcs_" + uuid.uuid4().hex)

    gcs_files_written: list[Path] = []

    def init(self) -> None:
        self.BASE_DIR.mkdir(parents=True, exist_ok=False)

    @override
    async def close(self) -> None:
        # remove all files in the mock gcs file store
        shutil.rmtree(self.BASE_DIR)

    @override
    async def download_file(self, gcs_path: str, file_path: Optional[Path]=None) -> tuple[str, str]:
        if file_path is None:
            file_path = Path(__file__).parent / ("temp_file_"+uuid.uuid4().hex)
        # copy file from mock gcs to local file system
        gcs_file_path = self.BASE_DIR / gcs_path
        local_file_path = Path(file_path)
        local_file_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(gcs_file_path, mode='rb') as f:
            contents = await f.read()
            async with aiofiles.open(local_file_path, mode='wb') as f2:
                await f2.write(contents)
        return str(gcs_file_path), str(local_file_path)

    @override
    async def upload_file(self, file_path: Path, gcs_path: str) -> str:
        # copy file from local file_path to mock gcs using aoifiles
        local_file_path = Path(file_path)
        gcs_file_path = self.BASE_DIR / gcs_path
        gcs_file_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(local_file_path, mode='rb') as f:
            contents = await f.read()
            async with aiofiles.open(gcs_file_path, mode='wb') as f2:
                await f2.write(contents)
        self.gcs_files_written.append(gcs_file_path)
        logging.info(f"Uploaded file to gcs at {gcs_file_path}")
        return str(gcs_file_path)

    @override
    async def upload_bytes(self, file_contents: bytes, gcs_path: str) -> str:
        # write bytes to mock gcs
        gcs_file_path = self.BASE_DIR / gcs_path
        gcs_file_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(gcs_file_path, mode='wb') as f:
            await f.write(file_contents)
        self.gcs_files_written.append(gcs_file_path)
        return str(gcs_file_path)

    @override
    async def get_modified_date(self, gcs_path: str) -> datetime:
        # get the modified date of the file in mock gcs
        gcs_file_path = self.BASE_DIR / gcs_path
        return datetime.fromtimestamp(gcs_file_path.stat().st_mtime)

    @override
    async def get_listing(self, gcs_path: str) -> List[ListingItem]:
        # get the listing of the directory in mock gcs
        gcs_dir_path = self.BASE_DIR / gcs_path
        return [ListingItem(Key=str(file.relative_to(self.BASE_DIR)), Size=file.stat().st_size,
                            LastModified=datetime.fromtimestamp(file.stat().st_mtime), ETag=generate_fake_etag(file))
                for file in gcs_dir_path.rglob("*")]

    @override
    async def get_file_contents(self, gcs_path: str) -> bytes:
        # get the file contents from mock gcs
        gcs_file_path = self.BASE_DIR / gcs_path
        return gcs_file_path.read_bytes()
