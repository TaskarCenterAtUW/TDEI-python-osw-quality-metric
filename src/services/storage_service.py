# Class for Storage service.

from python_ms_core import Core
from src.config import Config

class StorageService:

    def __init__(self, core: Core) -> None:
        self.storage_client = core.get_storage_client()
        # TODO : Change storage location
        self.config = Config()
        self.storage_container = self.storage_client.get_container(self.config.storage_container_name)

    def upload_local_file(self, local_path: str, remote_path: str) -> str:
        azure_file = self.storage_container.create_file(remote_path)
        with open(local_path, 'rb') as file_stream:
            azure_file.upload(file_stream.read())
        remote_url = azure_file.get_remote_url()
        return remote_url

    def download_remote_file(self, remote_path: str, local_path: str) -> str:
        #  Change this to download from client
        file_entity = self.storage_client.get_file_from_url(self.config.storage_container_name, remote_path)
        
        with open(local_path, 'wb') as file_stream:
            file_stream.write(file_entity.get_stream())

        # just do wget
        # return wget.download(remote_path, local_path)
        return ''
